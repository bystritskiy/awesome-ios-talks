#!/usr/bin/env python3
"""Поиск YouTube-каналов по запросу — чтобы узнать канонический channel_id для sources/channels.json.

Использование:
    python3 scripts/discover_channels.py "CocoaHeads" "Mobius конференция"
"""
import json
import re
import sys
import urllib.parse
import urllib.request

SP_CHANNELS = "EgIQAg%3D%3D"  # фильтр «только каналы» в поисковой выдаче


def search(query, limit=8):
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode(
        {"search_query": query}) + "&sp=" + SP_CHANNELS
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept-Language": "ru,en"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    if not m:
        return []
    found, seen = [], set()

    def walk(node):
        if isinstance(node, dict):
            c = node.get("channelRenderer")
            if c and c.get("channelId") not in seen:
                seen.add(c["channelId"])
                desc = "".join(r.get("text", "") for r in
                               (c.get("descriptionSnippet") or {}).get("runs", []))
                found.append({
                    "id": c["channelId"],
                    "title": (c.get("title") or {}).get("simpleText", ""),
                    "handle": c.get("navigationEndpoint", {}).get(
                        "browseEndpoint", {}).get("canonicalBaseUrl", ""),
                    "subs": (c.get("videoCountText") or {}).get("simpleText", ""),
                    "description": desc[:120],
                })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(m.group(1)))
    return found[:limit]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    known = {c["id"] for c in json.load(
        open("sources/channels.json", encoding="utf-8"))["channels"]}
    for q in sys.argv[1:]:
        print(f"=== {q}")
        for c in search(q):
            mark = "*" if c["id"] in known else " "
            print(f" {mark} {c['id']}  {c['title'][:38]:40} {c['handle']:28} {c['subs']}")
            if c["description"]:
                print(f"     {c['description']}")
    print("\n* — канал уже в sources/channels.json")


if __name__ == "__main__":
    main()
