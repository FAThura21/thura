-- Thura news database (SQLite 3)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  key       TEXT NOT NULL UNIQUE,        -- short id used by the site: ar, aj, bb ...
  name      TEXT NOT NULL,               -- display name
  lang      TEXT NOT NULL DEFAULT 'ar',  -- language of the original headline
  enabled   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  title        TEXT NOT NULL,            -- headline as published
  title_ar     TEXT,                     -- Arabic translation (English sources, optional)
  url          TEXT NOT NULL UNIQUE,
  category     TEXT,
  published_at TEXT NOT NULL,            -- ISO 8601, UTC
  fetched_at   TEXT NOT NULL             -- ISO 8601, UTC
);
CREATE INDEX IF NOT EXISTS idx_articles_source_pub ON articles(source_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at DESC);

CREATE TABLE IF NOT EXISTS fetch_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  feed_url   TEXT NOT NULL,
  ran_at     TEXT NOT NULL,
  ok         INTEGER NOT NULL,           -- 1 success, 0 failure
  new_items  INTEGER NOT NULL DEFAULT 0,
  error      TEXT
);
