#!/usr/bin/env python3
"""Шаг 4б. Перенос одобренных кандидатов в базу докладов data/talks/<год>.json.

Использование:
    python3 scripts/promote.py abc12345678 --category swift --speaker "Иван Петров"
    python3 scripts/promote.py abc12345678 def45678901 --category tests
    python3 scripts/promote.py --ignore abc12345678          # отклонить навсегда
    python3 scripts/promote.py --auto --min-score 8          # массово, по догадке классификатора
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib


def to_talk(r, categories):
    return {
        "video_id": r["video_id"],
        "url": r["url"],
        "title": (r.get("clean_title") or r.get("title") or "").strip(),
        "speakers": r.get("speakers") or r.get("speakers_guess") or [],
        "year": r.get("year"),
        "categories": categories,
        "channel_slug": r.get("channel_slug"),
        "channel_title": r.get("channel_title"),
        "duration": r.get("duration"),
        "source": "youtube",
        "curated": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="*")
    ap.add_argument("--category", action="append", default=[])
    ap.add_argument("--speaker", action="append", default=[])
    ap.add_argument("--title")
    ap.add_argument("--year", type=int)
    ap.add_argument("--ignore", action="store_true", help="отклонить навсегда")
    ap.add_argument("--auto", action="store_true", help="взять всех кандидатов от --min-score")
    ap.add_argument("--min-score", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    valid = {c["slug"] for c in lib.categories()}
    bad = [c for c in args.category if c not in valid]
    if bad:
        sys.exit(f"неизвестные категории: {bad}. Доступны: {sorted(valid)}")

    rows = lib.load_candidates()
    by_id = {r["video_id"]: r for r in rows}
    targets = list(args.video_ids)
    if args.auto:
        targets += [r["video_id"] for r in rows
                    if r.get("status") == "candidate" and (r.get("score") or 0) >= args.min_score]
    if not targets:
        sys.exit("нечего переносить: укажите video_id или --auto")

    db = lib.load_talks_db()
    known = {t.get("video_id") for t in db["talks"]}
    added = ignored = 0
    for vid in dict.fromkeys(targets):
        r = by_id.get(vid)
        if not r:
            print(f"  ? {vid} нет в пуле кандидатов")
            continue
        if args.ignore:
            r["status"] = "ignored"
            ignored += 1
            continue
        r["status"] = "approved"
        if vid in known:
            continue
        cats = args.category or r.get("categories_guess") or ["uncategorized"]
        talk = to_talk(r, cats)
        if args.speaker:
            talk["speakers"] = args.speaker
        if args.title:
            talk["title"] = args.title
        if args.year:
            talk["year"] = args.year
        db["talks"].append(talk)
        known.add(vid)
        added += 1
        print(f"  + [{','.join(cats)}] {talk['title'][:70]}")
    if args.dry_run:
        print(f"(dry-run) добавилось бы {added}, отклонено {ignored}")
        return
    lib.save_candidates(rows)
    lib.save_talks_db(db)
    print(f"Добавлено {added}, отклонено {ignored}. Всего в базе {len(db['talks'])}")


if __name__ == "__main__":
    main()
