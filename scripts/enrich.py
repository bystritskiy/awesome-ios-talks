#!/usr/bin/env python3
"""Шаг 3. Догрузка описаний, дат и тегов для отобранных кандидатов.

Два бэкенда:

  api    (по умолчанию, если задан YOUTUBE_API_KEY) — YouTube Data API v3,
         videos.list по 50 id за запрос. Быстро, без блокировок:
         1500 видео ≈ 30 запросов ≈ 30 единиц квоты из 10 000 в сутки.
         Ключ бесплатный: console.cloud.google.com → YouTube Data API v3 → API key.

  ytdlp  — без ключа, но по одному запросу на видео. YouTube быстро отвечает
         «Sign in to confirm you're not a bot», поэтому здесь один поток,
         пауза между запросами и остановка при серии отказов.

Использование:
    export YOUTUBE_API_KEY=...            # необязательно, но сильно лучше
    python3 scripts/enrich.py
    python3 scripts/enrich.py --backend ytdlp --sleep 3 --limit 100
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib

DESC_LIMIT = 2000
API_URL = "https://www.googleapis.com/youtube/v3/videos"
ISO_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(s):
    m = ISO_DUR.fullmatch(s or "")
    if not m:
        return None
    d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + sec


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def enrich_api(ids, key):
    """Возвращает {video_id: meta}. Бросает исключение при ошибке запроса."""
    out = {}
    for batch in chunks(ids, 50):
        url = API_URL + "?" + urllib.parse.urlencode({
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(batch),
            "key": key,
            "maxResults": 50,
        })
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.load(resp)
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            published = sn.get("publishedAt", "")
            out[item["id"]] = {
                "description": (sn.get("description") or "")[:DESC_LIMIT],
                "upload_date": published[:10].replace("-", "") or None,
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "duration": parse_duration(item.get("contentDetails", {}).get("duration")),
                "view_count": int(item.get("statistics", {}).get("viewCount", 0)) or None,
                "like_count": int(item.get("statistics", {}).get("likeCount", 0)) or None,
                "tags": (sn.get("tags") or [])[:20],
                "channel_title": sn.get("channelTitle"),
                "enriched": True,
                "enrich_error": None,
            }
        missing = set(batch) - set(out)
        for vid in missing:
            out[vid] = {"enriched": True, "enrich_error": "видео недоступно (удалено или приватное)"}
        print(f"  +{len(batch)} (всего {len(out)}/{len(ids)})", flush=True)
    return out


def enrich_ytdlp_one(vid):
    p = subprocess.run(
        ["yt-dlp", "-J", "--skip-download", "--no-warnings", "--no-playlist",
         lib.canonical_url(vid)],
        capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        return None, (p.stderr.strip().splitlines() or ["пусто"])[-1][:140]
    d = json.loads(p.stdout)
    return {
        "description": (d.get("description") or "")[:DESC_LIMIT],
        "upload_date": d.get("upload_date"),
        "year": int(d["upload_date"][:4]) if d.get("upload_date") else None,
        "duration": d.get("duration"),
        "view_count": d.get("view_count"),
        "like_count": d.get("like_count"),
        "tags": (d.get("tags") or [])[:20],
        "chapters": [c.get("title") for c in (d.get("chapters") or [])][:40],
        "enriched": True,
        "enrich_error": None,
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["auto", "api", "ytdlp"], default="auto")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=2.0, help="пауза между запросами (ytdlp)")
    ap.add_argument("--status", nargs="*", default=["candidate", "maybe", "approved"])
    ap.add_argument("--retry-errors", action="store_true", help="повторить неудачные")
    args = ap.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    backend = args.backend
    if backend == "auto":
        backend = "api" if key else "ytdlp"
    if backend == "api" and not key:
        sys.exit("нужен YOUTUBE_API_KEY (или --backend ytdlp)")

    rows = lib.load_candidates()
    by_id = {r["video_id"]: r for r in rows}
    todo = [r["video_id"] for r in rows
            if r.get("status") in args.status
            and (not r.get("enriched") or (args.retry_errors and r.get("enrich_error")))]
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print("Нечего обогащать")
        return
    print(f"Бэкенд {backend}, к обработке {len(todo)} видео", flush=True)

    if backend == "api":
        meta = enrich_api(todo, key)
        for vid, m in meta.items():
            by_id[vid].update(m)
        lib.save_candidates(rows)
        bad = sum(1 for m in meta.values() if m.get("enrich_error"))
        print(f"Готово: {len(meta) - bad} обогащено, {bad} недоступно")
        return

    ok = fail = streak = 0
    for i, vid in enumerate(todo, 1):
        m, err = enrich_ytdlp_one(vid)
        if m:
            by_id[vid].update(m)
            ok, streak = ok + 1, 0
        else:
            by_id[vid]["enrich_error"] = err
            fail += 1
            streak += 1
            if "Sign in to confirm" in err:
                streak += 4  # YouTube включил антибота — дальше смысла мало
        if i % 20 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} (ошибок {fail})", flush=True)
            lib.save_candidates(rows)
        if streak >= 10:
            print("  YouTube начал отдавать отказы подряд — останавливаюсь. "
                  "Задайте YOUTUBE_API_KEY или увеличьте --sleep.")
            break
        time.sleep(args.sleep)
    lib.save_candidates(rows)
    print(f"Готово: {ok} обогащено, {fail} с ошибкой")


if __name__ == "__main__":
    main()
