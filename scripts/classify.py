#!/usr/bin/env python3
"""Шаг 2. Эвристический триаж пула кандидатов.

Для каждого нового видео решает: похоже ли это на русскоязычный доклад по iOS/Apple,
достаёт спикера из названия и предлагает категорию. Ничего не публикует —
только расставляет status/score/hints, чтобы дальше это проверил человек или ИИ.

status:
    new        — ещё не смотрели
    candidate  — прошло фильтр, ждёт ревью
    maybe      — по названию не понять; ждёт описания (scripts/enrich.py), потом пересудим
    rejected   — отсеяно эвристикой (причина в reject_reason)
    approved   — подтверждено вручную, попадёт в README (ставится в review.py)
    ignored    — вручную отклонено навсегда

Использование:
    python3 scripts/classify.py            # только новые
    python3 scripts/classify.py --all      # пересчитать всё, кроме approved/ignored
"""
import argparse
import re
import sys
import unicodedata

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib

# --- сигналы релевантности -------------------------------------------------
IOS_STRONG = [
    "ios", "swift", "swiftui", "objective-c", "objective c", "objc", "obj-c", "xcode",
    "uikit", "appkit", "cocoa", "cocoapods", "iphone", "ipad", "apple", "macos", "watchos",
    "tvos", "visionos", "vision pro", "app store", "testflight", "core data", "coredata",
    "combine", "rxswift", "spm", "swift package", "wwdc", "айос", "эпл", "яблоч", "spritekit",
    "scenekit", "arkit", "coreml", "core ml", "avfoundation", "уикит", "свифт",
    "auto layout", "autolayout", "storyboard", "uitableview", "uicollectionview", "viper",
    "uiview", "uiviewcontroller", "swiftpm", "fastlane", "testflight", "mach-o", "dyld",
    "instruments", "lldb", "keychain", "userdefaults", "realm", "alamofire", "tuist",
    "xcodegen", "bitcode", "widgetkit", "app clip", "live activity", "core animation",
]
IOS_WEAK = ["мобильн", "mobile", "кроссплатформ", "cross-platform", "kmp", "kmm",
            "multiplatform", "flutter", "react native", "app clip", "мобил"]
ANDROID = ["android", "андроид", "kotlin", "jetpack", "compose", "gradle", "google play",
           "котлин", "aidl", "dagger", "hilt"]
BACKEND_OFF = ["backend", "бэкенд", "devops", "kubernetes", "postgres", "java ", "python",
               "frontend", "фронтенд", "react ", "vue", "golang", " go ", "1c", "sql server",
               "data science", "аналитик данных", "ml-инженер"]
JUNK = ["вакансия", "мы нанимаем", "реклама", "подкаст #", "анонс", "трейлер", "тизер",
        "поздравля", "корпоратив", "новогодн", "розыгрыш", "приглашаем", "открытие набора",
        "промо", "интро", "shorts", "#shorts", "нарезка", "тайм-код"]
TALK_HINTS = ["доклад", "митап", "meetup", "конференц", "cocoaheads", "talk", "лекция",
              "воркшоп", "workshop", "круглый стол", "devtalks", "секция"]

# --- вытаскивание спикера из названия --------------------------------------
# Названия бывают вида «Тема / Имя Фамилия (Компания)», «Тема | Имя Фамилия, Компания»,
# «Имя Фамилия (Компания) — Тема», «Тема — Имя Фамилия и Имя Фамилия».
NAME = r"[А-ЯЁA-Z][а-яёa-z'`-]+"
PERSON = re.compile(rf"^{NAME}(?:\s+{NAME}){{1,2}}$")
SEPARATORS = (" // ", " / ", " | ", " — ", " – ", " - ", " − ")
# слова, по которым «Яндекс Маркет» или «Tech Lamoda» отличаются от имени человека
ORG_WORDS = {
    "яндекс", "yandex", "маркет", "авито", "avito", "тинькофф", "tinkoff", "сбер", "сбербанк",
    "альфа", "банк", "bank", "tech", "mail", "vk", "ozon", "лаборатория", "касперского",
    "kaspersky", "group", "labs", "lab", "team", "еда", "карты", "такси", "музыка", "плюс",
    "superapp", "мтс", "циан", "wildberries", "lamoda", "surf", "redmadrobot", "badoo",
    "rambler", "digital", "studio", "мобайл", "mobile", "онлайн", "online", "доставка",
    "браузер", "аренда", "вертикали", "дзен", "маркета", "go", "про", "pro", "ltd", "inc",
    "gmbh", "llc", "cocoaheads", "mobius", "appsconf", "podlodka", "meetup", "митап",
}
NOISE_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]*\]|#\S+|(?:CocoaHeads|Mobius|AppsConf|MBLT\w*)[^|:–—/-]*)\s*[|:–—-]?\s*", re.I)
# хвосты и префиксы рубрик: «… / Круглый стол», «Лента Мобиуса // …», «Mobile Interview. …»
RUBRICS = re.compile(
    r"^(?:Лента Мобиуса|Mobius (?:Ribbon|Strip)|Yet Another Mobile Party|Mobile Interview)\s*(?://|/|\.|:)\s*"
    r"|\s*/\s*(?:Круглый стол|Яндекс Стримерская на Mobius)\s*$", re.I)
SPEAKER_SPLIT = re.compile(r"\s*(?:,|&|\bи\b|\band\b)\s*")


def is_person(part):
    words = part.split()
    if not PERSON.match(part) or any(w.lower() in ORG_WORDS for w in words):
        return False
    # имя пишется одним алфавитом: «Боевой Reverse Engineering» — не человек
    cyr = [bool(re.search("[а-яё]", w.lower())) for w in words]
    return all(cyr) or not any(cyr)


def parse_speakers(block):
    """«Иван Петров (Яндекс), Анна Смирнова» → [Иван Петров, Анна Смирнова]; не люди → None."""
    block = re.sub(r"\([^)]*\)", " ", block).strip(" .,")
    parts = re.split(r"(\s*(?:,|&|\bи\b|\band\b)\s*)", block)
    people = []
    for i in range(0, len(parts), 2):
        part = re.sub(r"\s+", " ", parts[i]).strip(" .")
        if not part:
            continue
        if is_person(part):
            people.append(part)
        elif people and parts[i - 1].strip() == "," and len(part.split()) <= 4:
            break          # хвост «, Компания» после имён
        else:
            return None
    return people or None


def cyrillic_share(people):
    return sum(bool(re.search("[а-яё]", p.lower())) for p in people) / len(people)


def split_speaker(title):
    t = unicodedata.normalize("NFKC", title)        # в том числе неразрывные пробелы
    t = re.sub(r"\s+", " ", t).strip()
    t = NOISE_PREFIX.sub("", t).strip()
    t = RUBRICS.sub("", t).strip()
    options = []   # (приоритет, название, спикеры)
    for sep in SEPARATORS:
        if sep not in t:
            continue
        pos = t.rfind(sep)
        people = parse_speakers(t[pos + len(sep):])
        if people and pos >= 6:
            options.append((cyrillic_share(people), 1, t[:pos], people))
        pos = t.find(sep)
        people = parse_speakers(t[:pos])
        if people and len(t) - pos > 6:
            options.append((cyrillic_share(people), 0, t[pos + len(sep):], people))
    if options:
        # при двусмысленности («Swift Method Dispatch — Сергей Турсунов») побеждают кириллические имена,
        # затем спикер в конце названия
        _, _, rest, people = max(options, key=lambda o: (o[0], o[1]))
        return rest.strip(" .–—-|/"), people
    m = re.match(rf"^({NAME}\s+{NAME})\s*:\s+(.{{6,}})$", t)
    if m and parse_speakers(m.group(1)):
        return m.group(2).strip(), parse_speakers(m.group(1))
    for m in reversed(list(re.finditer(r"\.\s+", t))):
        people = parse_speakers(t[m.end():])
        if people and m.start() >= 6:
            return t[:m.start()].strip(), people
    return t, []


def suggest_categories(text, cats):
    hits = []
    for c in cats:
        score = sum(1 for kw in c.get("keywords", []) if kw in text)
        if score:
            hits.append((score, c["slug"]))
    hits.sort(reverse=True)
    return [slug for _, slug in hits[:3]]


def judge(row, focus, cats):
    text = lib.norm(f"{row.get('title','')} {row.get('description','')}")
    dur = row.get("duration") or 0

    def any_in(words):
        return [w for w in words if w in text]

    ios = any_in(IOS_STRONG)
    weak = any_in(IOS_WEAK)
    android = any_in(ANDROID)
    off = any_in(BACKEND_OFF)
    junk = any_in(JUNK)

    score = 0
    score += 3 * len(ios[:3]) + len(weak[:2])
    score += 2 if any_in(TALK_HINTS) else 0
    score += {"ios": 3, "mobile": 1, "general": 0}[focus]
    score -= 2 * len(android[:2]) + len(off[:2])

    enriched = bool(row.get("enriched"))

    if junk:
        return "rejected", score, f"служебное видео: {junk[0]}"
    lang = row.get("audio_lang")
    if lang and lang not in ("ru", "unknown"):
        return "rejected", score, f"доклад не на русском ({lang})"
    if dur and dur < 480:
        return "rejected", score, f"слишком короткое ({dur // 60} мин)"
    if android and not ios:
        return "rejected", score, f"про Android: {android[0]}"
    if ios:
        return "candidate", score, None
    if off:
        return "rejected", score, f"не про мобилки: {off[0]}"
    if focus == "ios":
        # на профильном канале доверяем каналу, даже если в названии нет ключевых слов
        return "candidate", score, None
    if focus == "mobile" and (weak or not enriched):
        # конференции по мобилкам: без описания по названию не отличить трек iOS от Android
        return ("candidate" if weak and enriched else "maybe"), score, None
    return "rejected", score, ("нет iOS-сигналов в названии и описании" if enriched
                               else "нет iOS-сигналов в названии")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="пересчитать всё, кроме approved/ignored")
    args = ap.parse_args()

    cats = lib.categories()
    focus = {c["slug"]: c.get("focus", "general") for c in lib.channels(only_enabled=False)}
    rows = lib.load_candidates()
    stats = {"candidate": 0, "rejected": 0, "maybe": 0, "skip": 0}

    for r in rows:
        st = r.get("status", "new")
        if st in ("approved", "ignored") or (st not in ("new", "maybe") and not args.all) \
                or r.get("slim"):
            stats["skip"] += 1
            continue
        title, speakers = split_speaker(r.get("title", ""))
        r["clean_title"] = title
        r["speakers_guess"] = speakers
        new_st, score, reason = judge(r, focus.get(r["channel_slug"], "general"), cats)
        r["status"] = new_st
        r["score"] = score
        r["reject_reason"] = reason
        r["categories_guess"] = suggest_categories(
            lib.norm(f"{title} {r.get('description','')}"), cats) or ["uncategorized"]
        stats[new_st] += 1

    lib.save_candidates(rows)
    total = {}
    for r in rows:
        total[r.get("status", "new")] = total.get(r.get("status", "new"), 0) + 1
    print(f"Обработано: +{stats['candidate']} candidate, +{stats['rejected']} rejected, "
          f"{stats['skip']} без изменений")
    print("Пул целиком: " + ", ".join(f"{k}={v}" for k, v in sorted(total.items())))


if __name__ == "__main__":
    main()
