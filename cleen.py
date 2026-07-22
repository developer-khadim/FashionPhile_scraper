"""
FASHIONPHILE JSON Cleaner
=========================
Processes EVERY .json file in an input folder (INPUT_DIR), one by one.
For each file it removes products that:
  1. Have a blocked subcategory  →  "Accessories", "Best of Sale", or any brand name
     used as a subcategory (e.g. "Louis Vuitton", "Prada")
  2. Return a "Page not found" response when their URL is visited

Each cleaned file is written to OUTPUT_DIR (./CleanData) with the same filename.
"""

import json
import time
import sys
import os
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# Force UTF-8 stdout so emojis / box-drawing chars work on Windows terminals
# (cp1252) too. Safe no-op on consoles that already use UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── Configuration ────────────────────────────────────────────────────────────

INPUT_DIR  = "./output_data"      # folder containing the JSON files to clean
OUTPUT_DIR = "./CleanData"        # cleaned files are written here (same filename)

# Subcategories to remove (case-insensitive match)
BLOCKED_SUBCATEGORIES = {
    "accessories",
    "best of sale",
    "louis vuitton",
    "prada",
    "gucci",
    "chanel",
    "hermes",
    "hermès",
    "dior",
    "fendi",
    "burberry",
    "versace",
    "valentino",
    "balenciaga",
    "givenchy",
    "bottega veneta",
    "saint laurent",
    "celine",
    "céline",
    "loewe",
    "mcm",
    "coach",
    "kate spade",
    "michael kors",
}

# "Page not found" detection — phrases that appear in the page body
PAGE_NOT_FOUND_PHRASES = [
    "page not found",
    "we can't find the page you're looking for",
    "the url might be an old link",
    "404",
]

# HTTP settings
REQUEST_TIMEOUT   = 15          # seconds per request
MAX_WORKERS       = 10          # parallel URL checks
RETRY_ATTEMPTS    = 2           # retries on connection error
DELAY_BETWEEN_REQ = 0.1         # seconds between thread launches (be polite)

# ── Helpers ──────────────────────────────────────────────────────────────────

def is_blocked_subcategory(subcategory: str) -> bool:
    """Return True if this subcategory should be removed."""
    return (subcategory or "").strip().lower() in BLOCKED_SUBCATEGORIES


def is_page_not_found(url: str) -> bool:
    """
    Fetch the URL and check if it returns a "page not found" page.
    Returns True  → product should be removed.
    Returns False → product URL is alive (or we couldn't determine).
    """
    if not url:
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                # 4xx status codes via urlopen raise HTTPError; 200-range land here
                body = resp.read(8192).decode("utf-8", errors="ignore").lower()
                return any(phrase in body for phrase in PAGE_NOT_FOUND_PHRASES)

        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return True          # definitely gone
            # 5xx, 403, etc. → treat as alive (don't delete)
            return False

        except Exception:
            if attempt < RETRY_ATTEMPTS:
                time.sleep(1)
                continue
            # Network error / timeout → be conservative, keep the product
            return False

    return False


def check_url_worker(item_tuple):
    """Worker function for the thread pool."""
    index, item = item_tuple
    url = item.get("url", "")
    dead = is_page_not_found(url)
    return index, dead, url


def print_progress(done: int, total: int, prefix: str = "", bar_len: int = 30):
    """Draw / update a single-line progress bar in the terminal."""
    total = max(total, 1)
    frac = done / total
    filled = int(bar_len * frac)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(f"\r    {prefix} |{bar}| {done:>5}/{total} ({frac*100:5.1f}%)")
    sys.stdout.flush()
    if done >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def remove_duplicates(products: list) -> tuple:
    """Remove duplicate products, keeping the first occurrence.
    A product is considered a duplicate if its URL (preferred) or item_number
    matches one already seen. Returns (unique_list, removed_count)."""
    seen = set()
    unique = []
    removed = 0
    for item in products:
        url = (item.get("url") or "").strip().lower()
        item_no = str(item.get("product_description", {}).get("item_number", "")).strip()
        key = url or f"item:{item_no}" or None
        if key and key in seen:
            removed += 1
            continue
        if key:
            seen.add(key)
        unique.append(item)
    return unique, removed


# ── Clean a single file ───────────────────────────────────────────────────────

def clean_file(input_path: str, output_path: str) -> dict:
    """Clean one JSON file and write the result to output_path.
    Returns a stats dict for the summary."""
    # ── 1. Load data ─────────────────────────────────────────────────────────
    print(f"📂  Loading  {input_path} …")
    with open(input_path, encoding="utf-8") as f:
        products = json.load(f)

    total_original = len(products)
    print(f"    Total products loaded : {total_original:,}")

    # ── 2. Remove duplicates ─────────────────────────────────────────────────
    print("🧹  Step 1 — Removing duplicates …")
    products, removed_dupes = remove_duplicates(products)
    print(f"    Removed  (duplicates)      : {removed_dupes:,}")
    print(f"    Remaining after this step  : {len(products):,}")

    # ── 3. Remove blocked subcategories ──────────────────────────────────────
    print("🔍  Step 2 — Filtering blocked subcategories …")
    after_subcat = []
    removed_subcat = []

    for item in products:
        subcat = item.get("subcategory", "")
        if is_blocked_subcategory(subcat):
            removed_subcat.append(item)
        else:
            after_subcat.append(item)

    print(f"    Removed  (bad subcategory) : {len(removed_subcat):,}")
    print(f"    Remaining after this step  : {len(after_subcat):,}")

    # Breakdown by subcategory value
    from collections import Counter
    breakdown = Counter(i.get("subcategory","") for i in removed_subcat)
    for val, cnt in breakdown.most_common():
        print(f"      └─ '{val}' : {cnt:,} products")

    # ── 4. Check URLs for dead pages ─────────────────────────────────────────
    total_urls = len(after_subcat)
    print(f"🌐  Step 3 — Checking {total_urls:,} product URLs for 'Page not found' …")
    print(f"    (workers={MAX_WORKERS}, timeout={REQUEST_TIMEOUT}s per request)")

    dead_indices   = set()
    checked        = 0
    tasks          = list(enumerate(after_subcat))

    print_progress(0, total_urls, prefix="URLs")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for task in tasks:
            future = executor.submit(check_url_worker, task)
            futures[future] = task
            time.sleep(DELAY_BETWEEN_REQ)

        for future in as_completed(futures):
            index, dead, _url = future.result()
            checked += 1
            if dead:
                dead_indices.add(index)
            print_progress(checked, total_urls, prefix="URLs")

    removed_url_count = len(dead_indices)
    print(f"    Dead URLs removed : {removed_url_count:,}")

    # ── 5. Build the final clean list ─────────────────────────────────────────
    cleaned = [item for i, item in enumerate(after_subcat) if i not in dead_indices]

    total_removed = removed_dupes + len(removed_subcat) + removed_url_count

    # ── 6. Save output ────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"    Output saved → {output_path}")

    return {
        "file": os.path.basename(input_path),
        "original": total_original,
        "removed_dupes": removed_dupes,
        "removed_subcat": len(removed_subcat),
        "removed_url": removed_url_count,
        "total_removed": total_removed,
        "cleaned": len(cleaned),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not os.path.isdir(INPUT_DIR):
        print(f"❌  Input folder not found: {INPUT_DIR}")
        return

    json_files = sorted(
        f for f in os.listdir(INPUT_DIR)
        if f.lower().endswith(".json")
    )

    if not json_files:
        print(f"⚠️   No .json files found in {INPUT_DIR}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Found {len(json_files)} JSON file(s) in {INPUT_DIR}\n")

    all_stats = []
    for i, fname in enumerate(json_files, 1):
        print("#" * 60)
        print(f"#  FILE {i}/{len(json_files)} — {fname}")
        print("#" * 60)

        input_path  = os.path.join(INPUT_DIR, fname)
        output_path = os.path.join(OUTPUT_DIR, fname)

        try:
            stats = clean_file(input_path, output_path)
            all_stats.append(stats)
        except Exception as e:
            print(f"  [ERROR] Failed to clean {fname}: {e}")
        print()

    # ── Overall summary ────────────────────────────────────────────────────────
    print("═" * 60)
    print("  ✅  ALL FILES CLEANED")
    print("═" * 60)
    for s in all_stats:
        print(f"  {s['file']}")
        print(f"      original {s['original']:,} → clean {s['cleaned']:,} "
              f"(removed {s['total_removed']:,}: "
              f"{s['removed_dupes']:,} dupes, {s['removed_subcat']:,} subcat, "
              f"{s['removed_url']:,} dead URL)")
    print("─" * 60)
    print(f"  Files cleaned : {len(all_stats):,}")
    print(f"  Total kept    : {sum(s['cleaned'] for s in all_stats):,}")
    print(f"  Total removed : {sum(s['total_removed'] for s in all_stats):,}")
    print(f"  Output folder : {OUTPUT_DIR}")
    print("═" * 60)


if __name__ == "__main__":
    main()