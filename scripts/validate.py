#!/usr/bin/env python3
"""Проверка целостности конфигов и базы докладов (используется в CI)."""
import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib


def main():
    problems = []
    cats = lib.categories()
    slugs = [c["slug"] for c in cats]
    for slug, n in collections.Counter(slugs).items():
        if n > 1:
            problems.append(f"категория {slug} объявлена {n} раза")
    for slug, n in collections.Counter(c["slug"] for c in lib.channels(only_enabled=False)).items():
        if n > 1:
            problems.append(f"канал {slug} объявлен {n} раза")

    talks = lib.load_talks_db()["talks"]
    seen_ids, seen_titles = {}, {}
    for t in talks:
        title = t.get("title", "")
        if not title:
            problems.append(f"доклад без названия: {t.get('url')}")
        if not t.get("url") and not t.get("needs_link"):
            problems.append(f"доклад без ссылки: {title}")
        for c in t.get("categories") or []:
            if c not in slugs:
                problems.append(f"неизвестная категория {c!r} у «{title}»")
        vid = t.get("video_id")
        if vid:
            if vid in seen_ids:
                problems.append(f"дубль video_id {vid}: «{seen_ids[vid]}» и «{title}»")
            seen_ids[vid] = title
        key = lib.norm_title(title)
        if key and key in seen_titles:
            problems.append(f"похожие названия: «{seen_titles[key]}» и «{title}»")
        seen_titles[key] = title
        if t.get("url_conflict"):
            problems.append(f"ссылка требует проверки (взята у другого доклада): «{title}»")

    if problems:
        print(f"Найдено проблем: {len(problems)}")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"OK: {len(talks)} докладов, {len(cats)} категорий")


if __name__ == "__main__":
    main()
