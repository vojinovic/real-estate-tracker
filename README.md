# Real Estate Tracker

Prati cene oglasa nekretnina na Halo oglasima i salje email alerte kada se cena promeni,
kada oglas nestane, ili kada se pojave novi oglasi u pretrazi.

## Struktura

```
real-estate-tracker/
  app/
    scrapers/
      halooglasi.py        # Scraper za halooglasi.com (requests + Playwright fallback)
    alerts/
      email_alert.py       # Gmail SMTP alerti
    storage/
      database.py          # SQLite schema + CRUD
    config.py              # Env vars i konstante
    tracker.py             # Main orchestrator
  data/
    tracker.db             # SQLite baza (commit-uje se u repo)
  listings.csv             # Lista oglasa za pracenje
  searches.csv             # Lista pretraga za pracenje (novi oglasi)
  .github/workflows/
    check-prices.yml       # Cron: svaki dan 06:30 UTC
  requirements.txt
```

## Setup

### 1. Klon i instalacija

```bash
git clone <repo>
cd real-estate-tracker
python -m venv .venv
source .venv/bin/activate  # ili .venv\Scripts\activate na Windowsu
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Gmail App Password

1. Idi na https://myaccount.google.com/apppasswords (mora da imas 2FA upaljen)
2. Generisi App Password za "Mail"
3. Kopiraj 16-cifreni kod

### 3. Lokalni .env (za testiranje)

Kopiraj `.env.example` u `.env` i popuni:

```
EMAIL_FROM=tvoj.email@gmail.com
EMAIL_PASSWORD=app_password_iz_koraka_2
EMAIL_TO=isto_ili_drugi_email@gmail.com
```

### 4. Dodaj oglase u listings.csv

```csv
id,url,type,city,note
1,https://www.halooglasi.com/nekretnine/prodaja-stanova/.../5425123456789,stan,Nis,Durlan trosoban
2,https://www.halooglasi.com/nekretnine/prodaja-lokala/.../5425987654321,lokal,Nis,Lokal centar
```

### 5. (Opciono) Dodaj search trackere u searches.csv

```csv
id,name,url,note
1,Stanovi Nis Durlan do 80k,https://www.halooglasi.com/nekretnine/prodaja-stanova/nis?cena_d_to=80000,stan
```

Da bi search radio kako treba, najlakse je da odes na Halo oglasi, podesis filtere, 
i kopiras URL iz adresne linije.

### 6. Lokalni test

```bash
python -m app.tracker
```

Prvi run nece slati alerte (samo upisuje baseline cene i listinge).

### 7. GitHub Actions setup

1. Push repo na GitHub
2. Settings -> Secrets and variables -> Actions -> New repository secret:
   - `EMAIL_FROM`
   - `EMAIL_PASSWORD`  
   - `EMAIL_TO`
3. Cron radi automatski svaki dan u 06:30 UTC.
4. Mozes manuelno da pokrenes iz Actions tab -> "Check Real Estate Prices" -> Run workflow.

## Kako radi

**Listings tracker:**
1. Za svaki URL iz `listings.csv`, otvara stranicu
2. Cita strukturirane podatke (QuidditaEnvironment + JSON-LD)
3. Uporedjuje sa poslednjom cenom u bazi
4. Salje email ako je cena pala
5. Posle 3 uzastopne greske markira oglas kao "unavailable" i salje "oglas nestao" alert

**Search tracker:**
1. Za svaki URL iz `searches.csv`, otvara stranicu rezultata
2. Izvlaci sve linkove ka detail stranicama
3. Uporedjuje sa "vec videnim" listinzima iz baze
4. Salje email sa listom novih oglasa
5. Prva provera nije alert (samo se belezi baseline)

## Podesavanja

U `app/config.py`:

- `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS` - random pauza izmedju requestova
- `ERROR_THRESHOLD_FOR_UNAVAILABLE` - koliko gresaka pre nego sto se markira kao unavailable
- `USE_PLAYWRIGHT_FALLBACK` - da li da koristi Playwright kad requests pukne

## Alerti

Trenutno aktivni:
- Pad cene
- Oglas nestao  
- Novi oglas u pretrazi

Beleze se u bazu ali se ne salje email:
- Porast cene
- Promena drugih polja

## Sledeci koraci (v2)

- Telegram bot kao drugi kanal
- Web dashboard za pregled price history grafova
- Podrska za nekretnine.rs i 4zida.rs
- Detekcija duplikata istog oglasa preko vise sajtova
