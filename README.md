# ذرى THURA

An Arabic finance and news site. A fixed desert-canyon background moves as you scroll, a market strip sits under the hero, and the news comes from several channels. A small Python script refreshes the headlines every day and keeps them in a SQLite database.

```
thura/
├── index.html              the whole site (HTML, CSS, JS in one file)
├── sources.json            which feeds to read, per channel
├── schema.sql              database schema
├── scripts/update.py       daily updater (Python standard library only)
├── data/
│   ├── thura.db            SQLite database (sources, articles, fetch_log)
│   ├── news.js             newest headlines, loaded by index.html
│   ├── news.json           same data as plain JSON
│   └── seed.json           first snapshot (6 Oct 2026), used to fill the database
├── tests/                  fixture feeds and a test config for the updater
└── .github/workflows/daily.yml   runs the updater every day on GitHub
```

## See the site

Open `index.html` in a browser. It works from a plain file because the headlines load from `data/news.js`, not from a network request.

To serve it locally instead:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Update the news by hand

Python 3.9 or newer. Nothing to install.

```bash
python3 scripts/update.py
```

The script reads each feed in `sources.json`, adds new headlines to `data/thura.db`, then rewrites `data/news.js` and `data/news.json` with the newest items from the last 7 days. A feed that fails is logged and skipped, so one broken source never stops the rest. The script exits with an error only when every feed fails.

Options:

| Flag | What it does |
|------|--------------|
| `--offline` | Do not fetch. Only rebuild `news.js` from the database. |
| `--seed data/seed.json` | Load articles from a JSON file first. |
| `--no-translate` | Never call the translation API. |
| `--sources PATH`, `--db PATH`, `--out DIR` | Use other files or folders. |

## Update every day

### Option A: GitHub Actions (free, no server)

1. Create a GitHub repository and push this folder to it.
2. Open **Settings → Pages** and publish from the `main` branch, root folder. The site goes live at `https://<you>.github.io/<repo>/`.
3. The workflow in `.github/workflows/daily.yml` runs at 03:00 UTC every day. It runs the updater and commits the new `data/` files, and Pages republishes the site. You can also run it from the **Actions** tab with **Run workflow**.

### Option B: your own computer or server (cron)

```bash
crontab -e
```

```
0 6 * * * cd /path/to/thura && /usr/bin/python3 scripts/update.py >> data/update.log 2>&1
```

Then serve the folder with any web server (nginx, Caddy, GitHub Pages, Netlify).

## Channels

| Tab | Source | Feed |
|-----|--------|------|
| العربية السعودية | Al Arabiya, Saudi section only | main feed, filtered to `/saudi-today/` |
| (right-hand list) | Al Arabiya markets | main feed, filtered to `/aswaq/` |
| الجزيرة | Al Jazeera | RSS |
| سكاي نيوز عربية | Sky News Arabia | RSS |
| الشرق مع بلومبرغ | Asharq Bloomberg | RSS |
| Bloomberg | Bloomberg markets | RSS |
| CNBC | CNBC top news | RSS |
| MarketWatch | MarketWatch top stories | RSS |
| CNN | CNN business | RSS |
| نيويورك تايمز | New York Times business | RSS |

Add, remove or reorder channels in `sources.json` (`enabled`, `limit`, `feed_urls`, `url_contains`). A new channel also needs a button in the `#ctabs` block of `index.html` and an entry in the `chan` object in the script.

### Things to know

These are the limits I ran into while building this. Check them on your own machine, since I could only test the updater against local sample feeds, not the live sites.

- **New York Times and CNN.** I could not read the New York Times feed from my environment, so the first snapshot has only two section links for it. CNN's public RSS has been frozen since 2023, so after the first snapshot ages out (7 days) the CNN tab will show no recent headlines. For live CNN and New York Times headlines use their news APIs or a paid aggregator (for example NewsAPI or GDELT), and add a small function in `update.py` that inserts rows with `insert_article`.
- **Al Arabiya section feeds.** The main Al Arabiya feed has only a handful of items at a time. The second URL for each Al Arabiya source (`saudi-today.xml`, `aswaq.xml`) is my guess at a section feed. If it does not respond, copy the right addresses from https://www.alarabiya.net/rss into `sources.json`.
- **Bloomberg and CNBC feed addresses.** Bloomberg's feed returned an error and CNBC's was blocked for me. Both addresses are the commonly published ones. If either fails, the log shows why: `sqlite3 data/thura.db "select * from fetch_log order by id desc limit 20"`.
- **English headlines.** Bloomberg, CNBC, MarketWatch, CNN and the New York Times publish in English. The first snapshot contains Arabic summaries of them. For new headlines, set the environment variable `ANTHROPIC_API_KEY` and the updater translates them to Arabic (model set by `THURA_MODEL`, default `claude-haiku-4-5-20251001`). I could not test this step without a key. Without a key, English headlines are shown in English, left to right.
- **Market numbers are examples.** The ticker, sparklines and the indices table use made-up figures. To show real prices, add a quotes provider to `update.py` and write the values into `news.js`, then read them in `index.html` where `tickers` and `idx` are defined.
- **Copyright.** The site shows headlines, a source name and a link to the original article. It does not copy article text. Keep it that way, and check each publisher's terms before using their feeds on a public site.

## Database

SQLite file `data/thura.db`. Open it with `sqlite3 data/thura.db` or any SQLite viewer.

| Table | Purpose |
|-------|---------|
| `sources` | one row per channel (`key`, `name`, `lang`, `enabled`) |
| `articles` | headlines (`title`, `title_ar`, `url` unique, `category`, `published_at`, `fetched_at`) |
| `fetch_log` | one row per feed per run (`ok`, `new_items`, `error`) |

Useful queries:

```sql
-- newest 10 headlines overall
SELECT s.name, a.title, a.published_at
FROM articles a JOIN sources s ON s.id = a.source_id
ORDER BY a.published_at DESC LIMIT 10;

-- which feeds failed in the last run
SELECT s.key, f.feed_url, f.error
FROM fetch_log f JOIN sources s ON s.id = f.source_id
WHERE f.ok = 0 ORDER BY f.id DESC LIMIT 20;
```

The updater only ingests items from the last `keep_days` (30), and the site shows items from the last `max_age_days` (7). Both are set at the top of `sources.json`. Old rows stay in the database until you delete them.

## Test

```bash
python3 scripts/update.py --sources tests/sources.test.json --db /tmp/test.db --out /tmp/test-out --no-translate
```

This reads the sample feeds in `tests/fixtures/`, including one old item that must be skipped and one feed address that must fail without stopping the run.

## Design notes

The landscape is drawn in code on a fixed canvas: four ridge layers, a sun and drifting mist. Scrolling moves each layer by a different amount, so the near ridges travel more than the far ones, and the sky darkens so cards stay readable. With "reduce motion" turned on in the system, the drifting stops. Fonts load from Google Fonts: Aref Ruqaa for the wordmark, IBM Plex Sans Arabic for text, Cinzel for "THURA".
