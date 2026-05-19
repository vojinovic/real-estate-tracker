"""On-demand pretraga koju frontend triggeruje preko GitHub API-ja.

Prima URL kao argument, scrape-uje, snima rezultate u data/last_ondemand_search.json.
"""
import json
import sys
from pathlib import Path

from app.scrapers.halooglasi import scrape_search

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT = BASE_DIR / "data" / "last_ondemand_search.json"


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.ondemand_search <url>")
        sys.exit(1)

    url = sys.argv[1].strip()
    label = sys.argv[2].strip() if len(sys.argv) > 2 else url

    print(f"[ondemand] Scraping: {url}")
    results = scrape_search(url)
    print(f"[ondemand] {len(results)} rezultata")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "label": label,
        "results": [
            {"url": r.url, "title": r.title, "price": r.price}
            for r in results
        ],
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[ondemand] Snimio {OUTPUT}")


if __name__ == "__main__":
    main()
