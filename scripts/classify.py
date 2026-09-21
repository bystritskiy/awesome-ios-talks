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
NAME = r"[А-ЯЁA-Z][а-яёa-z'`-]+"
SPEAKER_PATTERNS = [
    re.compile(rf"^\s*(?P<sp>{NAME}\s+{NAME}(?:\s*[,и]\s*{NAME}\s+{NAME})*)\s*[–—\-−:|.]\s+(?P<t>.{{6,}})$"),
    re.compile(rf"^(?P<t>.{{6,}}?)\s*[/|]\s*(?P<sp>{NAME}\s+{NAME})\s*$"),
    re.compile(rf"^(?P<t>.{{6,}}?)\s*[–—\-−]\s*(?P<sp>{NAME}\s+{NAME})\s*$"),
]
NOISE_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]*\]|\([^)]*\)|#\S+|CocoaHeads[^|:–—-]*|Mobius[^|:–—-]*|AppsConf[^|:–—-]*)\s*[|:–—-]?\s*",
    re.I)


def split_speaker(title):
    t = NOISE_PREFIX.sub("", title).strip()
    for pat in SPEAKER_PATTERNS:
        m = pat.match(t)
        if m:
            speakers = [s.strip() for s in re.split(r"[,и]\s+(?=[А-ЯЁA-Z])", m.group("sp")) if s.strip()]
            return m.group("t").strip(" .–—-"), speakers
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
