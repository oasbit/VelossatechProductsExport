# Velossatech Products Export

Fetches all products from [Velossa Tech Design](https://www.velossatechdesign.com/) that contain at least one of the defined customization/option tags, then exports the results to a **CSV file** and optionally to a **Google Sheet**.

Uses the public Shopify storefront JSON endpoint — no Shopify API credentials required.

---

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

### CSV export only (default)

```bash
python fetch_velossa_tagged_products.py
```

Output file: `Velossa-Tagged-Products.csv`

### CSV + Google Sheets export

See the [Google Sheets setup](#google-sheets-setup) section below, then set the following flags inside the script:

```python
EXPORT_TO_SHEETS        = True
SHEETS_CREDENTIALS_FILE = "service-account.json"   # path to your service account key
SHEETS_SPREADSHEET_ID   = "<your-spreadsheet-id>"  # from the Sheet URL
SHEETS_WORKSHEET_NAME   = "Products"               # tab name
```

Then run the script as normal:

```bash
python fetch_velossa_tagged_products.py
```

---

## Google Sheets Setup

This is a one-time setup per Google Cloud project.

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
> Add it to `.gitignore` if using version control.

### 5. Share the Google Sheet with the service account

- Open your target Google Sheet.
- Click **Share** and add the service account email address (found in `service-account.json` under `"client_email"`).
- Grant it **Editor** access.

### 6. Get the Spreadsheet ID

Copy the ID from the Sheet URL:

```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

Paste it into `SHEETS_SPREADSHEET_ID` in the script.

---

## Exported Columns

| Column | Description |
|---|---|
| Product ID | Shopify internal product ID |
| Title | Product title |
| Handle | URL-friendly product slug |
| Product Type | Shopify product type |
| Variants Count | Number of variants |
| Matched Tags | Customization tags found on the product |
| Product URL | Direct link to the product page |
| Created At | ISO 8601 creation timestamp |
| Updated At | ISO 8601 last-updated timestamp |

---

## Target Tags

The following customization/option tags are used to filter products:

`flarecolor`, `bodycolor`, `makemodel`, `universal`, `subarumodel`, `f150year`, `focusyear`, `musbumper`, `musconfig`, `grilletype`, `musgrille`, `musresonator`, `brakecool`, `keycolor`, `fusionlower`, `fusionpedal`, `pedalinlay`, `pedalbackground`, `winglift`, `plugcolor`, `fincolor`, `elantratrans`, `g70trim`, `canistercolor`, `bigconfig`, `suvbigconfig`, `halo`

To add or remove tags, edit the `TARGET_TAGS` set in the script.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `STORE_URL` | `https://www.velossatechdesign.com` | Shopify store base URL |
| `OUTPUT_CSV` | `Velossa-Tagged-Products.csv` | Output CSV file name |
| `PAGE_SIZE` | `250` | Products per API page (max 250) |
| `EXPORT_TO_SHEETS` | `False` | Enable Google Sheets export |
| `SHEETS_CREDENTIALS_FILE` | `service-account.json` | Path to service account key file |
| `SHEETS_SPREADSHEET_ID` | `` | Target Google Spreadsheet ID |
| `SHEETS_WORKSHEET_NAME` | `Products` | Target worksheet/tab name |
