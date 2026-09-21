# Как устроен репозиторий

README.md — **генерируемый файл**. Правки в нём затираются при следующей сборке.
Источник правды — данные в `data/` и конфиги в `sources/`.

## Пайплайн

```
sources/channels.json
        │  scripts/fetch.py        yt-dlp, плоский список видео канала
        ▼
data/candidates/<канал>.jsonl      пул всех найденных видео + статус
        │  scripts/classify.py     эвристика: iOS это или нет, спикер, категория
        │  scripts/enrich.py       описания и даты — только для отобранных
        │  scripts/review.py       выгрузка инбокса в data/review.md
        │  scripts/promote.py      решение человека: забрать / отклонить
        ▼
data/talks/<год>.json              курируемая база докладов
        │  scripts/build_readme.py + templates/README.md.tmpl
        ▼
README.md
```

Ничего, кроме `yt-dlp` и Python 3.9+, не нужно: API-ключ YouTube не требуется.

```bash
brew install yt-dlp     # или pipx install yt-dlp
make update             # fetch + classify + enrich + review
```

## Статусы кандидата

| Статус | Что значит |
| :-- | :-- |
| `new` | только что найдено, ещё не классифицировано |
| `candidate` | эвристика считает, что это iOS-доклад — ждёт ревью |
| `maybe` | по названию не понять, нужно описание (`enrich.py`), потом пересудим |
| `rejected` | отсеяно автоматически, причина в `reject_reason` |
| `approved` | подтверждено вручную, лежит в `data/talks/<год>.json` |
| `ignored` | отклонено вручную навсегда, больше не всплывёт |

Статусы `approved` и `ignored` классификатор не трогает — ручные решения не теряются.

## Добавить доклад руками

```bash
python3 scripts/promote.py dQw4w9WgXcQ --category swift --speaker "Иван Петров" --year 2024
python3 scripts/build_readme.py
```

Если видео нет в пуле кандидатов (например, канал не отслеживается) — допишите запись
в массив `data/talks/<год>.json` руками (порядок внутри файла неважен — при следующей сборке он нормализуется), формат такой:

```json
{
  "video_id": "dQw4w9WgXcQ",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Название доклада",
  "speakers": ["Иван Петров"],
  "year": 2024,
  "categories": ["swift"],
  "curated": true
}
```

## Добавить канал

Допишите объект в `sources/channels.json`. Нужен канонический `id` вида `UC...`
(`@handle` со временем меняются, id — нет). Найти id можно так:

```bash
python3 scripts/discover_channels.py "название канала"
```

`focus` управляет строгостью фильтра: `ios` — доверяем каналу целиком,
`mobile` — конференция по мобильной разработке, нужен iOS-сигнал,
`general` — общий IT-канал, берём только явные iOS-доклады.

## Добавить категорию

`sources/categories.json`. Порядок массива = порядок разделов в README.
`keywords` используются автоклассификатором (регистронезависимо, ё→е),
`aliases` — чтобы старые заголовки README продолжали сопоставляться.

## Что проверяется в CI

`python3 scripts/build_readme.py --check` — README собран из текущей базы.
