# FASHIONPHILE Scraper

A Python scraper for [Fashionphile](https://www.fashionphile.com) that collects
pre-owned luxury **handbag** listings and exports them as structured JSON.

It reads product data from Fashionphile's public Shopify collection API
(`/collections/<handle>/products.json`), filters out non-handbag items (jewelry,
shoes, sunglasses, wallets, etc.), then visits each product page to enrich the
record with condition, dimensions, materials, hardware, color, and more.

---

## Features

- **URL-driven** — just paste collection URLs into `run.py` and run.
- **Brand filtering** — reads the `vendor` filter from the URL and targets that brand's collection.
- **Handbag-only** — includes/excludes items by type, title, and tags.
- **Rich extraction** — condition, dimensions (converted to cm), exterior/interior material, hardware, color, item number, "includes", images, price, and sold status.
- **Anti-rate-limit** — retry/backoff, reduced page size, and randomized delays to avoid `429` errors.
- **Cleaner utility** — `cleen.py` removes duplicates, bad subcategories, and dead (404) product URLs from a whole folder of scraped files, with a live progress bar.

---

## Requirements

- Python 3.9+
- Dependencies listed in `Requirements.txt`:

```
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
pydantic>=2.0.0
urllib3>=2.0.0
playwright>=1.38.0
```

### Install

```bash
# (recommended) create a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r Requirements.txt
```

> Note: `playwright` is listed but the current scraper uses `requests` only.
> You can omit it if you don't need it.

---

## Usage

### 1. Configure URLs

Open `run.py` and edit the `URLS` list. Add one or more Fashionphile collection URLs:

```python
URLS = [
    "https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=MCM&sortBy=shopify_products_published_at_desc",
    # "https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=Chanel&sortBy=shopify_products_published_at_desc",
]

MAX_PAGES = 0   # 0 = fetch ALL pages, or set a number to limit
```

To target a single brand, use a URL containing the vendor filter
(`refinementList[vendor][0]=<Brand>`). The scraper reads the brand from that
parameter and names the output file accordingly.

### 2. Run

```bash
python run.py
```

Each URL is scraped in turn. Progress is logged to the console.

### 3. Output

Results are written to `./output_data/` as:

```
<brand>_fashionphile.json     e.g. mcm_fashionphile.json
```

(If no brand filter is present, the file is named `all_fashionphile.json`.)

---

## Output format

Each record is a JSON object:

```json
{
  "category": "bags",
  "subcategory": "Backpacks",
  "brand": "MCM",
  "model_title": "Calfskin Essential Visetos Small Backpack Powder Pink",
  "gender": "Women",
  "product_description": {
    "material": "grained calfskin leather",
    "hardware": "Faint scratch(es)",
    "Exterior": "Creases, marks",
    "Interior": "Marks",
    "color": "Pink",
    "origin": null,
    "includes": "FASHIONPHILE Certificate of Authenticity, dust bag, 2 straps",
    "item_number": "1767221",
    "description": "This is an authentic MCM ..."
  },
  "size": null,
  "dims": { "length": "22.9 cm", "height": "23.5 cm", "width": "11.4 cm", "drop": "41.3 cm" },
  "condition": 4,
  "condition_description": { "description": "Item is clean and contains very little wear. ..." },
  "url": "https://www.fashionphile.com/products/mcm-...-1767221",
  "shop": "Fashionphile",
  "price": "600.00",
  "currency": "USD",
  "sold": false,
  "image_urls": ["https://cdn.shopify.com/..."],
  "main_image_url": null
}
```

### Condition scale

| ID | Name       |
| -- | ---------- |
| 0  | Flawed     |
| 1  | Fair       |
| 2  | Worn       |
| 3  | Shows Wear |
| 4  | Excellent  |
| 5  | New        |
| 6  | Giftable   |

---

## Cleaning the data (optional)

`cleen.py` post-processes **every `.json` file in a folder**, one by one, and writes
the cleaned versions (same filenames) to a `CleanData/` folder. For each file it removes:

1. **Duplicate products** — matched by URL (falling back to item number); the first occurrence is kept.
2. Products with a **blocked subcategory** (e.g. `"Accessories"`, `"Best of Sale"`, or a brand name used as a subcategory).
3. Products whose **URL returns a "Page not found" / 404**.

A live progress bar is shown while URLs are checked, and a per-file + overall summary
is printed at the end.

Edit the config at the top of the file if you want different folders:

```python
INPUT_DIR  = "./output_data"   # folder of JSON files to clean
OUTPUT_DIR = "./CleanData"     # cleaned files are written here (same filenames)
```

Then run:

```bash
python cleen.py
```

Example: `output_data/mcm_fashionphile.json` → `CleanData/mcm_fashionphile.json`.

---

## Project structure

```
FASHIONPHILE_site_v2/
├── run.py              # Entry point — configure URLs here, then run
├── Scraper.py          # Core scraper logic (fetch, filter, parse, export)
├── cleen.py            # Post-processing cleaner (dupes + bad subcategories + dead URLs)
├── Requirements.txt    # Python dependencies
├── output_data/        # Scraped JSON output (created automatically)
└── CleanData/          # Cleaned JSON output from cleen.py (created automatically)
```

---

## How it works

1. **`run.py`** iterates over your `URLS` and calls `scrape_fashionphile()` for each.
2. **Listing fetch** — `fetch_listing_smart()` pulls products from the collection's
   `products.json` API in pages of 50, with random delays and 429 handling.
3. **Filtering** — `is_handbag()` keeps only handbag-type items.
4. **Enrichment** — each product page is fetched and `parse_product_page()` extracts
   condition, dimensions, materials, color, item number, and subcategory.
5. **Export** — records are sorted by brand/title and written to `output_data/`.

---

## Notes & tips

- **Be polite.** The scraper already adds delays and backoff. Avoid running many
  brands in parallel or lowering the delays, or you may hit `429 Too Many Requests`.
- **`max_workers` is set to 1** in `Scraper.py` for complete/stable extraction.
  Increasing it speeds things up but raises rate-limit risk.
- Fashionphile's site structure can change; if extraction of a field stops working,
  the CSS selectors / regex in `parse_product_page()` may need updating.

---

## Disclaimer

This tool is for educational and personal research purposes. Respect
Fashionphile's Terms of Service and `robots.txt`, and scrape responsibly.
"# FashionPhile_scraper" 
