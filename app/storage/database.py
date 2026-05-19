"""SQLite storage za listings, price history, i searches."""
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from app.config import DB_PATH, DATA_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    location TEXT,
    property_type TEXT,
    note TEXT,
    current_price REAL,
    first_seen_price REAL,
    area_m2 REAL,
    price_per_m2 REAL,
    status TEXT DEFAULT 'active',
    consecutive_errors INTEGER DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_checked_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    price REAL NOT NULL,
    checked_at TEXT NOT NULL,
    change_amount REAL,
    change_percent REAL,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    note TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS seen_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    listing_url TEXT NOT NULL,
    title TEXT,
    price REAL,
    first_seen_at TEXT NOT NULL,
    UNIQUE(search_id, listing_url),
    FOREIGN KEY (search_id) REFERENCES searches(id)
);

CREATE TABLE IF NOT EXISTS prefetched_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    listing_url TEXT NOT NULL,
    title TEXT,
    price REAL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(search_id, listing_url),
    FOREIGN KEY (search_id) REFERENCES searches(id)
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_seen_search ON seen_listings(search_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_prefetched_search ON prefetched_listings(search_id);
"""


@contextmanager
def get_conn():
    """Context manager za SQLite konekciju."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Inicijalizuje šemu. Sigurno za pozivanje pri svakom startu."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


# ---------- Listings ----------

def get_active_listings():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM listings WHERE status != 'archived' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_listing_by_url(url: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM listings WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None


def upsert_listing_from_csv(source: str, url: str, property_type: str, location: str, note: str):
    """Dodaje novi oglas iz listings.csv ako ne postoji. Ne dira postojeće cene."""
    existing = get_listing_by_url(url)
    if existing:
        # Update samo metapodatke koji mogu da se menjaju u CSV-u
        with get_conn() as conn:
            conn.execute(
                """UPDATE listings SET property_type = ?, location = ?, note = ?, updated_at = ?
                   WHERE url = ?""",
                (property_type, location, note, now_iso(), url),
            )
        return existing["id"]

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO listings (source, url, property_type, location, note,
                                     status, first_seen_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (source, url, property_type, location, note, now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_listing_after_scrape(
    listing_id: int,
    title: str,
    price: float,
    area_m2: float | None,
    price_per_m2: float | None,
):
    """Update polja iz scrape-a. Postavlja first_seen_price ako još ne postoji."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT first_seen_price FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        first_seen = existing["first_seen_price"] if existing and existing["first_seen_price"] else price

        conn.execute(
            """UPDATE listings
               SET title = COALESCE(?, title),
                   current_price = ?,
                   first_seen_price = ?,
                   area_m2 = COALESCE(?, area_m2),
                   price_per_m2 = COALESCE(?, price_per_m2),
                   status = 'active',
                   consecutive_errors = 0,
                   last_checked_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (title, price, first_seen, area_m2, price_per_m2, now_iso(), now_iso(), listing_id),
        )


def record_scrape_error(listing_id: int, threshold: int) -> bool:
    """Inkrementira error brojač. Vraća True ako je listing sada markiran kao unavailable."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT consecutive_errors, status FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        new_count = (row["consecutive_errors"] or 0) + 1
        new_status = "unavailable" if new_count >= threshold else row["status"]
        became_unavailable = new_status == "unavailable" and row["status"] != "unavailable"

        conn.execute(
            """UPDATE listings
               SET consecutive_errors = ?, status = ?, last_checked_at = ?, updated_at = ?
               WHERE id = ?""",
            (new_count, new_status, now_iso(), now_iso(), listing_id),
        )
        return became_unavailable


def add_price_history(listing_id: int, price: float, prev_price: float | None):
    change_amount = None
    change_percent = None
    if prev_price and prev_price > 0:
        change_amount = price - prev_price
        change_percent = (change_amount / prev_price) * 100

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO price_history (listing_id, price, checked_at, change_amount, change_percent)
               VALUES (?, ?, ?, ?, ?)""",
            (listing_id, price, now_iso(), change_amount, change_percent),
        )


# ---------- Searches ----------

def get_active_searches():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM searches WHERE is_active = 1").fetchall()
        return [dict(r) for r in rows]


def upsert_search(source: str, name: str, url: str, note: str):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM searches WHERE url = ?", (url,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE searches SET name = ?, note = ?, is_active = 1 WHERE url = ?",
                (name, note, url),
            )
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO searches (source, name, url, note, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (source, name, url, note, now_iso()),
        )
        return cur.lastrowid


def get_seen_urls_for_search(search_id: int) -> set[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT listing_url FROM seen_listings WHERE search_id = ?", (search_id,)
        ).fetchall()
        return {r["listing_url"] for r in rows}


def add_seen_listing(search_id: int, url: str, title: str, price: float | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO seen_listings (search_id, listing_url, title, price, first_seen_at)
               VALUES (?, ?, ?, ?, ?)""",
            (search_id, url, title, price, now_iso()),
        )


def mark_search_checked(search_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE searches SET last_checked_at = ? WHERE id = ?",
            (now_iso(), search_id),
        )


# ---------- Prefetched listings (snapshot of latest search results) ----------

def replace_prefetched_for_search(search_id: int, items: list[dict]):
    """Brise stare prefetched rezultate za pretragu i upisuje nove.
    items: list of dicts with keys: url, title, price"""
    with get_conn() as conn:
        conn.execute("DELETE FROM prefetched_listings WHERE search_id = ?", (search_id,))
        for item in items:
            conn.execute(
                """INSERT OR IGNORE INTO prefetched_listings
                   (search_id, listing_url, title, price, last_seen_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (search_id, item["url"], item.get("title"), item.get("price"), now_iso()),
            )


def get_prefetched_for_search(search_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM prefetched_listings WHERE search_id = ? ORDER BY id",
            (search_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- Price history & dashboard export ----------

def get_price_history(listing_id: int, limit: int = 60) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT price, checked_at, change_amount, change_percent
               FROM price_history WHERE listing_id = ?
               ORDER BY checked_at ASC LIMIT ?""",
            (listing_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def export_dashboard_json() -> dict:
    """Eksport za frontend - sve listings sa price history-jem + searches + prefetched."""
    listings_out = []
    for listing in get_active_listings():
        history = get_price_history(listing["id"])
        listings_out.append({**listing, "history": history})

    searches_out = []
    for search in get_active_searches():
        searches_out.append({**search, "prefetched": get_prefetched_for_search(search["id"])})

    return {
        "generated_at": now_iso(),
        "listings": listings_out,
        "searches": searches_out,
    }
