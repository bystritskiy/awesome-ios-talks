#!/usr/bin/env python3
"""Шаг 3. Догрузка описаний, дат и тегов для отобранных кандидатов.

Два бэкенда:

  api    (по умолчанию, если задан YOUTUBE_API_KEY) — YouTube Data API v3,
         videos.list по 50 id за запрос. Быстро, без блокировок:
         1500 видео ≈ 30 запросов ≈ 30 единиц квоты из 10 000 в сутки.
         Ключ бесплатный: console.cloud.google.com → YouTube Data API v3 → API key.
         Название берётся из API: там всегда оригинал, а yt-dlp может отдать
         автоперевод YouTube под локаль запроса.
         Для кандидатов на ревью дополнительно определяется язык доклада — по
         автосубтитрам (captions.list, 50 единиц на видео). Поле defaultAudioLanguage
         для этого не годится: его выставляет канал сразу на все видео.

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
from classify import split_speaker

DESC_LIMIT = 2000
API_URL = "https://www.googleapis.com/youtube/v3/videos"
CAPTIONS_URL = "https://www.googleapis.com/youtube/v3/captions"
PENDING = ("candidate", "maybe")
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
                "title": sn.get("title"),
                "title_source": "api",
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


def caption_language(vid, key):
    """Язык автоматических субтитров (asr) = язык, на котором говорят в видео. None, если их нет."""
    url = CAPTIONS_URL + "?" + urllib.parse.urlencode({"part": "snippet", "videoId": vid, "key": key})
    with urllib.request.urlopen(url, timeout=60) as resp:
        items = json.load(resp).get("items", [])
    for it in items:
        if it["snippet"].get("trackKind") == "asr":
            return it["snippet"].get("language", "").split("-")[0] or None
    return None


def apply_meta(row, meta):
    old_title = row.get("title")
    row.update(meta)
    if meta.get("title") and meta["title"] != old_title:
        row["clean_title"], row["speakers_guess"] = split_speaker(meta["title"])


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


def detect_languages(rows, key, limit):
    todo = [r for r in rows if r.get("status") in PENDING and "audio_lang" not in r][:limit]
    if not todo:
        return
    print(f"Определяю язык у {len(todo)} кандидатов ({len(todo) * 50} единиц квоты)", flush=True)
    langs = {}
    for r in todo:
        try:
            r["audio_lang"] = caption_language(r["video_id"], key) or "unknown"
        except urllib.error.HTTPError as e:
            print(f"  captions.list: HTTP {e.code} — останавливаюсь (квота?)")
            break
        langs[r["audio_lang"]] = langs.get(r["audio_lang"], 0) + 1
    lib.save_candidates(rows)
    print("  языки: " + ", ".join(f"{k}={v}" for k, v in sorted(langs.items())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["auto", "api", "ytdlp"], default="auto")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=2.0, help="пауза между запросами (ytdlp)")
    ap.add_argument("--status", nargs="*", default=["candidate", "maybe", "approved"])
    ap.add_argument("--retry-errors", action="store_true", help="повторить неудачные")
    ap.add_argument("--refetch", action="store_true",
                    help="перезапросить и уже обогащённые (например, чтобы обновить названия)")
    ap.add_argument("--lang-limit", type=int, default=150,
                    help="сколько кандидатов проверять на язык за прогон (50 единиц квоты за видео)")
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
            and (args.refetch or not r.get("enriched")
                 or (args.retry_errors and r.get("enrich_error")))]
    if args.limit:
        todo = todo[:args.limit]
    if backend == "api":
        if todo:
            print(f"Бэкенд api, к обработке {len(todo)} видео", flush=True)
            meta = enrich_api(todo, key)
            for vid, m in meta.items():
                apply_meta(by_id[vid], m)
            lib.save_candidates(rows)
            bad = sum(1 for m in meta.values() if m.get("enrich_error"))
            print(f"Готово: {len(meta) - bad} обогащено, {bad} недоступно")
        detect_languages(rows, key, args.lang_limit)
        return
    if not todo:
        print("Нечего обогащать")
        return
    print(f"Бэкенд {backend}, к обработке {len(todo)} видео", flush=True)

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
