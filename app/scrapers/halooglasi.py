"""Scraper za halooglasi.com - detail stranice i search rezultati."""
from __future__ import annotations

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
    SCRAPERAPI_KEY,
    SCRAPERAPI_ENDPOINT,
)


@dataclass
class ListingData:
    title: str | None
    price: float | None
    currency: str | None
    area_m2: float | None
    price_per_m2: float | None
    image_url: str | None = None
    location: str | None = None
    rooms: str | None = None
    floor: str | None = None


@dataclass
class SearchResultItem:
    url: str
    title: str | None
    price: float | None
    area_m2: float | None = None
    price_per_m2: float | None = None
    rooms: str | None = None
    floor: str | None = None
    image_url: str | None = None
    location: str | None = None
    description: str | None = None
    listing_id: str | None = None
    publish_date: str | None = None
    advertiser_type: str | None = None  # agencija / privatno


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


def _fetch_with_scraperapi(url: str, attempt: int = 1) -> tuple[str | None, str]:
    """Fetch preko ScraperAPI proxy-ja. Premium proxy ako standard pukne."""
    if not SCRAPERAPI_KEY:
        return None, "scraperapi key not configured"
    try:
        params = {
            "api_key": SCRAPERAPI_KEY,
            "url": url,
        }
        if attempt > 1:
            params["premium"] = "true"

        resp = requests.get(SCRAPERAPI_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            tag = "premium" if attempt > 1 else "standard"
            return resp.text, f"scraperapi {tag} ok ({len(resp.text)} bytes)"

        if resp.status_code == 500 and attempt == 1:
            print(f"     [fetch] scraperapi standard HTTP 500, retry sa premium proxy")
            return _fetch_with_scraperapi(url, attempt=2)

        error_snippet = resp.text[:200].replace("\n", " ") if resp.text else "(empty body)"
        return None, f"scraperapi HTTP {resp.status_code}: {error_snippet}"
    except requests.RequestException as e:
        return None, f"scraperapi exception: {type(e).__name__}: {e}"


def _fetch_with_requests(url: str) -> tuple[str | None, str]:
    """Obican requests. Brz, ali Cloudflare ga blokira sa 403."""
    try:
        resp = requests.get(url, headers=_build_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text, f"requests ok ({len(resp.text)} bytes)"
        return None, f"requests HTTP {resp.status_code}"
    except requests.RequestException as e:
        return None, f"requests exception: {type(e).__name__}: {e}"


def _fetch_with_playwright_stealth(url: str) -> tuple[str | None, str]:
    """Playwright sa stealth bibliotekom - probija Cloudflare na kucnom IP-u.
    Najsporiji ali najpouzdaniji nacin."""
    if not USE_PLAYWRIGHT_FALLBACK:
        return None, "playwright disabled"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright not installed (pip install playwright)"

    # Stealth je opcioni - radi i bez njega, ali bolje sa
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
    except ImportError:
        stealth = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="sr-RS",
                viewport={"width": 1280, "height": 800},
            )
            if stealth:
                stealth.apply_stealth_sync(context)

            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = response.status if response else None

            # Cloudflare ponekad treba 5-10s da prodje
            page.wait_for_timeout(8000)

            html = page.content()
            browser.close()

            if status and status != 200:
                return None, f"playwright HTTP {status}"
            if "Just a moment" in html and "QuidditaEnvironment" not in html:
                return None, f"playwright got Cloudflare challenge ({len(html)} bytes)"
            return html, f"playwright stealth ok ({len(html)} bytes)"
    except Exception as e:
        return None, f"playwright exception: {type(e).__name__}: {e}"


def fetch_page(url: str) -> str | None:
    """Strategija:
    1. Ako je SCRAPERAPI_KEY postavljen -> probaj ScraperAPI prvo (brze)
    2. Inace ili ako ScraperAPI pukne -> Playwright sa stealth (lokalni, kucni IP)
    """
    if SCRAPERAPI_KEY:
        html, msg = _fetch_with_scraperapi(url)
        print(f"     [fetch] {msg}")
        if html and len(html) > 1000 and "QuidditaEnvironment" in html:
            return html
        print(f"     [fetch] scraperapi nije dao validan HTML, prelazim na playwright stealth")

    html, msg = _fetch_with_playwright_stealth(url)
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
    """Izvlaci strukturirane podatke iz Halo oglasi detail stranice.

    Strategija (redom po pouzdanosti):
    1. JSON-LD blok sa schema.org/Product (najstabilniji, standardizovan format)
    2. QuidditaEnvironment.CurrentClassified -> OtherFields (cena_d, kvadratura_d)
    3. Meta tagovi (og:title, og:description) za fallback naslova
    """
    soup = BeautifulSoup(html, "lxml")

    title = None
    price = None
    currency = None
    area_m2 = None
    price_per_m2 = None
    image_url = None
    location = None
    rooms = None
    floor = None

    # 1. JSON-LD - najstabilniji izvor cene i slike
    for item in _extract_jsonld(soup):
        if not isinstance(item, dict):
            continue
        if item.get("@type") != "Product":
            continue
        if not title:
            title = item.get("name")
        # Slika iz JSON-LD
        if not image_url:
            img = item.get("image")
            if isinstance(img, str):
                image_url = img
            elif isinstance(img, list) and len(img) > 0:
                image_url = img[0]
        offers = item.get("offers")
        if isinstance(offers, dict):
            p = offers.get("price")
            if p is not None and price is None:
                try:
                    price = float(p)
                except (TypeError, ValueError):
                    price = _parse_number(str(p))
                currency = offers.get("priceCurrency") or currency

    # 2. QuidditaEnvironment.CurrentClassified -> OtherFields
    quiddita = _extract_quiddita_data(html)
    if quiddita:
        if not title:
            title = quiddita.get("Title") or quiddita.get("TextHtml")

        other_fields = quiddita.get("OtherFields") or {}

        # Cena: cena_d (numericka vrednost), cena_d_unit_s (valuta)
        if price is None:
            cena_raw = other_fields.get("cena_d") or other_fields.get("defaultunit_cena_d")
            if cena_raw is not None:
                try:
                    price = float(cena_raw)
                except (TypeError, ValueError):
                    price = _parse_number(str(cena_raw))
        if not currency:
            currency = other_fields.get("cena_d_unit_s") or "EUR"

        # Kvadratura
        kv_raw = (
            other_fields.get("kvadratura_d") or
            other_fields.get("defaultunit_kvadratura_d") or
            quiddita.get("Kvadratura") or
            quiddita.get("LivingArea")
        )
        if kv_raw is not None:
            try:
                area_m2 = float(kv_raw)
            except (TypeError, ValueError):
                area_m2 = _parse_number(str(kv_raw))

        # Slika iz ImageURLs liste
        if not image_url:
            image_urls = quiddita.get("ImageURLs") or []
            if isinstance(image_urls, list) and len(image_urls) > 0:
                first = image_urls[0]
                # ImageURLs su filename-ovi, treba dodati prefix
                if first and not first.startswith("http"):
                    image_url = f"https://img.halooglasi.com/slike/oglasi/Thumbs/{first}"
                else:
                    image_url = first

        # Lokacija iz OtherFields
        if not location:
            loc_parts = []
            for key in ["grad_s", "lokacija_s", "mikrolokacija_s", "ulica_t"]:
                v = other_fields.get(key)
                if v:
                    loc_parts.append(str(v))
            if loc_parts:
                location = ", ".join(loc_parts)

        # Sobe i sprat
        if not rooms:
            rooms_val = other_fields.get("broj_soba_s") or other_fields.get("broj_soba_d")
            if rooms_val:
                rooms = str(rooms_val)
        if not floor:
            floor_val = other_fields.get("sprat_s") or other_fields.get("spratnost_s")
            if floor_val:
                floor = str(floor_val)

    # 3. Fallback: meta tagovi
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content")

    if price is not None and area_m2 and area_m2 > 0:
        price_per_m2 = round(price / area_m2, 2)

    # Debug log kad nema cene
    if price is None:
        quiddita_keys = list(quiddita.keys())[:10] if quiddita else None
        print(f"     [parse] no price found. quiddita keys: {quiddita_keys}, title: {title!r}, html_len: {len(html)}")

    return ListingData(
        title=title.strip() if title else None,
        price=price,
        currency=currency,
        area_m2=area_m2,
        price_per_m2=price_per_m2,
        image_url=image_url,
        location=location,
        rooms=rooms,
        floor=floor,
    )


# ---------- Search results parsing ----------

def _parse_list_html(list_html: str) -> dict:
    """Iz ListHTML komada (pre-renderovan HTML kartice oglasa) izvlaci:
    cenu, kvadraturu, sobe, sprat, lokaciju, sliku, opis, datum, tip oglasivaca.
    """
    import html as html_module
    if not list_html:
        return {}
    # ListHTML dolazi HTML-encoded (&lt; &gt;), treba unescape
    decoded = html_module.unescape(list_html)
    soup = BeautifulSoup(decoded, "lxml")

    result = {}

    # Cena: <span data-value="74.000"><i>74.000 €</i></span>
    price_el = soup.select_one(".central-feature span[data-value]")
    if price_el:
        # data-value je "74.000" -> 74000
        dv = price_el.get("data-value", "").strip()
        result["price"] = _parse_number(dv)

    # Cena po m2: <div class="price-by-surface"><span>1.644 €/m²</span></div>
    pps_el = soup.select_one(".price-by-surface span")
    if pps_el:
        result["price_per_m2"] = _parse_number(pps_el.get_text())

    # Karakteristike: kvadratura, sobe, spratnost u ul.product-features
    for li in soup.select(".product-features li"):
        legend = li.select_one(".legend")
        if not legend:
            continue
        legend_text = legend.get_text(strip=True).lower()
        # Value je sve unutar value-wrapper-a minus legend
        wrapper = li.select_one(".value-wrapper")
        if not wrapper:
            continue
        # Izvuci tekst pre <span class="legend">
        full_text = wrapper.get_text(separator=" ", strip=True)
        value_text = full_text.replace(legend.get_text(strip=True), "").strip()

        if "kvadratura" in legend_text:
            result["area_m2"] = _parse_number(value_text)
        elif "broj soba" in legend_text:
            result["rooms"] = value_text
        elif "spratnost" in legend_text or "sprat" in legend_text:
            result["floor"] = value_text

    # Slika: prva pi-img-wrapper > img
    img_el = soup.select_one(".pi-img-wrapper img")
    if img_el:
        src = img_el.get("src", "")
        if src and "no-image" not in src:
            result["image_url"] = src

    # Lokacija: ul.subtitle-places
    places = [li.get_text(strip=True) for li in soup.select(".subtitle-places li")]
    if places:
        result["location"] = ", ".join(places)

    # Opis
    desc_el = soup.select_one(".text-description-list, .product-description")
    if desc_el:
        result["description"] = desc_el.get_text(strip=True)

    # Datum: <span class="publish-date">15.05.2026.</span>
    date_el = soup.select_one(".publish-date")
    if date_el:
        result["publish_date"] = date_el.get_text(strip=True)

    # Tip oglasivaca: data-field-value="agencija" ili "fizicko-lice"
    adv_el = soup.select_one("[data-field-name='oglasivac_nekretnine_s']")
    if adv_el:
        result["advertiser_type"] = adv_el.get("data-field-value") or adv_el.get_text(strip=True)

    return result


def parse_search_results(html: str, base_url: str = "https://www.halooglasi.com") -> list[SearchResultItem]:
    """Izvlaci listu oglasa iz search rezultata koristeci QuidditaEnvironment.serverListData.

    Halo oglasi vraca search rezultate kao JSON sa pre-renderovanim HTML komadom (ListHTML).
    Iz JSON-a uzimamo Title i RelativeUrl, iz ListHTML-a izvlacimo strukturirane podatke.
    """
    items: list[SearchResultItem] = []

    # Trazi serverListData
    m = re.search(r'QuidditaEnvironment\.serverListData\s*=\s*(\{.*?\});', html, re.DOTALL)
    if not m:
        # Backup: stara strategija sa HTML linkovima
        return _parse_search_results_fallback(html, base_url)

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return _parse_search_results_fallback(html, base_url)

    ads = data.get("Ads") or []
    for ad in ads:
        if not isinstance(ad, dict):
            continue

        relative_url = ad.get("RelativeUrl")
        title = ad.get("Title")
        if not relative_url:
            continue

        # Skini query string parametre (kid=, sid=) za canonical URL
        clean_url = relative_url.split("?")[0]
        full_url = base_url + clean_url if clean_url.startswith("/") else clean_url

        # Parse ListHTML za strukturirane podatke
        list_html = ad.get("ListHTML") or ""
        extracted = _parse_list_html(list_html)

        items.append(SearchResultItem(
            url=full_url,
            title=title.strip() if title else None,
            price=extracted.get("price"),
            area_m2=extracted.get("area_m2"),
            price_per_m2=extracted.get("price_per_m2"),
            rooms=extracted.get("rooms"),
            floor=extracted.get("floor"),
            image_url=extracted.get("image_url"),
            location=extracted.get("location"),
            description=extracted.get("description"),
            listing_id=str(ad.get("Id")) if ad.get("Id") else None,
            publish_date=extracted.get("publish_date"),
            advertiser_type=extracted.get("advertiser_type"),
        ))

    return items


def _parse_search_results_fallback(html: str, base_url: str) -> list[SearchResultItem]:
    """Fallback HTML parser - koristi se samo ako serverListData ne postoji."""
    soup = BeautifulSoup(html, "lxml")
    items: list[SearchResultItem] = []
    seen_urls: set[str] = set()

    listing_link_re = re.compile(r"/nekretnine/[^/]+/[^/]+/")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not listing_link_re.search(href):
            continue
        if href.startswith("/"):
            href = base_url + href
        if not re.search(r"/\d{6,}", href.split("?")[0]):
            continue

        clean_url = href.split("?")[0]
        if clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)

        title = a.get("title") or a.get_text(strip=True)[:200] or None
        items.append(SearchResultItem(url=clean_url, title=title, price=None))

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
