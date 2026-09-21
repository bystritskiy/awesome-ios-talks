#!/usr/bin/env python3
"""Сводка по базе и пулу кандидатов."""
import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib


def main():
    rows = lib.load_candidates()
    talks = lib.load_talks_db()["talks"]
    st = collections.Counter(r.get("status", "new") for r in rows)
    print(f"Пул кандидатов: {len(rows)}")
    for k, v in st.most_common():
        print(f"  {k:10} {v}")
    print(f"\nВ подборке: {len(talks)} докладов")
    cats = collections.Counter(c for t in talks for c in (t.get("categories") or []))
    titles = {c["slug"]: c["title"] for c in lib.categories()}
    for slug, n in cats.most_common(10):
        print(f"  {titles.get(slug, slug):45} {n}")
    speakers = collections.Counter(
        s for t in talks for s in (t.get("speakers") or []))
    print("\nЧаще всего выступают:")
    for name, n in speakers.most_common(10):
        print(f"  {name:35} {n}")
    years = collections.Counter(t.get("year") for t in talks if t.get("year"))
    print("\nПо годам: " + ", ".join(f"{y}:{years[y]}" for y in sorted(years)))
    pending = [r for r in rows if r.get("status") in ("candidate", "maybe")]
    if pending:
        print(f"\nЖдут ревью: {len(pending)} — python3 scripts/review.py")


if __name__ == "__main__":
    main()
