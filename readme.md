# Velossatech Products Export

Fetches all active products from [Velossa Tech Design](https://www.velossatechdesign.com/) that contain at least one of the defined customization/option tags, scrapes their [Infinite Options](https://www.shoppad.co/infinite-options/) option groups via headless Chromium, and exports everything to a **CSV file** and/or a **Google Sheet**.

---

## Requirements

- Python 3.9+
- Install Python dependencies:

```bash
pip install -r requirements.txt
```

- Install the Playwright Chromium browser (needed for Infinite Options scraping):

```bash
playwright install chromium
```

---

## Usage

### Run locally (CSV + Google Sheets)

```bash
python3 fetch_velossa_tagged_products.py
```

Output file: `Velossa-Tagged-Products.csv`

The script auto-selects the data source:

- **Admin API** — used when `SHOPIFY_ADMIN_TOKEN` is set. Returns all products and all variants.
- **Storefront API** — public fallback, no credentials needed. May cap variants per product.

### Disable Infinite Options scraping (faster, for testing)

```bash
SCRAPE_INFINITE_OPTIONS=false python3 fetch_velossa_tagged_products.py
```

---

## Google Sheets Setup

One-time setup per Google Cloud project.

### 1. Create a Google Cloud project

Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a new project (or use an existing one).

### 2. Enable the Google Sheets API

- In the Cloud Console, navigate to **APIs & Services > Library**.
- Search for **Google Sheets API** and click **Enable**.

### 3. Create a Service Account

- Navigate to **APIs & Services > Credentials**.
- Click **Create Credentials > Service Account**.
- Give it any name (e.g. `velossa-exporter`) and click **Done**.

### 4. Download the JSON key

- Click the service account you just created.
- Go to the **Keys** tab > **Add Key > Create new key > JSON**.
- Save the downloaded file as `service-account.json` in this project folder.

> Keep this file private — it grants write access to any Sheet you share with it.
> It is in `.gitignore` so it will not be committed.

### 5. Share the Google Sheet with the service account

- Open your target Google Sheet.
- Click **Share** and add the service account email (found in `service-account.json` under `"client_email"`).
- Grant it **Editor** access.

### 6. Get the Spreadsheet ID

Copy the ID from the Sheet URL:

```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

Set it as the `SHEETS_SPREADSHEET_ID` environment variable (see `.env` below).

---

## Environment Variables

Copy the following into a `.env` file for local runs, or set them directly in Railway.

```bash
# ── Shopify Admin API ──────────────────────────────────────────────────────
SHOPIFY_ADMIN_TOKEN=              # Shopify Admin API access token
SHOPIFY_STORE=velossatech.myshopify.com

# ── Google Sheets ──────────────────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON=      # Full JSON content of service-account.json (one line, for Railway)
SHEETS_SPREADSHEET_ID=            # From the Sheet URL: .../d/<ID>/edit
SHEETS_CREDENTIALS_FILE=service-account.json   # Path to key file (local only)

# ── Export behaviour ───────────────────────────────────────────────────────
EXPORT_TO_SHEETS=true             # Enable Google Sheets export
EXPORT_CSV_FILE=true              # Write a local CSV file (set false on Railway)

# ── Infinite Options scraping ──────────────────────────────────────────────
SCRAPE_INFINITE_OPTIONS=true      # Scrape IO option groups via headless Chromium
IO_CONCURRENCY=5                  # Parallel browser pages (increase to speed up)
```

---

## Exported Columns

| Column | Description |
|---|---|
| Product ID | Shopify internal product ID |
| Title | Product title |
| Handle | URL-friendly product slug |
| Product Type | Shopify product type |
| Matched Tags | Customization tags found on the product |
| Product URL | Direct link to the product page |
| Description | Product description as plain text (HTML stripped from `body_html`) |
| Image URL | Image for this variant when available; otherwise the product’s featured / first image |
| IO Option 1 Name | First Infinite Options group name (e.g. "Body/Snorkel Color") |
| IO Option 1 Values | Comma-separated list of values for option group 1 |
| IO Option 2 Name | Second Infinite Options group name |
| IO Option 2 Values | Comma-separated list of values for option group 2 |
| IO Option 3–5 Name/Values | Additional option groups (up to 5 total) |
| Variant ID | Shopify variant ID |
| Variant Title | Variant title (usually "Default Title" for IO-managed products) |
| Price | Variant price |
| Compare At Price | Original price before discount |
| SKU | Variant SKU |
| Available | Whether the variant is in stock |
| Created At | ISO 8601 creation timestamp |
| Updated At | ISO 8601 last-updated timestamp |

---

## Target Tags

The following customization/option tags are used to filter products:

`flarecolor`, `bodycolor`, `makemodel`, `universal`, `subarumodel`, `f150year`, `focusyear`, `musbumper`, `musconfig`, `grilletype`, `musgrille`, `musresonator`, `brakecool`, `keycolor`, `fusionlower`, `fusionpedal`, `pedalinlay`, `pedalbackground`, `winglift`, `plugcolor`, `fincolor`, `elantratrans`, `g70trim`, `canistercolor`, `bigconfig`, `suvbigconfig`, `halo`

To add or remove tags, edit the `TARGET_TAGS` set in the script.

---

## Railway Deployment

The project includes a `Dockerfile` that bakes Python, Playwright, and the Chromium browser into the image. Railway automatically detects and uses it.

The `railway.toml` schedules the script to run daily at 08:00 UTC:

```toml
[deploy]
startCommand = "python3 fetch_velossa_tagged_products.py"
cronSchedule = "0 8 * * *"
```

Set all environment variables listed above in Railway's **Variables** tab. Do **not** set `EXPORT_CSV_FILE=true` on Railway (no persistent filesystem). Use `GOOGLE_SERVICE_ACCOUNT_JSON` instead of `SHEETS_CREDENTIALS_FILE` to pass the service account credentials as a single environment variable.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `STORE_URL` | `https://www.velossatechdesign.com` | Shopify store base URL |
| `OUTPUT_CSV` | `Velossa-Tagged-Products.csv` | Output CSV file name |
| `PAGE_SIZE` | `250` | Products per API page (max 250) |
| `EXPORT_TO_SHEETS` | `true` | Enable Google Sheets export |
| `EXPORT_CSV_FILE` | `true` | Write a local CSV file |
| `SHEETS_CREDENTIALS_FILE` | `service-account.json` | Path to service account key file |
| `SHEETS_SPREADSHEET_ID` | — | Target Google Spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Full service account JSON string (Railway) |
| `SHOPIFY_ADMIN_TOKEN` | — | Shopify Admin API access token |
| `SHOPIFY_STORE` | `velossatech.myshopify.com` | Myshopify domain |
| `SHOPIFY_API_VERSION` | `2026-01` | Shopify API version |
| `SCRAPE_INFINITE_OPTIONS` | `true` | Scrape Infinite Options via headless Chromium |
| `IO_CONCURRENCY` | `5` | Number of parallel browser pages for scraping |
