#!/usr/bin/env python3
"""Шаг 5. Сборка README.md из data/talks/*.json и templates/README.md.tmpl.

README — артефакт сборки: правки вносятся в базу докладов или в шаблон.

Использование:
    python3 scripts/build_readme.py [--check]   # --check: не писать, а проверить актуальность
"""
import argparse
import collections
import datetime
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lib


def esc(s):
    return (s or "").replace("|", "\\|").strip()


def talk_sort_key(t):
    return (-(t.get("year") or 0), lib.norm(t.get("title", "")))


def render_talks(talks, cats):
    by_cat = collections.defaultdict(list)
    for t in talks:
        if t.get("needs_link") or not t.get("url"):
            continue
        for slug in t.get("categories") or ["uncategorized"]:
            by_cat[slug].append(t)
    out = []
    for c in cats:
        items = sorted(by_cat.get(c["slug"], []), key=talk_sort_key)
        if not items:
            continue
        out.append(f"### {c['title']} ({len(items)})")
        out.append("")
        out.append(f"| Тема | {c.get('speaker_column', 'Автор')} | Год |")
        out.append("| :-- | :-- | :-: |")
        for t in items:
            speakers = ", ".join(t.get("speakers") or []) or "—"
            out.append(f"| [{esc(t['title'])}]({t['url']}) | {esc(speakers)} | {t.get('year') or '—'} |")
        out.append("")
    unknown = set(by_cat) - {c["slug"] for c in cats}
    if unknown:
        print(f"  ! категории вне конфига: {sorted(unknown)}", file=sys.stderr)
    return "\n".join(out).strip()


def render_years(talks):
    per_year = collections.Counter(t.get("year") for t in talks if t.get("year"))
    if not per_year:
        return "_пока нет данных_"
    rows = ["| Год | Докладов |", "| :-: | :-: |"]
    for year in sorted(per_year, reverse=True):
        rows.append(f"| {year} | {per_year[year]} |")
    return "\n".join(rows)


def render_channels(talks):
    per_chan = collections.Counter(t.get("channel_slug") for t in talks if t.get("channel_slug"))
    pool = collections.Counter()
    for r in lib.load_candidates():
        pool[r["channel_slug"]] += 1
    rows = ["| Канал | Видео в пуле | В подборке |", "| :-- | :-: | :-: |"]
    for c in lib.channels(only_enabled=False):
        if not c.get("enabled", True) and not pool.get(c["slug"]):
            continue
        link = f"[{c['title']}](https://www.youtube.com/channel/{c['id']})"
        mark = "" if c.get("enabled", True) else " _(выключен)_"
        rows.append(f"| {link}{mark} | {pool.get(c['slug'], 0) or '—'} | {per_chan.get(c['slug'], 0) or '—'} |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    db = lib.load_talks_db()
    # доклады без рабочей ссылки остаются в базе, но в README не попадают
    talks = [t for t in db["talks"] if t.get("url") and not t.get("needs_link")]
    hidden = len(db["talks"]) - len(talks)
    cats = lib.categories()
    speakers = {lib.norm(s) for t in talks for s in (t.get("speakers") or []) if s}
    now = datetime.date.today()

    text = open(lib.TEMPLATE, encoding="utf-8").read()
    for key, value in {
        "TALKS_COUNT": str(len(talks)),
        "SPEAKERS_COUNT": str(len(speakers)),
        "UPDATED": f"{lib.MONTHS_RU_NOM[now.month - 1]} {now.year}",
        "TALKS": render_talks(talks, cats),
        "YEARS": render_years(talks),
        "CHANNELS": render_channels(talks),
    }.items():
        text = text.replace("{{" + key + "}}", value)

    if args.check:
        current = open(lib.README, encoding="utf-8").read()
        if current.strip() != text.strip():
            sys.exit("README.md устарел: запустите python3 scripts/build_readme.py")
        print("README.md актуален")
        return
    open(lib.README, "w", encoding="utf-8").write(text)
    print(f"README.md собран: {len(talks)} докладов, {len(speakers)} спикеров"
          + (f"; скрыто без ссылки: {hidden}" if hidden else ""))


if __name__ == "__main__":
    main()
