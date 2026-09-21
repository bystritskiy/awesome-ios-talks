"""Общие утилиты пайплайна awesome-ios-talks. Только stdlib."""
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(ROOT, "sources")
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
CANDIDATES_DIR = os.path.join(DATA, "candidates")   # <channel_slug>.jsonl
TALKS_DIR = os.path.join(DATA, "talks")             # <year>.json
STORED_DESC_LIMIT = 600
# тяжёлые поля нужны только для триажа; у решённых кандидатов их не храним
HEAVY_FIELDS = ("description", "tags", "chapters")
SETTLED = ("approved", "ignored", "rejected")
README = os.path.join(ROOT, "README.md")
TEMPLATE = os.path.join(ROOT, "templates", "README.md.tmpl")

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_RU_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь",
                 "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def save_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def channels(only_enabled=True):
    cfg = load_json(os.path.join(SOURCES, "channels.json"), {"channels": []})
    return [c for c in cfg["channels"] if c.get("enabled", True) or not only_enabled]


def categories():
    cfg = load_json(os.path.join(SOURCES, "categories.json"), {"categories": []})
    return cfg["categories"]


VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})")


def video_id(url):
    m = VIDEO_ID_RE.search(url or "")
    return m.group(1) if m else None


def canonical_url(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def norm(s):
    """Нормализация текста для сравнений: нижний регистр, ё→е, схлопнутые пробелы."""
    s = unicodedata.normalize("NFKC", s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


def norm_title(s):
    """Для дедупа по названию: убирает пунктуацию и служебные приставки."""
    s = norm(s)
    s = re.sub(r"^(доклад|митап|meetup|talk|запись)\s*[:—-]\s*", "", s)
    return re.sub(r"[^\w\s]", " ", s).strip()


def _replace_dir_files(directory, suffix, contents):
    """Пишет {имя: текст} в directory и удаляет файлы с тем же суффиксом, которых больше нет."""
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        if name.endswith(suffix) and name not in contents:
            os.remove(os.path.join(directory, name))
    for name, text in contents.items():
        path = os.path.join(directory, name)
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)


def load_talks_db():
    """База докладов, разложенная по годам: data/talks/<year>.json (без года — unknown.json)."""
    talks = []
    if os.path.isdir(TALKS_DIR):
        for name in sorted(os.listdir(TALKS_DIR)):
            if name.endswith(".json"):
                talks += load_json(os.path.join(TALKS_DIR, name), [])
    return {"talks": talks}


def save_talks_db(db):
    by_year = {}
    for t in db["talks"]:
        t = {k: v for k, v in t.items() if v not in (None, [], "")}
        by_year.setdefault(f"{t.get('year') or 'unknown'}.json", []).append(t)
    contents = {}
    for name, items in by_year.items():
        items.sort(key=lambda t: (t.get("video_id") or "", t.get("url") or "", t.get("title", "")))
        contents[name] = json.dumps(items, ensure_ascii=False, indent=2) + "\n"
    _replace_dir_files(TALKS_DIR, ".json", contents)


def load_candidates():
    """Пул кандидатов, разложенный по каналам: data/candidates/<channel_slug>.jsonl."""
    rows = []
    if os.path.isdir(CANDIDATES_DIR):
        for name in sorted(os.listdir(CANDIDATES_DIR)):
            if name.endswith(".jsonl"):
                rows += load_jsonl(os.path.join(CANDIDATES_DIR, name))
    return rows


def save_candidates(rows):
    by_chan = {}
    for r in rows:
        r = {k: v for k, v in r.items() if v not in (None, [], "")}
        if r.get("status") in SETTLED:
            if any(k in r for k in HEAVY_FIELDS):
                r = {k: v for k, v in r.items() if k not in HEAVY_FIELDS}
                r["slim"] = True  # входы триажа выброшены — пересуживать нельзя
        elif r.get("description"):
            # полное описание всегда можно добрать заново через enrich.py
            r["description"] = r["description"][:STORED_DESC_LIMIT]
        by_chan.setdefault(f"{r.get('channel_slug') or 'unknown'}.jsonl", []).append(r)
    contents = {}
    for name, items in by_chan.items():
        items.sort(key=lambda r: r["video_id"])
        contents[name] = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in items)
    _replace_dir_files(CANDIDATES_DIR, ".jsonl", contents)
