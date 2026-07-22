"""
================================================================================
  FASHIONPHILE Scraper — Runner
================================================================================
  This is the entry point for running the scraper.

  HOW TO USE:
    1. Add / edit the URLs in the `URLS` list below.
    2. (Optional) Change MAX_PAGES  (0 = fetch every page).
    3. Run:   python run.py

  Each URL is scraped in turn. Output is written to ./output_data/ as
  <brand>_fashionphile.json  (the brand is read from the URL's vendor filter).
================================================================================
"""

from Scraper import scrape_fashionphile

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURE YOUR URLS HERE
# ══════════════════════════════════════════════════════════════════════════════
#  Paste one or more Fashionphile collection URLs.
#  Tip: to target a single brand, use a URL with the vendor filter, e.g.
#  ...all-bags?refinementList%5Bvendor%5D%5B0%5D=Chanel&sortBy=...
# ══════════════════════════════════════════════════════════════════════════════

URLS = [
    "https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=MCM&sortBy=shopify_products_published_at_desc",
    # "https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=Chanel&sortBy=shopify_products_published_at_desc",
    # "https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=Gucci&sortBy=shopify_products_published_at_desc",
]

# Number of listing pages to fetch per URL.  0 (or None) = fetch ALL pages.
MAX_PAGES = 0


# ══════════════════════════════════════════════════════════════════════════════
#  RUNNER  (no need to edit below)
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not URLS:
        print("No URLs configured. Add at least one URL to the URLS list in run.py.")
        return

    print(f"Queued {len(URLS)} URL(s) to scrape.\n")

    for i, url in enumerate(URLS, 1):
        print("\n" + "#" * 70)
        print(f"#  URL {i}/{len(URLS)}")
        print("#" * 70)
        try:
            scrape_fashionphile(run_url=url, max_pages=MAX_PAGES)
        except Exception as e:
            print(f"[ERROR] Failed to scrape URL {i}: {e}")

    print("\nAll done.")


if __name__ == "__main__":
    main()
