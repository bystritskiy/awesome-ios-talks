#!/usr/bin/env python3
"""Шаг 4а. Инбокс ревью: выгружает необработанных кандидатов в data/review.md.

Файл — для глаз (или для ИИ-ассистента): по нему удобно пройтись и решить,
что забирать в README. Решения применяются через scripts/promote.py.

Использование:
    python3 scripts/review.py [--min-score 4] [--limit 300]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib


LINKY = re.compile(r"https?://\S+|@\S+|#\S+|\d{1,2}:\d{2}(?::\d{2})?")
BOILER = re.compile(
    r"(подписыва\w*|наш telegram|наши соцсети|тайм-?коды|больше докладов|"
    r"присоединяйтесь|все доклады|смотрите также|— — —|___+|\*\*\*+)", re.I)


def snippet(desc, limit=180):
    """Первые осмысленные слова описания: без ссылок, тайм-кодов и подвала канала."""
    text = LINKY.sub(" ", desc or "")
    parts = []
    for line in text.splitlines():
        line = line.strip(" -—|·•")
        if not line or BOILER.search(line):
            continue
        parts.append(line)
        if sum(len(p) for p in parts) > limit:
            break
    return re.sub(r"\s+", " ", " ".join(parts))[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="0 — без ограничения")
    ap.add_argument("--status", default="candidate")
    ap.add_argument("--format", choices=["md", "tsv"], default="md",
                    help="tsv — компактная выгрузка в stdout для построчного разбора")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--channel", nargs="*", help="только эти каналы")
    args = ap.parse_args()

    rows = [r for r in lib.load_candidates()
            if r.get("status") == args.status and (r.get("score") or 0) >= args.min_score]
    if args.channel:
        rows = [r for r in rows if r.get("channel_slug") in args.channel]
    rows.sort(key=lambda r: (r.get("channel_slug", ""), -(r.get("score") or 0),
                             r.get("video_id", "")))
    rows = rows[args.offset:]
    rows = rows[:args.limit] if args.limit else rows

    if args.format == "tsv":
        for r in rows:
            print("\t".join((
                r["video_id"],
                r.get("channel_slug", ""),
                str(r.get("year") or ""),
                str(round((r.get("duration") or 0) / 60)),
                (r.get("clean_title") or r.get("title") or "").replace("\t", " "),
                ", ".join(r.get("speakers_guess") or []),
                snippet(r.get("description"), 180),
            )))
        return

    out = [f"# Ревью кандидатов ({len(rows)})", "",
           "Команды: `python3 scripts/promote.py <video_id> --category <slug>` — забрать в README, ",
           "`python3 scripts/promote.py <video_id> --ignore` — отклонить навсегда.", ""]
    by_chan = {}
    for r in rows:
        by_chan.setdefault(r.get("channel_title", "?"), []).append(r)
    for chan, items in sorted(by_chan.items(), key=lambda kv: -len(kv[1])):
        out.append(f"## {chan} ({len(items)})")
        out.append("")
        out.append("| score | Видео | Спикер | Год | Категории (догадка) | id |")
        out.append("| :-: | --- | --- | :-: | --- | :-: |")
        for r in items:
            sp = ", ".join(r.get("speakers_guess") or []) or "—"
            cats = ", ".join(r.get("categories_guess") or [])
            title = (r.get("clean_title") or r.get("title") or "").replace("|", "\\|")
            out.append(f"| {r.get('score', 0)} | [{title}]({r['url']}) | {sp} | "
                       f"{r.get('year') or '—'} | {cats} | `{r['video_id']}` |")
        out.append("")
    path = os.path.join(lib.DATA, "review.md")
    os.makedirs(lib.DATA, exist_ok=True)
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{len(rows)} кандидатов -> {path}")


if __name__ == "__main__":
    main()
