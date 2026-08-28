"""
Export every product and its native Shopify variants from Velossa Tech Design
to a Google Sheet (and optionally a local CSV).

This is a traditional Shopify catalog export: one row per real variant, with the
variant's option values, price, compare-at price, SKU, availability and inventory
— exactly how you would export a normal Shopify store. It replaces the old
Infinite Options scraper: the store has migrated to native Shopify variants, so
there is no longer any third-party widget to render or scrape.

Data source
-----------
GraphQL Admin API (`SHOPIFY_ADMIN_TOKEN` required). The Admin API is used because
several migrated products now carry hundreds — and in some cases over a thousand
— native variants (body colour x flare colour x flare shape). The public
`/products.json` storefront endpoint caps variants per product and would silently
truncate those products, so it is intentionally not used here.

Configuration (environment variables)
-------------------------------------
  SHOPIFY_ADMIN_TOKEN          Shopify Admin API access token (required).
                               Read from this var or the local file
                               `.velossa_admin_token`.
  SHOPIFY_STORE                Myshopify domain (default: velossatech.myshopify.com)
  SHOPIFY_API_VERSION          Admin API version (default: 2026-01)
  STORE_PUBLIC_URL             Public storefront URL for the Product URL column
                               (default: https://www.velossatechdesign.com)

  EXPORT_TO_SHEETS             true/false — write to Google Sheets (default: true)
  EXPORT_CSV_FILE              true/false — write a local CSV (default: true locally)
  OUTPUT_CSV                   CSV file name (default: Velossa-Products.csv)

  SHEETS_SPREADSHEET_ID        Target spreadsheet ID from the Sheet URL
  GOOGLE_SERVICE_ACCOUNT_JSON  Full service-account.json contents (Railway)
  SHEETS_CREDENTIALS_FILE      Path to service-account.json (local, default name)
  SHEETS_WORKSHEET             Worksheet/tab title or index to write (default: 0)

  FILTER_TAGS                  Optional comma-separated tag allow-list. When set,
                               only products carrying at least one of these tags
                               are exported. Empty (default) exports all products.
  PRODUCT_STATUS               active | archived | draft | any (default: active)
  MAX_PRODUCT_IMAGES           Max gallery image columns per product (default: 13)
  MAX_PRODUCTS                 Stop after N products — handy for a dry run
                               (default: 0 = full catalog)
  ONLY_HANDLES                 Comma-separated product handles to export only —
                               handy for a targeted dry run (default: all)

Google Sheets setup (one-time): see readme.md.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    print("Error: requests is not installed. Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORE_PUBLIC_URL = os.environ.get("STORE_PUBLIC_URL", "https://www.velossatechdesign.com").rstrip("/")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "velossatech.myshopify.com")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-01")

_token_file = os.environ.get("SHOPIFY_TOKEN_FILE", ".velossa_admin_token")
_token_from_file = ""
if os.path.exists(_token_file):
    with open(_token_file) as _f:
        _token_from_file = _f.read().strip()
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", _token_from_file)

# Dev Dashboard apps no longer expose a permanent shpat_ token (legacy custom apps
# were deprecated 2026-01-01). Instead we exchange the app's Client ID + Client
# Secret for a short-lived (~24h) access token via the client_credentials grant.
# This only works when the app and store live in the same Shopify organization.
# Credentials may be provided via env vars or a git-ignored .shopify_app.json
# file ({"client_id": "...", "client_secret": "..."}).
_app_creds: dict = {}
_app_creds_file = os.environ.get("SHOPIFY_APP_CREDENTIALS_FILE", ".shopify_app.json")
if os.path.exists(_app_creds_file):
    try:
        with open(_app_creds_file) as _f:
            _app_creds = json.load(_f)
    except (json.JSONDecodeError, OSError):
        _app_creds = {}

SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", _app_creds.get("client_id", ""))
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", _app_creds.get("client_secret", ""))

EXPORT_TO_SHEETS = os.environ.get("EXPORT_TO_SHEETS", "true").lower() == "true"
EXPORT_CSV_FILE = os.environ.get("EXPORT_CSV_FILE", "true").lower() == "true"
OUTPUT_CSV = os.environ.get("OUTPUT_CSV", "Velossa-Products.csv")

SHEETS_SPREADSHEET_ID = os.environ.get(
    "SHEETS_SPREADSHEET_ID", "1iV4e3nwf2kMAx2G7LZkxSyCopXxc867Jm4J7rvVcVUE"
)
SHEETS_CREDENTIALS_FILE = os.environ.get("SHEETS_CREDENTIALS_FILE", "service-account.json")
SHEETS_WORKSHEET = os.environ.get("SHEETS_WORKSHEET", "0")

FILTER_TAGS = {
    t.strip().lower()
    for t in os.environ.get("FILTER_TAGS", "").split(",")
    if t.strip()
}
PRODUCT_STATUS = os.environ.get("PRODUCT_STATUS", "active").strip().lower()
MAX_PRODUCT_IMAGES = int(os.environ.get("MAX_PRODUCT_IMAGES", "13"))

# GraphQL paging sizes (kept conservative to stay well under the cost limit).
PRODUCTS_PER_PAGE = int(os.environ.get("PRODUCTS_PER_PAGE", "25"))
VARIANTS_PER_PAGE = int(os.environ.get("VARIANTS_PER_PAGE", "100"))

# Dry-run cap: stop after this many products (0 = no limit / full catalog).
MAX_PRODUCTS = int(os.environ.get("MAX_PRODUCTS", "0"))

# Dry-run targeting: only export these specific product handles (comma-separated).
ONLY_HANDLES = [h.strip() for h in os.environ.get("ONLY_HANDLES", "").split(",") if h.strip()]

# Google Sheets write batch size (rows per update request). Kept conservative so
# each request stays well under the Sheets API payload limit at ~54k rows.
SHEETS_BATCH_ROWS = int(os.environ.get("SHEETS_BATCH_ROWS", "2000"))


# ---------------------------------------------------------------------------
# GraphQL Admin client
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "velossa-product-exporter/2.0"})

GRAPHQL_URL = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
OAUTH_TOKEN_URL = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"


def fetch_access_token_via_client_credentials() -> str:
    """
    Exchange the Dev Dashboard app's Client ID + Client Secret for a short-lived
    Admin API access token using the client_credentials grant.

    Requires the app and store to be in the same Shopify organization, the app to
    have a released version with the needed scopes, and the app to be installed on
    the store. The app must NOT use the legacy install flow, otherwise the granted
    scopes come back empty.
    """
    resp = SESSION.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"client_credentials token exchange failed (HTTP {resp.status_code}): {resp.text}\n"
            "  Check that the app is installed on the store, has a released version,\n"
            "  and that the app and store are in the same Shopify organization."
        )

    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in token response: {body}")

    scope = body.get("scope", "")
    expires = body.get("expires_in", "")
    print(f"  Access token acquired (scope='{scope}', expires_in={expires}s).")
    if not scope:
        print(
            "  WARNING: granted scope is empty. The app is likely using the legacy\n"
            "  install flow — disable it, re-release, and reinstall the app."
        )
    return token


def resolve_access_token() -> str:
    """Use a static token if provided, otherwise client_credentials."""
    # Accept real Admin API access tokens: shpat_ (custom app), shpca_ (offline
    # token from the authorization code grant), shppa_ (legacy). Reject shpss_,
    # which is an API secret key, not an access token.
    if SHOPIFY_ADMIN_TOKEN and SHOPIFY_ADMIN_TOKEN.startswith(("shpat_", "shpca_", "shppa_")):
        print(f"Using static Admin API token ({SHOPIFY_ADMIN_TOKEN[:6]}…).")
        return SHOPIFY_ADMIN_TOKEN

    if SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
        print("Requesting an Admin API access token via client_credentials grant ...")
        return fetch_access_token_via_client_credentials()

    raise SystemExit(
        "Error: no usable credentials found.\n"
        "  Provide either:\n"
        "    - SHOPIFY_ADMIN_TOKEN (a static shpat_... token), or\n"
        "    - SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET (Dev Dashboard app, recommended).\n"
        "  Credentials can be set as env vars or in a git-ignored .shopify_app.json."
    )


def graphql(query: str, variables: dict | None = None) -> dict:
    """
    Execute a GraphQL query with retry on throttling (cost limiter), rate
    limiting and transient 5xx errors. Returns the `data` object.
    """
    payload = {"query": query, "variables": variables or {}}

    for attempt in range(8):
        try:
            resp = SESSION.post(GRAPHQL_URL, json=payload, timeout=60)
        except requests.exceptions.ConnectionError as exc:
            wait = 2 ** attempt
            print(f"  Connection error ({exc}) — retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            print(f"  Rate limited (429) — waiting {wait:.1f}s...")
            time.sleep(wait)
            continue

        if resp.status_code in (500, 502, 503, 504):
            wait = 2 ** attempt
            print(f"  HTTP {resp.status_code} — retrying in {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        body = resp.json()

        errors = body.get("errors")
        if errors:
            throttled = any(
                (e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors
            )
            if throttled:
                wait = 2 ** attempt
                print(f"  Query throttled — backing off {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"GraphQL errors: {json.dumps(errors, indent=2)}")

        return body["data"]

    raise RuntimeError("Max retries exceeded talking to the Shopify Admin GraphQL API.")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_VARIANT_FIELDS = """
  id
  legacyResourceId
  title
  sku
  price
  compareAtPrice
  availableForSale
  selectedOptions { name value }
  image { url }
"""

PRODUCTS_QUERY = """
query Products($cursor: String, $productsPerPage: Int!, $variantsPerPage: Int!, $query: String) {
  products(first: $productsPerPage, after: $cursor, query: $query, sortKey: TITLE) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      legacyResourceId
      handle
      title
      vendor
      productType
      status
      tags
      onlineStoreUrl
      descriptionHtml
      createdAt
      updatedAt
      featuredImage { url }
      images(first: %d) { nodes { url } }
      options { name position }
      variants(first: $variantsPerPage) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % (MAX_PRODUCT_IMAGES, _VARIANT_FIELDS)

PRODUCT_VARIANTS_QUERY = """
query ProductVariants($id: ID!, $cursor: String, $variantsPerPage: Int!) {
  product(id: $id) {
    variants(first: $variantsPerPage, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % _VARIANT_FIELDS


def _status_query_filter() -> str | None:
    clauses: list[str] = []
    if PRODUCT_STATUS not in ("", "any", "all"):
        clauses.append(f"status:{PRODUCT_STATUS}")
    if ONLY_HANDLES:
        handle_clause = " OR ".join(f"handle:{h}" for h in ONLY_HANDLES)
        clauses.append(f"({handle_clause})")
    if not clauses:
        return None
    return " AND ".join(clauses)


def fetch_all_variants_for_product(product_gid: str, first_page_variants: dict) -> list[dict]:
    """Return every variant for a product, paginating past the first page."""
    variants: list[dict] = list(first_page_variants.get("nodes", []))
    page_info = first_page_variants.get("pageInfo", {})
    cursor = page_info.get("endCursor")
    has_next = page_info.get("hasNextPage", False)

    while has_next:
        data = graphql(
            PRODUCT_VARIANTS_QUERY,
            {"id": product_gid, "cursor": cursor, "variantsPerPage": VARIANTS_PER_PAGE},
        )
        conn = (data.get("product") or {}).get("variants") or {}
        variants.extend(conn.get("nodes", []))
        page_info = conn.get("pageInfo", {})
        cursor = page_info.get("endCursor")
        has_next = page_info.get("hasNextPage", False)

    return variants


def fetch_all_products() -> list[dict]:
    """Page through all products, resolving full variant lists for each."""
    products: list[dict] = []
    cursor: str | None = None
    query_filter = _status_query_filter()
    page = 0

    print(f"Fetching products from {SHOPIFY_STORE} (GraphQL Admin API {SHOPIFY_API_VERSION}) ...")

    while True:
        data = graphql(
            PRODUCTS_QUERY,
            {
                "cursor": cursor,
                "productsPerPage": PRODUCTS_PER_PAGE,
                "variantsPerPage": VARIANTS_PER_PAGE,
                "query": query_filter,
            },
        )
        conn = data["products"]
        nodes = conn["nodes"]
        page += 1

        if MAX_PRODUCTS and len(products) + len(nodes) > MAX_PRODUCTS:
            nodes = nodes[: MAX_PRODUCTS - len(products)]

        for node in nodes:
            node["_all_variants"] = fetch_all_variants_for_product(
                node["id"], node.get("variants") or {}
            )
        products.extend(nodes)

        total_variants = sum(len(p["_all_variants"]) for p in products)
        print(
            f"  Page {page}: {len(nodes)} products "
            f"(total products: {len(products)}, variants: {total_variants})"
        )

        if MAX_PRODUCTS and len(products) >= MAX_PRODUCTS:
            print(f"  Reached MAX_PRODUCTS={MAX_PRODUCTS} (dry run) — stopping.")
            break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
        time.sleep(0.2)

    return products


# ---------------------------------------------------------------------------
# Shaping
# ---------------------------------------------------------------------------

def _plain_text(body: str) -> str:
    if not body:
        return ""
    text = re.sub(r"<[^>]+>", " ", body)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _gallery_image_urls(product: dict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in (product.get("images") or {}).get("nodes", []):
        u = (img or {}).get("url") or ""
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    if not urls:
        feat = (product.get("featuredImage") or {}).get("url")
        if feat:
            urls.append(feat)
    return urls[:MAX_PRODUCT_IMAGES]


def _matches_filter(product: dict) -> bool:
    if not FILTER_TAGS:
        return True
    tags = {t.strip().lower() for t in product.get("tags", [])}
    return bool(FILTER_TAGS & tags)


def shape_rows(products: list[dict]) -> tuple[list[dict], int]:
    """One flat dict per variant. Gallery images only on each product's first row."""
    rows: list[dict] = []
    max_images = 0

    for p in products:
        if not _matches_filter(p):
            continue

        handle = p.get("handle", "")
        option_names = [o["name"] for o in sorted(p.get("options", []), key=lambda o: o["position"])]
        image_urls = _gallery_image_urls(p)
        max_images = max(max_images, len(image_urls))

        product_base = {
            "Product ID": p.get("legacyResourceId", ""),
            "Handle": handle,
            "Title": p.get("title", ""),
            "Vendor": p.get("vendor", ""),
            "Product Type": p.get("productType", ""),
            "Status": (p.get("status") or "").lower(),
            "Tags": ", ".join(p.get("tags", [])),
            "Product URL": p.get("onlineStoreUrl") or f"{STORE_PUBLIC_URL}/products/{handle}",
            "Created At": p.get("createdAt", ""),
            "Updated At": p.get("updatedAt", ""),
        }
        description = _plain_text(p.get("descriptionHtml", ""))

        variants = p.get("_all_variants", [])
        for v_index, v in enumerate(variants):
            selected = {so["name"]: so["value"] for so in v.get("selectedOptions", [])}

            option_cols: dict[str, str] = {}
            for i in range(1, 4):
                name = option_names[i - 1] if i <= len(option_names) else ""
                option_cols[f"Option{i} Name"] = name
                option_cols[f"Option{i} Value"] = selected.get(name, "") if name else ""

            # Heavy product-level fields (Description, gallery images) live on the
            # first variant row only — Shopify-CSV style — to avoid duplicating
            # kilobytes of text across hundreds/thousands of variant rows.
            gallery_cols = {
                f"Image URL {i}": (image_urls[i - 1] if (v_index == 0 and i <= len(image_urls)) else "")
                for i in range(1, MAX_PRODUCT_IMAGES + 1)
            }

            rows.append({
                **product_base,
                "Description": description if v_index == 0 else "",
                **option_cols,
                "Variant ID": v.get("legacyResourceId", ""),
                "Variant SKU": v.get("sku") or "",
                "Price": v.get("price", ""),
                "Compare At Price": v.get("compareAtPrice") or "",
                "Available": v.get("availableForSale", ""),
                "Variant Image": (v.get("image") or {}).get("url", "") or "",
                **gallery_cols,
            })

    return rows, max_images


def build_fieldnames(num_images: int) -> list[str]:
    image_cols = [f"Image URL {i}" for i in range(1, num_images + 1)]
    return [
        "Product ID",
        "Handle",
        "Title",
        "Vendor",
        "Product Type",
        "Status",
        "Tags",
        "Product URL",
        "Description",
        "Option1 Name",
        "Option1 Value",
        "Option2 Name",
        "Option2 Value",
        "Option3 Name",
        "Option3 Value",
        "Variant ID",
        "Variant SKU",
        "Price",
        "Compare At Price",
        "Available",
        "Variant Image",
        *image_cols,
        "Created At",
        "Updated At",
    ]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(rows: list[dict], fieldnames: list[str]) -> None:
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: r.get(k, "") for k in fieldnames} for r in rows)
    print(f"Exported {len(rows)} variant row(s) -> {OUTPUT_CSV}")


def _resolve_worksheet(spreadsheet, identifier: str):
    """Select a worksheet by zero-based index or by title."""
    if identifier.isdigit():
        return spreadsheet.get_worksheet(int(identifier))
    try:
        return spreadsheet.worksheet(identifier)
    except Exception:
        return spreadsheet.get_worksheet(0)


def export_to_sheets(rows: list[dict], fieldnames: list[str]) -> None:
    try:
        import gspread
        from gspread.utils import ValueInputOption, rowcol_to_a1
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Error: gspread / google-auth not installed. Run: pip install gspread google-auth")
        sys.exit(1)

    if not SHEETS_SPREADSHEET_ID:
        print("Error: SHEETS_SPREADSHEET_ID is not set.")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        print("Authenticating with GOOGLE_SERVICE_ACCOUNT_JSON ...")
        creds = Credentials.from_service_account_info(json.loads(raw_json), scopes=scopes)
    elif os.path.exists(SHEETS_CREDENTIALS_FILE):
        print(f"Authenticating with {SHEETS_CREDENTIALS_FILE} ...")
        creds = Credentials.from_service_account_file(SHEETS_CREDENTIALS_FILE, scopes=scopes)
    else:
        print(
            "Error: No Google credentials found.\n"
            "  Set GOOGLE_SERVICE_ACCOUNT_JSON (Railway/CI) or place a key file at "
            f"{SHEETS_CREDENTIALS_FILE}."
        )
        sys.exit(1)

    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEETS_SPREADSHEET_ID)
    worksheet = _resolve_worksheet(spreadsheet, SHEETS_WORKSHEET)

    all_values = [fieldnames] + [[str(r.get(f, "")) for f in fieldnames] for r in rows]
    num_rows = len(all_values)
    num_cols = len(fieldnames)

    # Size the sheet to fit, then clear stale content.
    worksheet.resize(rows=max(num_rows, 1), cols=num_cols)
    worksheet.clear()

    # Write in batches to stay under per-request size limits.
    start = 0
    while start < num_rows:
        chunk = all_values[start:start + SHEETS_BATCH_ROWS]
        a1_start = rowcol_to_a1(start + 1, 1)
        a1_end = rowcol_to_a1(start + len(chunk), num_cols)
        worksheet.update(
            range_name=f"{a1_start}:{a1_end}",
            values=chunk,
            value_input_option=ValueInputOption.user_entered,
        )
        start += len(chunk)
        print(f"  Wrote rows {start}/{num_rows}")
        if start < num_rows:
            time.sleep(1.0)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{SHEETS_SPREADSHEET_ID}"
    print(f"Exported {len(rows)} variant row(s) -> Google Sheet ('{worksheet.title}')")
    print(f"  {sheet_url}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    token = resolve_access_token()
    SESSION.headers.update({"X-Shopify-Access-Token": token})

    products = fetch_all_products()
    rows, num_images = shape_rows(products)
    fieldnames = build_fieldnames(num_images)

    if not rows:
        print("No products/variants to export.")
        return

    exported_products = len({r["Product ID"] for r in rows})
    print(f"\nProducts exported : {exported_products}")
    print(f"Variant rows      : {len(rows)}")
    if num_images:
        print(f"Image columns     : {num_images} (Image URL 1 ... Image URL {num_images})")
    if FILTER_TAGS:
        print(f"Tag filter        : {', '.join(sorted(FILTER_TAGS))}")
    print()

    if EXPORT_CSV_FILE:
        export_csv(rows, fieldnames)
    if EXPORT_TO_SHEETS:
        export_to_sheets(rows, fieldnames)


if __name__ == "__main__":
    main()
