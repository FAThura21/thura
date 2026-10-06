#!/usr/bin/env python3
"""Thura daily updater.

Fetches the RSS/Atom feeds listed in sources.json, stores new headlines in a
SQLite database (data/thura.db) and exports the newest ones to data/news.js
(and data/news.json) for the website.

Standard library only. Python 3.9+.

    python scripts/update.py                  # fetch, store, export
    python scripts/update.py --offline        # skip the network, just re-export
    python scripts/update.py --seed data/seed.json --offline
    python scripts/update.py --no-translate   # never call the translation API
"""
import argparse
import html
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (compatible; ThuraBot/1.0; +https://example.com/thura)"
DROP_PARAMS = {"traffic_source", "mod", "cmpid", "taid", "ocid"}


def now_utc():
    return datetime.now(timezone.utc)


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def clean_text(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def clean_url(u):
    u = (u or "").strip()
    try:
        p = urllib.parse.urlsplit(u)
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if k not in DROP_PARAMS and not k.startswith("utm_")]
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))
    except Exception:
        return u


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(data):
    """Return a list of dicts: title, url, category, published (datetime)."""
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {"title": "", "url": "", "category": "", "date": None}
        for c in el:
            k = local(c.tag)
            if k == "title":
                f["title"] = clean_text(c.text)
            elif k == "link":
                href = c.get("href") or (c.text or "").strip()
                if href and (not f["url"] or c.get("rel") == "alternate"):
                    f["url"] = href
            elif k in ("pubDate", "published", "updated", "date"):
                d = parse_date(c.text)
                if d and not f["date"]:
                    f["date"] = d
            elif k == "category" and not f["category"]:
                f["category"] = clean_text(c.text or c.get("term"))
        if f["title"] and f["url"]:
            out.append(f)
    return out


def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    with open(os.path.join(ROOT, "schema.sql"), encoding="utf-8") as fh:
        conn.executescript(fh.read())
    return conn


def sync_sources(conn, cfg):
    ids = {}
    for s in cfg["sources"]:
        conn.execute(
            "INSERT INTO sources(key,name,lang,enabled) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET name=excluded.name, lang=excluded.lang, enabled=excluded.enabled",
            (s["key"], s["name"], s.get("lang", "ar"), 1 if s.get("enabled", True) else 0))
        ids[s["key"]] = conn.execute("SELECT id FROM sources WHERE key=?", (s["key"],)).fetchone()[0]
    conn.commit()
    return ids


def insert_article(conn, source_id, title, url, category, published, title_ar=None):
    cur = conn.execute(
        "INSERT OR IGNORE INTO articles(source_id,title,title_ar,url,category,published_at,fetched_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (source_id, title, title_ar, url, category or "", iso(published), iso(now_utc())))
    return cur.rowcount


def ingest(conn, cfg, ids):
    keep_cut = now_utc() - timedelta(days=cfg.get("keep_days", 30))
    ok_feeds = 0
    tried = 0
    for s in cfg["sources"]:
        if not s.get("enabled", True):
            continue
        sid = ids[s["key"]]
        for url in s["feed_urls"]:
            tried += 1
            added, err = 0, None
            try:
                items = parse_feed(fetch(url))
                need = s.get("url_contains")
                for it in items:
                    if need and need not in it["url"]:
                        continue
                    pub = it["date"] or now_utc()
                    if pub < keep_cut:
                        continue
                    added += insert_article(conn, sid, it["title"], clean_url(it["url"]), it["category"], pub)
                ok_feeds += 1
            except Exception as e:  # network, HTTP, XML: log and carry on
                err = f"{type(e).__name__}: {e}"[:300]
            conn.execute(
                "INSERT INTO fetch_log(source_id,feed_url,ran_at,ok,new_items,error) VALUES(?,?,?,?,?,?)",
                (sid, url, iso(now_utc()), 0 if err else 1, added, err))
            conn.commit()
            print(f"  {'FAIL' if err else 'ok  '} {s['key']:<11} +{added:<3} {url}" + (f"\n       {err}" if err else ""))
    return ok_feeds, tried


def seed(conn, ids, path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    n = 0
    for key, items in data["sources"].items():
        if key not in ids:
            continue
        for it in items:
            pub = parse_date(it["published_at"]) or now_utc()
            n += insert_article(conn, ids[key], it["title"], it["url"], it.get("category", ""), pub, it.get("title_ar"))
    conn.commit()
    print(f"  seeded {n} articles from {path}")


def translate(conn):
    """Optional: translate English headlines to Arabic with the Anthropic API."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return
    rows = conn.execute(
        "SELECT a.id, a.title FROM articles a JOIN sources s ON s.id=a.source_id "
        "WHERE a.title_ar IS NULL AND s.lang='en' ORDER BY a.published_at DESC LIMIT 60").fetchall()
    if not rows:
        return
    prompt = ("Translate these news headlines into clear Modern Standard Arabic. "
              "Keep names and numbers accurate. Reply with only a JSON array of strings, "
              "same order and same length as the input.\n" + json.dumps([r[1] for r in rows], ensure_ascii=False))
    body = json.dumps({
        "model": os.environ.get("THURA_MODEL", "claude-haiku-4-5-20251001"),
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            text = json.loads(r.read())["content"][0]["text"]
        arr = json.loads(text[text.index("["): text.rindex("]") + 1])
        if len(arr) != len(rows):
            raise ValueError("translation count mismatch")
        for (rid, _), ar in zip(rows, arr):
            conn.execute("UPDATE articles SET title_ar=? WHERE id=?", (str(ar).strip(), rid))
        conn.commit()
        print(f"  translated {len(rows)} headlines")
    except Exception as e:
        print(f"  translation skipped: {type(e).__name__}: {e}")


def export(conn, cfg, out_dir):
    cut = iso(now_utc() - timedelta(days=cfg.get("max_age_days", 7)))
    channels = {}
    for s in cfg["sources"]:
        if not s.get("enabled", True):
            continue
        rows = conn.execute(
            "SELECT a.title, a.title_ar, a.url, a.category, a.published_at FROM articles a "
            "JOIN sources so ON so.id=a.source_id WHERE so.key=? AND a.published_at>=? "
            "ORDER BY a.published_at DESC LIMIT ?", (s["key"], cut, s.get("limit", 8))).fetchall()
        channels[s["key"]] = {
            "name": s["name"],
            "items": [{
                "h": ar or title, "u": url, "k": cat or "", "t": pub,
                "lang": "ar" if (ar or s.get("lang") == "ar") else "en",
            } for title, ar, url, cat, pub in rows],
        }
    payload = {"updated": iso(now_utc()), "channels": channels}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "news.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "news.js"), "w", encoding="utf-8") as fh:
        fh.write("window.THURA_NEWS = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    total = sum(len(c["items"]) for c in channels.values())
    print(f"  exported {total} headlines from {len(channels)} channels to {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "thura.db"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    ap.add_argument("--seed", help="load articles from a JSON file before exporting")
    ap.add_argument("--offline", action="store_true", help="do not fetch feeds")
    ap.add_argument("--no-translate", action="store_true")
    a = ap.parse_args()

    with open(a.sources, encoding="utf-8") as fh:
        cfg = json.load(fh)
    conn = connect(a.db)
    ids = sync_sources(conn, cfg)
    print(f"Thura update {iso(now_utc())}")
    status = 0
    if a.seed:
        seed(conn, ids, a.seed)
    if not a.offline:
        ok, tried = ingest(conn, cfg, ids)
        if tried and ok == 0:
            print("All feeds failed. Check the network and sources.json.")
            status = 1
    if not a.offline and not a.no_translate:
        translate(conn)
    export(conn, cfg, a.out)
    conn.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
