"""
Fetch all products from Velossa Tech Design that have at least one of the
specified option/customization tags, and export them to a Google Sheet and
optionally a local CSV file.

Site:   Velossa Tech Design – https://www.velossatechdesign.com/
Output: Google Sheet  (when EXPORT_TO_SHEETS = true)
        CSV file      (when EXPORT_CSV_FILE = true, local runs only)

Data source (auto-selected):
  Admin API  — used when SHOPIFY_ADMIN_TOKEN is set. Returns ALL products and
               ALL variants including unpublished ones and products with 100+
               variants. Recommended for accurate data.
  Storefront — public /products.json fallback (no credentials needed). Returns
               only published products and caps variants per product.

Configuration (environment variables):
  SHOPIFY_ADMIN_TOKEN         Shopify Admin API access token (from .velossa_admin_token
                              or set manually). Unlocks full variant data.
  SHOPIFY_STORE               Myshopify domain, e.g. velossatech.myshopify.com
                              (only needed with SHOPIFY_ADMIN_TOKEN)
  EXPORT_TO_SHEETS            true/false  — enable Google Sheets export (default: true)
  EXPORT_CSV_FILE             true/false  — write a local CSV file (default: true)
  SHEETS_SPREADSHEET_ID       Google Spreadsheet ID from the Sheet URL (…/d/<ID>/edit)
  GOOGLE_SERVICE_ACCOUNT_JSON Full contents of your service-account.json (for Railway)
  SHEETS_CREDENTIALS_FILE     Path to service-account.json (for local runs, default: service-account.json)

Google Sheets setup (one-time):
  1. Create a Google Cloud project and enable the Google Sheets API.
  2. Create a Service Account and download its JSON key file.
  3. Share your target Google Sheet with the service account e-mail (editor access).
  4. Set SHEETS_SPREADSHEET_ID and credential env vars as described above.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("Error: requests package not installed.")
    print("Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration — driven by environment variables with sensible local defaults
# ---------------------------------------------------------------------------

STORE_URL  = "https://www.velossatechdesign.com"
OUTPUT_CSV = "Velossa-Tagged-Products.csv"
PAGE_SIZE  = 250   # Maximum allowed by both endpoints

EXPORT_TO_SHEETS  = os.environ.get("EXPORT_TO_SHEETS",  "true").lower()  == "true"
EXPORT_CSV_FILE   = os.environ.get("EXPORT_CSV_FILE",   "true").lower()  == "true"

SHEETS_SPREADSHEET_ID   = os.environ.get("SHEETS_SPREADSHEET_ID",   "1kmZ-a9shCMNbtdnJhZJvP4vo9hhHCHcXdzvUQgaG7n0")
SHEETS_CREDENTIALS_FILE = os.environ.get("SHEETS_CREDENTIALS_FILE", "service-account.json")

# -- Shopify Admin API (optional) -------------------------------------------
# When set, uses the Admin API to get ALL variants and ALL products (including
# unpublished). Token is read from the env var or from the local token file.
_token_file = os.environ.get("SHOPIFY_TOKEN_FILE", ".velossa_admin_token")
_token_from_file = ""
if os.path.exists(_token_file):
    with open(_token_file) as _f:
        _token_from_file = _f.read().strip()

SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", _token_from_file)
SHOPIFY_STORE       = os.environ.get("SHOPIFY_STORE", "velossatech.myshopify.com")
SHOPIFY_API_VERSION = "2026-01"

TARGET_TAGS: set[str] = {
    "flarecolor",
    "bodycolor",
    "makemodel",
    "universal",
    "subarumodel",
    "f150year",
    "focusyear",
    "musbumper",
    "musconfig",
    "grilletype",
    "musgrille",
    "musresonator",
    "brakecool",
    "keycolor",
    "fusionlower",
    "fusionpedal",
    "pedalinlay",
    "pedalbackground",
    "winglift",
    "plugcolor",
    "fincolor",
    "elantratrans",
    "g70trim",
    "canistercolor",
    "bigconfig",
    "suvbigconfig",
    "halo",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "velossa-tag-exporter/1.0"})


def get_json(url: str, params: dict | None = None) -> dict | list:
    """GET a URL with automatic retry on rate limit and transient errors."""
    for attempt in range(7):
        try:
            resp = SESSION.get(url, params=params, timeout=15)
        except requests.exceptions.ConnectionError as exc:
            wait = 2 ** attempt
            print(f"  Connection error ({exc}) — retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            print(f"  Rate limited — waiting {wait:.1f}s before retry...")
            time.sleep(wait)
            continue

        if resp.status_code in (502, 503, 504):
            wait = 2 ** attempt
            print(f"  HTTP {resp.status_code} — retrying in {wait}s (attempt {attempt + 1}/7)...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("Max retries exceeded — server unavailable.")


# ---------------------------------------------------------------------------
# Fetch all products
# ---------------------------------------------------------------------------

def fetch_all_products() -> list[dict]:
    """
    Pages through /products.json until an empty page is returned.
    Returns the raw list of all product dicts from the storefront.
    """
    all_products: list[dict] = []
    page = 1

    print(f"Fetching all products from {STORE_URL} ...")

    while True:
        data = get_json(
            f"{STORE_URL}/products.json",
            params={"limit": PAGE_SIZE, "page": page},
        )
        products: list[dict] = data.get("products", [])

        if not products:
            break

        all_products.extend(products)
        print(f"  Page {page}: {len(products)} products fetched (total: {len(all_products)})")

        if len(products) < PAGE_SIZE:
            # Last page — no need for an extra empty request
            break

        page += 1
        time.sleep(0.3)

    return all_products


def fetch_all_products_admin() -> list[dict]:
    """
    Pages through the Shopify Admin API /products.json using cursor-based
    pagination (Link header). Returns all products with complete variant data.
    Requires SHOPIFY_ADMIN_TOKEN to be set.
    """
    all_products: list[dict] = []
    url    = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/products.json"
    params = {"limit": PAGE_SIZE, "status": "active"}

    print(f"Fetching all products via Admin API ({SHOPIFY_STORE}) ...")

    while url:
        for attempt in range(7):
            try:
                resp = SESSION.get(url, params=params, timeout=15)
            except requests.exceptions.ConnectionError as exc:
                wait = 2 ** attempt
                print(f"  Connection error ({exc}) — retrying in {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"  Rate limited — waiting {wait:.1f}s before retry...")
                time.sleep(wait)
                continue

            if resp.status_code in (502, 503, 504):
                wait = 2 ** attempt
                print(f"  HTTP {resp.status_code} — retrying in {wait}s (attempt {attempt + 1}/7)...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            break

        products: list[dict] = resp.json().get("products", [])
        all_products.extend(products)
        print(f"  Fetched {len(products)} products (total: {len(all_products)})")

        # Follow the next-page cursor from the Link header
        link_header = resp.headers.get("Link", "")
        next_url = None
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break

        url    = next_url
        params = {}   # URL already contains all params when paginating
        if url:
            time.sleep(0.3)

    return all_products


# ---------------------------------------------------------------------------
# Filter and shape
# ---------------------------------------------------------------------------

def filter_and_shape(raw_products: list[dict]) -> list[dict]:
    """
    Keep only products that have at least one TARGET_TAG.
    Returns one flat dict per variant (one row per variant in the output).
    """
    results: list[dict] = []

    for p in raw_products:
        raw_tags = p.get("tags", [])
        # Public endpoint returns tags as a list; guard against unexpected string format
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        product_tags: set[str] = {t.strip().lower() for t in raw_tags}
        matched: list[str] = sorted(TARGET_TAGS & product_tags)

        if not matched:
            continue

        product_base = {
            "Product ID":    p["id"],
            "Title":         p["title"],
            "Handle":        p["handle"],
            "Product Type":  p.get("product_type", ""),
            "Matched Tags":  ", ".join(matched),
            "Product URL":   f"{STORE_URL}/products/{p['handle']}",
            "Created At":    p.get("created_at", ""),
            "Updated At":    p.get("updated_at", ""),
        }

        for v in p.get("variants", []):
            results.append({
                **product_base,
                "Variant ID":       v["id"],
                "Variant Title":    v.get("title", ""),
                "Price":            v.get("price", ""),
                "Compare At Price": v.get("compare_at_price") or "",
                "SKU":              v.get("sku") or "",
                "Available":        v.get("available", ""),
            })

    return results


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "Product ID",
    "Title",
    "Handle",
    "Product Type",
    "Matched Tags",
    "Product URL",
    "Variant ID",
    "Variant Title",
    "Price",
    "Compare At Price",
    "SKU",
    "Available",
    "Created At",
    "Updated At",
]


def export_csv(products: list[dict]) -> None:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(products)

    print(f"Exported {len(products)} product(s) → {OUTPUT_CSV}")


def export_to_sheets(products: list[dict]) -> None:
    """
    Write the product list to a Google Sheet, replacing all existing content.

    Requires:
      - gspread         (pip install gspread)
      - google-auth     (pip install google-auth)
      - A service account JSON key file shared with the target spreadsheet.
    """
    try:
        import gspread
        from gspread.utils import ValueInputOption
        from google.oauth2.service_account import Credentials
    except ImportError:
        print(
            "Error: gspread / google-auth packages are not installed.\n"
            "Run: pip install gspread google-auth"
        )
        sys.exit(1)

    if not SHEETS_SPREADSHEET_ID:
        print("Error: SHEETS_SPREADSHEET_ID env var is not set.")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        print("Authenticating with service account from GOOGLE_SERVICE_ACCOUNT_JSON env var ...")
        creds = Credentials.from_service_account_info(json.loads(raw_json), scopes=scopes)
    elif os.path.exists(SHEETS_CREDENTIALS_FILE):
        print(f"Authenticating with service account from {SHEETS_CREDENTIALS_FILE} ...")
        creds = Credentials.from_service_account_file(SHEETS_CREDENTIALS_FILE, scopes=scopes)
    else:
        print(
            "Error: No Google credentials found.\n"
            "  Set the GOOGLE_SERVICE_ACCOUNT_JSON env var (Railway / CI)\n"
            f"  or place a service account key at: {SHEETS_CREDENTIALS_FILE}"
        )
        sys.exit(1)

    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SHEETS_SPREADSHEET_ID)
    worksheet   = spreadsheet.get_worksheet(0)

    # Build rows: header first, then one row per product
    rows = [FIELDNAMES] + [[str(p[field]) for field in FIELDNAMES] for p in products]

    worksheet.clear()
    worksheet.update(rows, value_input_option=ValueInputOption.user_entered)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{SHEETS_SPREADSHEET_ID}"
    print(f"Exported {len(products)} product(s) → Google Sheet ('{worksheet.title}')")
    print(f"  {sheet_url}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if SHOPIFY_ADMIN_TOKEN:
        SESSION.headers.update({"X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN})
        raw = fetch_all_products_admin()
        print(f"\nTotal products (Admin API) : {len(raw)}")
    else:
        print("No SHOPIFY_ADMIN_TOKEN found — falling back to public storefront API.")
        print("Note: variant data may be incomplete for products with many variants.")
        raw = fetch_all_products()
        print(f"\nTotal products (storefront) : {len(raw)}")

    matched = filter_and_shape(raw)

    if not matched:
        print("No products found matching the specified tags.")
        return

    # Per-tag breakdown — count unique products (not variant rows)
    tag_products: dict[str, set] = {}
    seen: set = set()
    for row in matched:
        pid = row["Product ID"]
        if pid not in seen:
            seen.add(pid)
            for tag in row["Matched Tags"].split(", "):
                tag_products.setdefault(tag, set()).add(pid)

    print(f"Matching products       : {len(seen)}")
    print(f"Total variant rows      : {len(matched)}")
    print("\nBreakdown by matched tag:")
    for tag, prods in sorted(tag_products.items(), key=lambda x: -len(x[1])):
        print(f"  {tag:<20} {len(prods)}")

    print()
    if EXPORT_CSV_FILE:
        export_csv(matched)

    if EXPORT_TO_SHEETS:
        export_to_sheets(matched)


if __name__ == "__main__":
    main()
