"""Scraper za halooglasi.com - detail stranice i search rezultati."""
import json
import random
import re
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from app.config import (
    USER_AGENTS,
    REQUEST_TIMEOUT,
    MIN_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    USE_PLAYWRIGHT_FALLBACK,
)


@dataclass
class ListingData:
    title: str | None
    price: float | None
    currency: str | None
    area_m2: float | None
    price_per_m2: float | None


@dataclass
class SearchResultItem:
    url: str
    title: str | None
    price: float | None


def polite_delay():
    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))


def _build_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sr-RS,sr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _fetch_with_requests(url: str) -> tuple[str | None, str]:
    """Vraca (html, status_message)."""
    try:
        resp = requests.get(url, headers=_build_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text, f"requests ok ({len(resp.text)} bytes)"
        return None, f"requests HTTP {resp.status_code}"
    except requests.RequestException as e:
        return None, f"requests exception: {type(e).__name__}: {e}"


def _fetch_with_playwright(url: str) -> tuple[str | None, str]:
    """Vraca (html, status_message). Sporiji ali stabilniji fallback."""
    if not USE_PLAYWRIGHT_FALLBACK:
        return None, "playwright disabled"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright not installed"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="sr-RS",
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else None
            html = page.content()
            browser.close()
            if status and status != 200:
                return None, f"playwright HTTP {status}"
            return html, f"playwright ok ({len(html)} bytes)"
    except Exception as e:
        return None, f"playwright exception: {type(e).__name__}: {e}"


def fetch_page(url: str) -> str | None:
    """Pokusava requests, ako pukne fallback na Playwright. Loguje status."""
    html, msg = _fetch_with_requests(url)
    if html and len(html) > 1000:
        print(f"     [fetch] {msg}")
        return html
    print(f"     [fetch] {msg} -> playwright fallback")
    html, msg = _fetch_with_playwright(url)
    print(f"     [fetch] {msg}")
    return html


# ---------- Detail page parsing ----------

_PRICE_NUM_RE = re.compile(r"[\d.,]+")


def _parse_number(text: str) -> float | None:
    """Parsira broj iz teksta. Podrzava EU format (1.250,50) i US format (1,250.50).
    Halo oglasi standardno koristi EU format (tacka = hiljadnik, zarez = decimala)."""
    if not text:
        return None
    match = _PRICE_NUM_RE.search(text)
    if not match:
        return None
    raw = match.group(0)

    has_comma = "," in raw
    has_dot = "." in raw

    if has_comma and has_dot:
        # Onaj separator koji se pojavljuje POSLEDNJI je decimalni
        if raw.rfind(",") > raw.rfind("."):
            # EU format: 1.250,50
            raw = raw.replace(".", "").replace(",", ".")
        else:
            # US format: 1,250.50
            raw = raw.replace(",", "")
    elif has_comma:
        # Samo zarez. EU: 1250,50 (decimala) ili 1,250 (US hiljadnik).
        # Heuristika: ako je deo posle zareza tacno 3 cifre, tretiraj kao hiljadnik
        parts = raw.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    elif has_dot:
        # Samo tacka. Moze biti: 95.50 (decimala), 118.000 (hiljadnik), 1.500.000 (vise hiljadnika).
        parts = raw.split(".")
        if len(parts) >= 3:
            # Vise tacaka => sve su hiljadnici (1.500.000)
            raw = raw.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3:
            # 118.000 -> hiljadnik
            raw = raw.replace(".", "")
        # inace ostavi: 95.50 -> 95.5

    try:
        return float(raw)
    except ValueError:
        return None


def _extract_quiddita_data(html: str) -> dict | None:
    """Halo oglasi inline-uje QuidditaEnvironment.CurrentClassified sa kompletnim JSON-om oglasa."""
    match = re.search(
        r"QuidditaEnvironment\.CurrentClassified\s*=\s*(\{.*?\});",
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    """JSON-LD blokovi kao backup izvor podataka."""
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def parse_listing(html: str) -> ListingData:
    """Izvlaci strukturirane podatke iz Halo oglasi detail stranice."""
    soup = BeautifulSoup(html, "lxml")

    title = None
    price = None
    currency = None
    area_m2 = None
    price_per_m2 = None

    # 1. Pokusaj QuidditaEnvironment - najpouzdaniji izvor
    quiddita = _extract_quiddita_data(html)
    quiddita_keys = list(quiddita.keys())[:10] if quiddita else None
    if quiddita:
        title = quiddita.get("Title") or quiddita.get("TextHtml")
        price_raw = quiddita.get("Price") or quiddita.get("ListingPriceValue")
        if price_raw is not None:
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                price = _parse_number(str(price_raw))
        currency = quiddita.get("CurrencyName") or "EUR"

        area_raw = (
            quiddita.get("Kvadratura") or
            quiddita.get("kvadratura") or
            quiddita.get("LivingArea")
        )
        if area_raw is not None:
            try:
                area_m2 = float(area_raw)
            except (TypeError, ValueError):
                area_m2 = _parse_number(str(area_raw))

    # 2. Backup: JSON-LD
    if price is None:
        for item in _extract_jsonld(soup):
            offers = item.get("offers") if isinstance(item, dict) else None
            if offers and isinstance(offers, dict):
                p = offers.get("price")
                if p:
                    price = _parse_number(str(p))
                    currency = offers.get("priceCurrency") or currency
            if not title and isinstance(item, dict):
                title = item.get("name") or title

    # 3. Backup: HTML meta tagovi
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content")

    if price is None:
        # Poslednji pokusaj: trazi .property-price ili sl. klase
        price_el = soup.select_one(".price-value, .property-price, [data-field-name='cena']")
        if price_el:
            price = _parse_number(price_el.get_text())

    if price is not None and area_m2 and area_m2 > 0:
        price_per_m2 = round(price / area_m2, 2)

    # Debug: ako nema cene, ispisi sta je nadjeno
    if price is None:
        print(f"     [parse] no price found. quiddita keys: {quiddita_keys}, title: {title!r}, html_len: {len(html)}")

    return ListingData(
        title=title.strip() if title else None,
        price=price,
        currency=currency,
        area_m2=area_m2,
        price_per_m2=price_per_m2,
    )


# ---------- Search results parsing ----------

def parse_search_results(html: str, base_url: str = "https://www.halooglasi.com") -> list[SearchResultItem]:
    """Izvlaci listu oglasa iz search rezultata.

    Halo oglasi koristi <div class='product-item'> ili sl. wrapper. Selektori se ponekad menjaju
    pa idemo defanzivno: trazimo svaki link koji vodi na detail stranicu nekretnine.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[SearchResultItem] = []
    seen_urls: set[str] = set()

    # Linkovi ka detail stranicama imaju /nekretnine/.../ID/ ili /5425... slug pattern
    listing_link_re = re.compile(r"/nekretnine/[^/]+/[^/]+/")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not listing_link_re.search(href):
            continue
        if href.startswith("/"):
            href = base_url + href
        # Filtriraj samo detail stranice (imaju numericki ID na kraju)
        if not re.search(r"/\d{6,}/?$", href.split("?")[0]):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Pokusaj da nadjes naslov i cenu u nadleznom kontejneru
        container = a.find_parent(["article", "div", "li"]) or a
        title = a.get("title") or a.get_text(strip=True)[:200] or None

        price = None
        price_el = container.find(class_=re.compile(r"price", re.IGNORECASE))
        if price_el:
            price = _parse_number(price_el.get_text())

        items.append(SearchResultItem(url=href, title=title, price=price))

    return items


# ---------- Public API ----------

def scrape_listing(url: str) -> ListingData | None:
    """High-level: fetch + parse detail stranice. Vraca None ako stranica nije dostupna."""
    html = fetch_page(url)
    if not html:
        return None
    return parse_listing(html)


def scrape_search(url: str) -> list[SearchResultItem]:
    """High-level: fetch + parse search rezultata."""
    html = fetch_page(url)
    if not html:
        return []
    return parse_search_results(html)
