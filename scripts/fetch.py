#!/usr/bin/env python3
"""Шаг 1. Обход каналов из sources/channels.json через yt-dlp.

Забирает «плоский» список видео (id, название, длительность, просмотры) — это дёшево
и не требует API-ключа. Описания и даты добираются позже, в scripts/enrich.py,
и только для отобранных кандидатов.

Результат: data/raw/<slug>.json (сырые дампы) и data/candidates/<slug>.jsonl (пул по каналам).

Использование:
    python3 scripts/fetch.py                # все включённые каналы
    python3 scripts/fetch.py cocoaheads     # только указанные slug'и
    python3 scripts/fetch.py --limit 50     # первые N видео канала (для отладки)
"""
import argparse
import json
import subprocess
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib

TABS = ("videos", "streams")


def ytdlp_flat(url, limit=None):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--ignore-errors",
           "--extractor-args", "youtubetab:approximate_date"]
    if limit:
        cmd += ["--playlist-items", f"1-{limit}"]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        return None, (p.stderr.strip().splitlines() or ["пустой ответ"])[-1]
    try:
        return json.loads(p.stdout), None
    except json.JSONDecodeError as e:
        return None, f"не разобрался JSON: {e}"


def fetch_channel(ch, limit=None):
    rows = []
    for tab in TABS:
        url = f"https://www.youtube.com/channel/{ch['id']}/{tab}"
        data, err = ytdlp_flat(url, limit)
        if err:
            print(f"    {tab}: пропущено ({err[:90]})")
            continue
        entries = data.get("entries") or []
        for e in entries:
            if not e or not e.get("id"):
                continue
            rows.append({
                "video_id": e["id"],
                "url": lib.canonical_url(e["id"]),
                "title": (e.get("title") or "").strip(),
                "duration": e.get("duration"),
                "view_count": e.get("view_count"),
                "timestamp": e.get("timestamp"),
                "tab": tab,
                "channel_slug": ch["slug"],
                "channel_title": ch["title"],
                "channel_id": ch["id"],
            })
        print(f"    {tab}: {len(entries)}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    chans = lib.channels()
    if args.slugs:
        chans = [c for c in lib.channels(only_enabled=False) if c["slug"] in args.slugs]

    pool = {c["video_id"]: c for c in lib.load_candidates()}
    before = len(pool)
    for ch in chans:
        print(f"[{ch['slug']}] {ch['title']}")
        t0 = time.time()
        rows = fetch_channel(ch, args.limit)
        lib.save_json(f"{lib.RAW}/{ch['slug']}.json", rows)
        new = 0
        for r in rows:
            prev = pool.get(r["video_id"])
            if prev:
                # обновляем волатильные поля, сохраняя решения триажа
                prev.update({k: r[k] for k in ("title", "duration") if r.get(k)})
            else:
                r["status"] = "new"
                pool[r["video_id"]] = r
                new += 1
        print(f"    итого {len(rows)}, новых {new}, {time.time() - t0:.0f}s")

    rows = sorted(pool.values(), key=lambda r: (r["channel_slug"], r["video_id"]))
    lib.save_candidates(rows)
    print(f"\nПул кандидатов: {len(rows)} (+{len(rows) - before})")


if __name__ == "__main__":
    main()
