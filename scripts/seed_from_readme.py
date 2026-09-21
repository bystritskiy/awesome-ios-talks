#!/usr/bin/env python3
"""Разовый импорт: переносит уже собранные вручную доклады из README.md в data/talks/.

Запускается один раз при переходе на генерируемый README. Повторный запуск безопасен:
существующие записи не перезатираются, добавляются только отсутствующие video_id.
"""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib

ROW = re.compile(r"^\|\s*\[(?P<title>.+?)\]\((?P<url>[^)]+)\)\s*\|(?P<rest>.*)\|\s*$")


def parse_readme(path):
    cat_by_title = {}
    for c in lib.categories():
        for name in [c["title"]] + c.get("aliases", []):
            cat_by_title.setdefault(name, c)
    talks, current = [], None
    stop = False
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("## "):
            name = line[3:].strip()
            if name in ("Площадки", "Полезное", "Мотивация", "Категории"):
                current = None
                stop = name in ("Площадки", "Полезное")
                continue
            current = cat_by_title.get(name, {}).get("slug") or "uncategorized"
            if name not in cat_by_title:
                print(f"  ! раздел README без категории в конфиге: {name}", file=sys.stderr)
            continue
        if stop or current is None:
            continue
        m = ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group("rest").split("|")]
        speakers_raw = cells[0] if cells else ""
        year = None
        for c in cells[1:]:
            if re.fullmatch(r"\d{4}", c):
                year = int(c)
        vid = lib.video_id(m.group("url"))
        talks.append({
            "video_id": vid,
            "url": lib.canonical_url(vid) if vid else m.group("url"),
            "title": m.group("title").strip(),
            "speakers": [s.strip() for s in re.split(r",|/", speakers_raw) if s.strip()],
            "year": year,
            "categories": [current],
            "source": "readme-seed",
            "curated": True,
        })
    return talks


def main():
    parsed = parse_readme(lib.README)
    db = lib.load_talks_db()
    existing = {t["video_id"]: t for t in db["talks"] if t.get("video_id")}
    dup_titles = {}
    added = 0
    for t in parsed:
        key = t["video_id"] or t["url"]
        if key in existing:
            # один и тот же video_id встречается в README у разных докладов (битые ссылки):
            # сохраняем как отдельную запись с пометкой, чтобы не потерять данные
            prev = existing[key]
            if lib.norm_title(prev["title"]) != lib.norm_title(t["title"]):
                t["url_conflict"] = True
                t["video_id"] = None
                dup_titles.setdefault(key, []).append(t["title"])
                db["talks"].append(t)
                added += 1
            continue
        existing[key] = t
        db["talks"].append(t)
        added += 1
    lib.save_talks_db(db)
    print(f"Импортировано {added} докладов (всего в базе {len(db['talks'])})")
    for vid, titles in dup_titles.items():
        print(f"  ! ссылка {lib.canonical_url(vid)} используется несколькими докладами: {titles}")


if __name__ == "__main__":
    main()
