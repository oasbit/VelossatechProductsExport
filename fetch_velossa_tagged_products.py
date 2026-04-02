"""
Fetch all products from Velossa Tech Design that have at least one of the
specified option/customization tags, and export them to a Google Sheet and
optionally a local CSV file.

Site:   Velossa Tech Design – https://www.velossatechdesign.com/
Output: Google Sheet  (when EXPORT_TO_SHEETS = true)
        CSV file      (when EXPORT_CSV_FILE = true, local runs only)

Uses the public Shopify storefront endpoint — no API credentials required.
Only returns products that are currently published/active.

Configuration (environment variables):
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
PAGE_SIZE  = 250   # Maximum allowed by the public endpoint

EXPORT_TO_SHEETS  = os.environ.get("EXPORT_TO_SHEETS",  "true").lower()  == "true"
EXPORT_CSV_FILE   = os.environ.get("EXPORT_CSV_FILE",   "true").lower()  == "true"

SHEETS_SPREADSHEET_ID   = os.environ.get("SHEETS_SPREADSHEET_ID",   "1kmZ-a9shCMNbtdnJhZJvP4vo9hhHCHcXdzvUQgaG7n0")
SHEETS_CREDENTIALS_FILE = os.environ.get("SHEETS_CREDENTIALS_FILE", "service-account.json")

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


# ---------------------------------------------------------------------------
# Filter and shape
# ---------------------------------------------------------------------------

def filter_and_shape(raw_products: list[dict]) -> list[dict]:
    """
    Keep only products that have at least one TARGET_TAG.
    Returns a list of flat dicts ready for CSV export.
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

        results.append({
            "Product ID":      p["id"],
            "Title":           p["title"],
            "Handle":          p["handle"],
            "Product Type":    p.get("product_type", ""),
            "Variants Count":  len(p.get("variants", [])),
            "Matched Tags":    ", ".join(matched),
            "Product URL":     f"{STORE_URL}/products/{p['handle']}",
            "Created At":      p.get("created_at", ""),
            "Updated At":      p.get("updated_at", ""),
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
    "Variants Count",
    "Matched Tags",
    "Product URL",
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
    raw = fetch_all_products()
    print(f"\nTotal products on store : {len(raw)}")

    matched = filter_and_shape(raw)

    if not matched:
        print("No products found matching the specified tags.")
        return

    # Per-tag breakdown
    tag_counts: dict[str, int] = {}
    for p in matched:
        for tag in p["Matched Tags"].split(", "):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    print(f"Matching products       : {len(matched)}")
    print("\nBreakdown by matched tag:")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:<20} {count}")

    print()
    if EXPORT_CSV_FILE:
        export_csv(matched)

    if EXPORT_TO_SHEETS:
        export_to_sheets(matched)


if __name__ == "__main__":
    main()
