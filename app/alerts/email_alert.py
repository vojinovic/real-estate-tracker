"""Email alerti preko Gmail SMTP-a (App Password)."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import (
    SMTP_HOST,
    SMTP_PORT,
    EMAIL_FROM,
    EMAIL_PASSWORD,
    EMAIL_TO,
)


def _send_email(subject: str, html_body: str, text_body: str) -> bool:
    if not (EMAIL_FROM and EMAIL_PASSWORD and EMAIL_TO):
        print(f"[email] Skipping (no SMTP config): {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"[email] Sent: {subject}")
        return True
    except Exception as e:
        print(f"[email] FAILED: {subject} - {e}")
        return False


def _fmt_price(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f} {currency}".replace(",", ".")


def alert_price_drop(listing: dict, new_price: float, old_price: float):
    change = new_price - old_price
    pct = (change / old_price) * 100 if old_price else 0
    note = listing.get("note") or listing.get("title") or "Oglas"

    subject = f"Cena pala: {note} ({pct:+.1f}%)"
    text = (
        f"Cena oglasa je pala.\n\n"
        f"Oglas: {note}\n"
        f"Stara cena: {_fmt_price(old_price)}\n"
        f"Nova cena:  {_fmt_price(new_price)}\n"
        f"Promena:    {_fmt_price(change)} ({pct:+.1f}%)\n\n"
        f"Link: {listing['url']}\n"
    )
    html = f"""
    <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #c62828;">Cena oglasa je pala</h2>
        <p><strong>Oglas:</strong> {note}</p>
        <table style="border-collapse: collapse;">
            <tr><td style="padding: 4px 12px 4px 0;">Stara cena:</td><td><strong>{_fmt_price(old_price)}</strong></td></tr>
            <tr><td style="padding: 4px 12px 4px 0;">Nova cena:</td><td><strong style="color: #c62828;">{_fmt_price(new_price)}</strong></td></tr>
            <tr><td style="padding: 4px 12px 4px 0;">Promena:</td><td>{_fmt_price(change)} ({pct:+.1f}%)</td></tr>
        </table>
        <p><a href="{listing['url']}">Otvori oglas</a></p>
    </body></html>
    """
    return _send_email(subject, html, text)


def alert_listing_unavailable(listing: dict):
    note = listing.get("note") or listing.get("title") or "Oglas"
    last_price = listing.get("current_price")
    subject = f"Oglas nestao: {note}"
    text = (
        f"Oglas vise nije dostupan.\n\n"
        f"Oglas: {note}\n"
        f"Poslednja cena: {_fmt_price(last_price)}\n"
        f"Link: {listing['url']}\n"
    )
    html = f"""
    <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #ef6c00;">Oglas vise nije dostupan</h2>
        <p><strong>Oglas:</strong> {note}</p>
        <p>Poslednja zabelezena cena: <strong>{_fmt_price(last_price)}</strong></p>
        <p><a href="{listing['url']}">Pokusaj otvoriti oglas</a></p>
    </body></html>
    """
    return _send_email(subject, html, text)


def alert_new_listings_in_search(search: dict, new_items: list):
    """new_items: list[SearchResultItem]"""
    if not new_items:
        return False
    name = search.get("name") or "Pretraga"
    subject = f"Novi oglasi: {name} ({len(new_items)})"

    text_lines = [f"Pronadjeno {len(new_items)} novih oglasa u pretrazi '{name}':\n"]
    html_rows = []
    for item in new_items:
        price_str = _fmt_price(item.price) if item.price else ""
        text_lines.append(f"- {item.title or '(bez naslova)'} {price_str}\n  {item.url}")
        html_rows.append(
            f'<li><a href="{item.url}">{item.title or "(bez naslova)"}</a>'
            f' <span style="color:#666;">{price_str}</span></li>'
        )

    text = "\n".join(text_lines)
    html = f"""
    <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #2e7d32;">Novi oglasi u pretrazi: {name}</h2>
        <p>Pronadjeno <strong>{len(new_items)}</strong> novih oglasa od poslednje provere.</p>
        <ul>{''.join(html_rows)}</ul>
        <p style="color:#666; font-size:12px;">Pretraga: <a href="{search['url']}">{search['url']}</a></p>
    </body></html>
    """
    return _send_email(subject, html, text)
