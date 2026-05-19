"""Glavni tracker. Pokrece se iz GitHub Actions.

Logika:
1. Inicijalizuje bazu
2. Sinhronizuje listings.csv i searches.csv u bazu
3. Za svaki aktivni oglas: scrape, uporedi cenu, alert ako treba
4. Za svaki aktivni search: scrape rezultate, alert za nove listinge
5. Eksportuje data/dashboard.json za frontend
"""
import csv
import json
import sys
from pathlib import Path

from app.config import ERROR_THRESHOLD_FOR_UNAVAILABLE
from app.storage import database as db
from app.scrapers.halooglasi import (
    scrape_listing,
    scrape_search,
    polite_delay,
)
from app.alerts.email_alert import (
    alert_price_drop,
    alert_listing_unavailable,
    alert_new_listings_in_search,
)


BASE_DIR = Path(__file__).resolve().parent.parent
LISTINGS_CSV = BASE_DIR / "listings.csv"
SEARCHES_CSV = BASE_DIR / "searches.csv"
DASHBOARD_JSON = BASE_DIR / "data" / "dashboard.json"


def detect_source(url: str) -> str:
    if "halooglasi.com" in url:
        return "halooglasi"
    return "unknown"


def sync_listings_csv():
    """Ucitava listings.csv i upsert-uje u bazu."""
    if not LISTINGS_CSV.exists():
        print(f"[sync] {LISTINGS_CSV} ne postoji, preskacem.")
        return
    with open(LISTINGS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url:
                continue
            db.upsert_listing_from_csv(
                source=detect_source(url),
                url=url,
                property_type=(row.get("type") or "").strip(),
                location=(row.get("city") or "").strip(),
                note=(row.get("note") or "").strip(),
            )
            count += 1
        print(f"[sync] listings.csv: {count} oglasa.")


def sync_searches_csv():
    """Ucitava searches.csv i upsert-uje u bazu."""
    if not SEARCHES_CSV.exists():
        print(f"[sync] {SEARCHES_CSV} ne postoji, preskacem.")
        return
    with open(SEARCHES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url:
                continue
            db.upsert_search(
                source=detect_source(url),
                name=(row.get("name") or "").strip(),
                url=url,
                note=(row.get("note") or "").strip(),
            )
            count += 1
        print(f"[sync] searches.csv: {count} pretraga.")


def check_listings():
    listings = db.get_active_listings()
    print(f"[listings] Proveravam {len(listings)} oglasa...")

    for listing in listings:
        url = listing["url"]
        prev_price = listing.get("current_price")
        print(f"  -> {listing.get('note') or url}")

        data = scrape_listing(url)

        if data is None or data.price is None:
            became_unavailable = db.record_scrape_error(
                listing["id"], ERROR_THRESHOLD_FOR_UNAVAILABLE
            )
            if became_unavailable:
                print(f"     ! Markiran kao unavailable posle {ERROR_THRESHOLD_FOR_UNAVAILABLE} gresaka")
                alert_listing_unavailable(listing)
            polite_delay()
            continue

        db.update_listing_after_scrape(
            listing_id=listing["id"],
            title=data.title,
            price=data.price,
            area_m2=data.area_m2,
            price_per_m2=data.price_per_m2,
        )
        db.add_price_history(listing["id"], data.price, prev_price)

        if prev_price and data.price < prev_price:
            print(f"     v Cena pala: {prev_price} -> {data.price}")
            # Osvezi listing dict pre slanja alerta da title bude tu
            updated = db.get_listing_by_url(url) or listing
            alert_price_drop(updated, data.price, prev_price)
        elif prev_price and data.price > prev_price:
            print(f"     ^ Cena porasla: {prev_price} -> {data.price} (nema alerta po konfiguraciji)")
        else:
            print(f"     = {data.price}")

        polite_delay()


def check_searches():
    searches = db.get_active_searches()
    print(f"[searches] Proveravam {len(searches)} pretraga...")

    for search in searches:
        print(f"  -> {search['name']}")
        results = scrape_search(search["url"])
        if not results:
            print(f"     ! Nema rezultata ili scrape pukao")
            db.mark_search_checked(search["id"])
            polite_delay()
            continue

        seen = db.get_seen_urls_for_search(search["id"])
        new_items = [r for r in results if r.url not in seen]

        for item in results:
            db.add_seen_listing(search["id"], item.url, item.title, item.price)
        db.mark_search_checked(search["id"])

        # Snimi snapshot trenutnih rezultata za dashboard
        db.replace_prefetched_for_search(
            search["id"],
            [{"url": r.url, "title": r.title, "price": r.price} for r in results],
        )

        if new_items and seen:
            # seen je prazan na prvoj proveri => preskaci alert (sve bi bilo "novo")
            print(f"     + {len(new_items)} novih oglasa")
            alert_new_listings_in_search(search, new_items)
        elif new_items and not seen:
            print(f"     i Prva provera: {len(new_items)} oglasa zabelezeno, bez alerta")
        else:
            print(f"     = nema novih")

        polite_delay()


def export_dashboard():
    """Snima JSON koji frontend cita."""
    DASHBOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    data = db.export_dashboard_json()
    with open(DASHBOARD_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[export] Snimio {DASHBOARD_JSON}")


def main():
    db.init_db()
    sync_listings_csv()
    sync_searches_csv()
    check_listings()
    check_searches()
    export_dashboard()
    print("[done]")


if __name__ == "__main__":
    sys.exit(main() or 0)
