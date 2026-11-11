"""Citation history, stored next to the existing SqliteDict table in data/db.sqlite.

The SqliteDict table ("unnamed") keeps the latest state per publication and is
left untouched for compatibility. The tables below keep everything fetched on
every run, so trends are built from our own observations over time.
"""
import datetime as dt
import json
import sqlite3
from collections import defaultdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_at      TEXT PRIMARY KEY,   -- ISO timestamp of the fetch
    date        TEXT NOT NULL,
    citedby     INTEGER,
    citedby5y   INTEGER,
    hindex      INTEGER,
    hindex5y    INTEGER,
    i10index    INTEGER,
    i10index5y  INTEGER,
    n_pubs      INTEGER,
    author_json TEXT                -- full author record minus the publication list
);
CREATE TABLE IF NOT EXISTS pub_snapshots (
    date      TEXT    NOT NULL,     -- one row per paper per day (latest run wins)
    pub_id    TEXT    NOT NULL,
    citations INTEGER NOT NULL,
    PRIMARY KEY (date, pub_id)
);
CREATE TABLE IF NOT EXISTS publications (
    pub_id     TEXT PRIMARY KEY,
    title      TEXT,
    year       INTEGER,
    citation   TEXT,                -- venue string as shown on the profile
    first_seen TEXT,
    last_seen  TEXT,
    bib_json   TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

AUTHOR_FIELDS = ("citedby", "citedby5y", "hindex", "hindex5y", "i10index", "i10index5y")


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


class History:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- writes -----------------------------------------------------------

    def record_run(self, run_at, author, pubs):
        """Save everything fetched in one run. pubs: {pub_id: publication dict from scholarly}."""
        date = run_at.date().isoformat()
        author_info = {k: v for k, v in dict(author).items() if k != "publications"}
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_at.isoformat(timespec="seconds"), date,
                 *(author.get(f) for f in AUTHOR_FIELDS), len(pubs),
                 json.dumps(_jsonable(author_info))),
            )
            for pid, p in pubs.items():
                bib = p.get("bib", {})
                self.conn.execute(
                    "INSERT OR REPLACE INTO pub_snapshots VALUES (?, ?, ?)",
                    (date, pid, int(p.get("num_citations", 0))))
                self.conn.execute(
                    """INSERT INTO publications VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(pub_id) DO UPDATE SET title=excluded.title, year=excluded.year,
                         citation=excluded.citation, last_seen=excluded.last_seen,
                         bib_json=excluded.bib_json""",
                    (pid, bib.get("title"), _year(bib.get("pub_year")), bib.get("citation"),
                     date, date, json.dumps(_jsonable(bib))))

    def record_pubs(self, date, citations_by_pub, overwrite=True):
        """Store bare citation counts for one date (used by backfill)."""
        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        with self.conn:
            self.conn.executemany(
                f"{verb} INTO pub_snapshots (date, pub_id, citations) VALUES (?, ?, ?)",
                [(date.isoformat(), pid, int(c)) for pid, c in citations_by_pub.items()],
            )

    def set_meta(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    # --- reads ------------------------------------------------------------

    def get_meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def pub_series(self):
        """{pub_id: [(date, citations), ...]} sorted by date."""
        series = defaultdict(list)
        for d, pid, c in self.conn.execute(
                "SELECT date, pub_id, citations FROM pub_snapshots ORDER BY date"):
            series[pid].append((dt.date.fromisoformat(d), c))
        return dict(series)

    def author_series(self):
        """[(date, citedby)] using the latest run of each day."""
        rows = self.conn.execute(
            """SELECT date, citedby FROM runs r
               WHERE run_at = (SELECT MAX(run_at) FROM runs WHERE date = r.date)
                 AND citedby IS NOT NULL
               ORDER BY date""").fetchall()
        return [(dt.date.fromisoformat(d), c) for d, c in rows]


def _year(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
