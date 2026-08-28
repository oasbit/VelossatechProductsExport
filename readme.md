# Velossatech Products Export

Exports the full [Velossa Tech Design](https://www.velossatechdesign.com/) catalog
— **every product and every native Shopify variant, with prices** — to a **Google
Sheet** (and optionally a local CSV). One row per variant, exactly like a normal
Shopify store export.

> **Migration note:** Velossa Tech has moved off the Infinite Options app to
> native Shopify variants. This exporter therefore reads variants directly from
> the Shopify Admin API. There is **no more page scraping / headless browser** —
> the previous Infinite Options Playwright scraper has been retired.

---

## How it works

1. Connects to the **Shopify GraphQL Admin API** using `SHOPIFY_ADMIN_TOKEN`.
2. Pages through every product and resolves the **complete** variant list for
   each one (paginating past 100/250 where needed). This matters because several
   migrated products now have hundreds — and some over a thousand — native
   variants (body colour × flare colour × flare shape).
3. Flattens to **one row per variant** with native option columns, price,
   compare-at price, SKU and availability.
4. Writes the result to the target Google Sheet in batches (and/or a CSV).

The public `/products.json` storefront endpoint is intentionally **not** used as
the data source because it caps variants at **250 per product** and would silently
truncate the high-variant products. This store has **43 products above 250
variants** (the largest has **1,700**), so storefront mode would drop real data.
The Admin API path paginates variants per product, so nothing is lost.

---

## Authentication

Legacy "custom apps" created in the store admin (which exposed a permanent
`shpat_` token) were **deprecated on 2026-01-01** and can no longer be created.
New apps are built in the **Dev Dashboard** and expose only a Client ID + Client
Secret. There are two ways to turn those into an Admin API token:

- **Client credentials grant** — simplest, but only works when the app **and**
  store are in the **same Shopify organization**. An agency app installed on a
  client's production store returns `shop_not_permitted`. The script will use this
  automatically if `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` are set and the
  store is in the same org.
- **Authorization code grant** — works **across organizations** and yields a
  **permanent** offline token (`shpca_…`/`shpat_…`, valid until the app is
  uninstalled). Use the included helper `get_offline_token.py` once to mint it.

### Mint a permanent token with `get_offline_token.py`

1. In the Dev Dashboard app: enable **"Use legacy install flow"**, add the
   Redirect URL `http://localhost:3456/callback`, set scopes
   `read_products, read_inventory`, and **Release** a version.
2. Put the app's Client ID/Secret in a git-ignored `.shopify_app.json`
   (`{"client_id": "...", "client_secret": "..."}`) or env vars.
3. Run:

```bash
SHOPIFY_STORE=velossatech.myshopify.com python3 get_offline_token.py
```

4. Open the printed authorize URL in a browser logged into the store admin and
   approve. The helper captures the code, exchanges it, and writes the token to
   `.velossa_admin_token`.

Set that token as `SHOPIFY_ADMIN_TOKEN` on Railway. It does not expire, so no
refresh logic is needed.

---

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install -r requirements.txt
```

No browser/Playwright is required.

---

## Usage

```bash
# Full export to Google Sheets (+ local CSV)
SHOPIFY_ADMIN_TOKEN=shpca_xxx python3 export_shopify_products.py

# CSV only (no Sheets), handy for local testing
EXPORT_TO_SHEETS=false python3 export_shopify_products.py

# Dry run: just the first N products to a CSV
MAX_PRODUCTS=4 EXPORT_TO_SHEETS=false OUTPUT_CSV=dry-run.csv python3 export_shopify_products.py
```

Local CSV output: `Velossa-Products.csv`

The Admin token can also be placed in a local file named `.velossa_admin_token`
(git-ignored) instead of the environment variable — this is what
`get_offline_token.py` writes. See **Authentication** above to obtain a token.

---

## Google Sheets Setup

One-time setup per Google Cloud project.

1. **Create a Google Cloud project** at [console.cloud.google.com](https://console.cloud.google.com/).
2. **Enable the Google Sheets API** under *APIs & Services > Library*.
3. **Create a Service Account** under *APIs & Services > Credentials*.
4. **Download a JSON key** (*Keys > Add Key > Create new key > JSON*) and save it
   as `service-account.json` in this folder (git-ignored).
5. **Share the target Google Sheet** with the service account email
   (`client_email` in the JSON) as **Editor**.
6. **Copy the Spreadsheet ID** from the Sheet URL
   (`https://docs.google.com/spreadsheets/d/<ID>/edit`) into `SHEETS_SPREADSHEET_ID`.

---

## Environment Variables

```bash
# ── Shopify Admin API ──────────────────────────────────────────────────────
SHOPIFY_ADMIN_TOKEN=              # required: Admin API access token (shpat_...)
SHOPIFY_STORE=velossatech.myshopify.com
SHOPIFY_API_VERSION=2026-01
STORE_PUBLIC_URL=https://www.velossatechdesign.com

# ── Google Sheets ──────────────────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON=      # full JSON content of service-account.json (Railway)
SHEETS_SPREADSHEET_ID=1iV4e3nwf2kMAx2G7LZkxSyCopXxc867Jm4J7rvVcVUE
SHEETS_CREDENTIALS_FILE=service-account.json   # local key file path
SHEETS_WORKSHEET=0                # worksheet tab index or title

# ── Export behaviour ───────────────────────────────────────────────────────
EXPORT_TO_SHEETS=true
EXPORT_CSV_FILE=true              # set false on Railway (no persistent filesystem)
OUTPUT_CSV=Velossa-Products.csv
PRODUCT_STATUS=active             # active | archived | draft | any
FILTER_TAGS=                      # optional comma-separated tag allow-list (empty = all products)
MAX_PRODUCT_IMAGES=13             # gallery image columns per product
MAX_PRODUCTS=0                    # stop after N products (0 = all); set e.g. 5 for a dry run
```

---

## Exported Columns

| Column | Description |
|---|---|
| Product ID | Shopify product ID (numeric) |
| Handle | URL slug |
| Title | Product title |
| Vendor | Product vendor |
| Product Type | Shopify product type |
| Status | active / archived / draft |
| Tags | Comma-separated product tags |
| Product URL | Storefront product link |
| Description | Description as plain text, HTML stripped (populated on each product's first variant row only, Shopify-CSV style) |
| Option1 Name / Value | First native option (e.g. "Body/Snorkel Color" → "Red") |
| Option2 Name / Value | Second native option |
| Option3 Name / Value | Third native option |
| Variant ID | Shopify variant ID (numeric) |
| Variant SKU | Variant SKU |
| Price | Variant price |
| Compare At Price | Original price before discount |
| Available | Whether the variant is purchasable |
| Variant Image | Variant-specific image URL (if any) |
| Image URL 1 … N | Product gallery images (populated on each product's first variant row, Shopify-CSV style) |
| Created At / Updated At | ISO 8601 timestamps |

---

## Railway Deployment

`railway.toml` runs the exporter daily at 08:00 UTC:

```toml
[deploy]
startCommand = "python3 export_shopify_products.py"
cronSchedule = "0 8 * * *"
```

The slim `Dockerfile` installs only the Python dependencies — no Chromium.

Set the environment variables above in Railway's **Variables** tab. On Railway,
use `GOOGLE_SERVICE_ACCOUNT_JSON` (not a key file) and set `EXPORT_CSV_FILE=false`.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `SHOPIFY_ADMIN_TOKEN` | — | **Required.** Admin API access token |
| `SHOPIFY_STORE` | `velossatech.myshopify.com` | Myshopify domain |
| `SHOPIFY_API_VERSION` | `2026-01` | Admin API version |
| `STORE_PUBLIC_URL` | `https://www.velossatechdesign.com` | Storefront base for Product URL fallback |
| `EXPORT_TO_SHEETS` | `true` | Write to Google Sheets |
| `EXPORT_CSV_FILE` | `true` | Write a local CSV |
| `OUTPUT_CSV` | `Velossa-Products.csv` | CSV file name |
| `SHEETS_SPREADSHEET_ID` | (target sheet) | Google Spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Service account JSON (Railway) |
| `SHEETS_CREDENTIALS_FILE` | `service-account.json` | Local key file path |
| `SHEETS_WORKSHEET` | `0` | Worksheet tab index or title |
| `PRODUCT_STATUS` | `active` | Product status filter |
| `FILTER_TAGS` | — | Optional tag allow-list (empty = all products) |
| `MAX_PRODUCT_IMAGES` | `13` | Gallery image columns per product |
| `MAX_PRODUCTS` | `0` | Stop after N products (0 = all); use for dry runs |
| `PRODUCTS_PER_PAGE` | `25` | Products per GraphQL page |
| `VARIANTS_PER_PAGE` | `100` | Variants per GraphQL page |
| `SHEETS_BATCH_ROWS` | `2000` | Rows per Sheets write request |
