#!/usr/bin/env python3
"""Массовое применение решений ревью.

Формат файла решений — по строке на видео, поля через табуляцию:

    <video_id>\t-                                  отклонить навсегда (ignored)
    <video_id>\t<категории через запятую>[\t<спикеры через ;>][\t<название>]

Строки, начинающиеся с #, и пустые игнорируются.

    python3 scripts/apply_review.py decisions.tsv [--dry-run]
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib
from promote import to_talk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    valid = {c["slug"] for c in lib.categories()}
    rows = lib.load_candidates()
    by_id = {r["video_id"]: r for r in rows}
    db = lib.load_talks_db()
    known = {t.get("video_id"): t for t in db["talks"] if t.get("video_id")}

    kept = skipped = 0
    problems = []
    for lineno, line in enumerate(open(args.path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        vid = parts[0].strip()
        r = by_id.get(vid)
        if not r:
            problems.append(f"строка {lineno}: {vid} нет в пуле")
            continue
        spec = parts[1].strip() if len(parts) > 1 else "-"
        if spec == "-":
            r["status"] = "ignored"
            skipped += 1
            continue
        cats = [c.strip() for c in spec.split(",") if c.strip()]
        bad = [c for c in cats if c not in valid]
        if bad:
            problems.append(f"строка {lineno}: неизвестные категории {bad}")
            continue
        speakers = [s.strip() for s in parts[2].split(";")] if len(parts) > 2 and parts[2].strip() else None
        title = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None

        r["status"] = "approved"
        talk = known.get(vid) or to_talk(r, cats)
        talk["categories"] = cats
        if speakers:
            talk["speakers"] = speakers
        if title:
            talk["title"] = title
        if vid not in known:
            db["talks"].append(talk)
            known[vid] = talk
        kept += 1

    for p in problems:
        print("  ! " + p)
    if args.dry_run:
        print(f"(dry-run) принято {kept}, отклонено {skipped}")
        return
    lib.save_candidates(rows)
    lib.save_talks_db(db)
    print(f"Принято {kept}, отклонено {skipped}. Всего в базе {len(db['talks'])}")


if __name__ == "__main__":
    main()
