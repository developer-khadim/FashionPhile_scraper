"""
================================================================================
  FASHIONPHILE.COM — Professional Scraper  v3.8 (Anti-Rate-Limit Fix)
  Features:
  - Fixed 429 Errors by reducing request size and adding pre-flight cookies
  - Correctly implements max_pages variable
  - Extracts specific subcategories (Clutch, Tote, etc.)
  - Extracts Hardware, Exterior, Interior from metafields
================================================================================
"""

import os
import re
import time
import json
import random
import logging
from typing import Optional, Any, Dict, List
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fashionphile")

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

output_dir= "./output_data"

BASE_URL = "https://www.fashionphile.com"

HANDBAG_TYPES = {
    "handbag", "bags", "shoulder bag", "crossbody", "tote", "clutch", 
    "satchel", "bucket bag", "hobo", "backpack", "belt bag", 
    "evening bag", "top handle", "phone holder", "wallet on chain", "woc",
    "flap bag", "messenger bag", "doctor bag", "duffle", "weekender"
}

EXCLUDED_TYPES = {
    "jewelry", "watch", "shoes", "sunglasses", "belt", "scarf", 
    "hat", "wallet", "card holder", "key holder", "bracelet", 
    "necklace", "earring", "ring", "brooch", "cufflink", "tie",
    "cologne", "perfume", "makeup", "cosmetic", "sunglass"
}

CONDITION_ID_TO_NAME = {
    0: "Flawed", 1: "Fair", 2: "Worn", 3: "Shows Wear",
    4: "Excellent", 5: "New", 6: "Giftable"
}

CONDITION_NAME_TO_ID = {
    "flawed": 0, "fair": 1, "worn": 2, "shows wear": 3, "shows_wear": 3,
    "excellent": 4, "new": 5, "giftable": 6, "gift": 6
}

CONDITION_DESCRIPTIONS = {
    "Giftable": {"id": 6, "name": "Giftable", "description": "Item is in New condition and includes one or more of the following: the original box, case, attached retailer tags."},
    "New": {"id": 5, "name": "New", "description": "Item appears unused. May contain faint signs of wear due to storage conditions."},
    "Excellent": {"id": 4, "name": "Excellent", "description": "Item is clean and contains very little wear. Any notable flaws or signs of wear are stated in the listing."},
    "Shows Wear": {"id": 3, "name": "Shows Wear", "description": "Item shows some wear and signs of previous use, but still has a lot of life in it."},
    "Worn": {"id": 2, "name": "Worn", "description": "Item does show moderate signs of prior use. Surface scratches, slight darkening in handles, and other indications of wear may be visible."},
    "Fair": {"id": 1, "name": "Fair", "description": "Item will have noticeable signs of wear such as well scuffed edges or significant scratches."},
    "Flawed": {"id": 0, "name": "Flawed", "description": "Item is generally in nice condition overall, but has a major defect or flaw that affects the item's appearance or functionality."}
}

def get_condition_name(condition_id: int) -> str:
    return CONDITION_ID_TO_NAME.get(condition_id, "Unknown")

def get_condition_id(condition_name: str) -> int:
    return CONDITION_NAME_TO_ID.get(condition_name.lower(), 4)

# ══════════════════════════════════════════════════════════════════════════════
#  SESSION (Enhanced Anti-Rate-Limit)
# ══════════════════════════════════════════════════════════════════════════════

def build_session():
    session = requests.Session()
    # Increased backoff_factor and total retries for 429 errors
    retry = Retry(
        total=5, 
        backoff_factor=2, 
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session

# ══════════════════════════════════════════════════════════════════════════════
#  SUBCATEGORY HELPER
# ══════════════════════════════════════════════════════════════════════════════

def get_specific_subcategory(title: str) -> str:
    title_lower = title.lower()
    sorted_types = sorted(list(HANDBAG_TYPES), key=len, reverse=True)
    
    for bag_type in sorted_types:
        if bag_type in ("bags", "handbag"):
            continue
        if bag_type in title_lower:
            return bag_type
            
    if "bag" in title_lower or "tote" in title_lower:
        return "handbag"
    return "handbag"

# ══════════════════════════════════════════════════════════════════════════════
#  PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def is_handbag(product_data: dict) -> bool:
    product_type = product_data.get("product_type", "").lower()
    title = product_data.get("title", "").lower()
    tags = [t.lower() for t in product_data.get("tags", [])]
    
    for excluded in EXCLUDED_TYPES:
        if excluded in product_type or excluded in title:
            return False
        if excluded in tags:
            return False
    
    for bag_type in HANDBAG_TYPES:
        if bag_type in product_type or bag_type in title:
            return True
            
    handbag_tags = {"bag", "handbag", "purse", "tote", "satchel", "crossbody"}
    if any(tag in handbag_tags for tag in tags):
        return True
    return False

def extract_condition_enhanced(soup: BeautifulSoup) -> tuple:
    condition_id = 4
    condition_name = "Excellent"
    if not soup:
        return condition_id, condition_name

    full_text = soup.get_text(separator=" ", strip=True)
    sentence_match = re.search(r"This product'?s condition is [\"']([^\"']+)[\"']", full_text, re.IGNORECASE)
    if sentence_match:
        found_name = sentence_match.group(1).strip()
        found_lower = found_name.lower()
        if found_lower in CONDITION_NAME_TO_ID:
            condition_id = CONDITION_NAME_TO_ID[found_lower]
            condition_name = get_condition_name(condition_id)
            return condition_id, condition_name

    elem = soup.select_one("[data-condition]")
    if elem:
        val = elem.get("data-condition", "").strip().lower()
        if val in CONDITION_NAME_TO_ID:
            condition_id = CONDITION_NAME_TO_ID[val]
            condition_name = get_condition_name(condition_id)
            return condition_id, condition_name

    return condition_id, condition_name

def parse_product_page(soup: BeautifulSoup) -> dict:
    data = {
        "specs": {},
        "dims": None,
        "color": None,
        "item_number": None,
        "condition_id": 4,
        "condition_name": "Excellent"
    }

    if not soup:
        return data

    cond_id, cond_name = extract_condition_enhanced(soup)
    data["condition_id"] = cond_id
    data["condition_name"] = cond_name

    # Debug: print page title for verification
    title_elem = soup.select_one("h1.product__title")
    if title_elem:
        log.info(f"  Parsing page: {title_elem.get_text(strip=True)[:80]}")

    # Extract Specs from Metafield - try multiple patterns
    metafield_elems = soup.select("span.metafield-multi_line_text_field, .metafield-multi_line_text_field, [class*='metafield']")
    log.info(f"  Found {len(metafield_elems)} metafield elements")
    for elem in metafield_elems:
        text_content = elem.get_text(separator="\n", strip=True)
        lines = text_content.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Try both ": " and "=" separators
            if ": " in line:
                key, val = line.split(": ", 1)
            elif "=" in line:
                key, val = line.split("=", 1)
            else:
                continue
            key_lower = key.lower().strip()
            val = val.strip()

            if key_lower == "hardware":
                data["specs"]["hardware"] = val
                log.info(f"  Found hardware: {val}")
            elif key_lower in ("exterior", "exterior material"):
                data["specs"]["exterior_material"] = val
                log.info(f"  Found exterior: {val}")
            elif key_lower in ("interior", "interior material"):
                data["specs"]["interior_material"] = val
                log.info(f"  Found interior: {val}")
            elif key_lower == "origin":
                data["specs"]["origin"] = val
                log.info(f"  Found origin: {val}")
            elif key_lower in ("includes", "comes with", "includes:"):
                data["specs"]["includes"] = val
                log.info(f"  Found includes: {val}")

    # Also check p tags with strong for "Comes With"
    comes_with_elems = soup.select("p strong, .product-description p strong")
    for elem in comes_with_elems:
        elem_text = elem.get_text(strip=True).lower()
        if "comes with" in elem_text or "includes" in elem_text:
            parent = elem.find_parent(["p", "div"])
            if parent:
                parent_text = parent.get_text()
                log.info(f"  Comes with parent text: {parent_text[:100]}")
                match = re.search(r"(?:comes with|includes)\s*:?\s*(.+?)(?:\.|$)", parent_text, re.IGNORECASE)
                if match:
                    data["specs"]["includes"] = match.group(1).strip()
            break

    # Extract Dimensions from metafield-multi_line_text_field (Fashionphile format)
    # This format uses <br /> separated lines like "Base length: 6.5 in"
    metafield_dims = soup.select("span.metafield-multi_line_text_field")
    dims = {}
    for elem in metafield_dims:
        text_content = elem.get_text(separator="\n", strip=True)
        lines = text_content.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Match patterns like "Base length: 6.5 in" or "Drop: 21.5 in"
            dim_match = re.match(r"^(Base length|Length|Width|Height|Depth|Drop|Handle drop|Strap drop)\s*:\s*(\d+\.?\d*)\s*(in|cm|inches)?", line, re.IGNORECASE)
            if dim_match:
                dim_type = dim_match.group(1).lower().strip()
                value = dim_match.group(2)
                unit = dim_match.group(3) or "in"

                # Normalize dim_type names
                if dim_type in ("base length", "length"):
                    dim_type = "length"
                elif dim_type in ("handle drop", "strap drop"):
                    dim_type = "drop"

                # Convert to cm if needed
                if unit.lower() in ("in", "inches"):
                    value_cm = round(float(value) * 2.54, 1)
                    dims[dim_type] = f"{value_cm} cm"
                else:
                    dims[dim_type] = f"{value} cm"

                log.info(f"  Found dimension: {dim_type} = {dims[dim_type]}")

    data["dims"] = dims if dims else None

    # Get full_text for remaining extractions (item number, color)
    full_text = soup.get_text(separator="\n", strip=True)

    # Extract Item Number
    item_match = re.search(r"Item\s*(?:#|Number)\s*:?\s*(\d+)", full_text, re.IGNORECASE)
    if item_match:
        data["item_number"] = item_match.group(1)
        log.info(f"  Found item number: {data['item_number']}")

    # Extract Subcategory from breadcrumb
    breadcrumb_links = soup.select('.breadcrumb a, .breadcrumbs a, [class*="breadcrumb"] a, nav a')
    subcategory = None
    skip_handles = {'all-bags', 'all', 'shop-all', 'designers', 'brands'}
    skip_texts = {'home', 'all', 'shop all bags', 'shop all'}
    for link in reversed(breadcrumb_links):
        href = link.get('href', '')
        text = link.get_text(strip=True)
        handle = href.split('/collections/')[-1].split('?')[0].lower() if '/collections/' in href else ''
        if handle in skip_handles:
            continue
        if text.lower() in skip_texts:
            continue
        if text and len(text) > 2:
            subcategory = text
            break
    data["subcategory"] = subcategory

    # Extract Color from title and description
    if title_elem:
        title_text = title_elem.get_text(strip=True)
        # Extended color list - try multi-word colors first (sorted by length)
        multi_word_colors = ['Milky Orange', 'Light Grey', 'Light Gray', 'Dark Grey', 'Dark Gray', 'Antique Yellow', 'Regency Blue', 'Mid Camel', 'Soft Violet', 'Dark Birch', 'Charcoal Grey', 'Person Brick']
        for mc in multi_word_colors:
            if title_text.lower().endswith(mc.lower()):
                data["color"] = mc.title()
                log.info(f"  Found multi-word color from title: {data['color']}")
                break

        if not data.get("color"):
            color_match = re.search(
                r"\b(Black|White|Red|Blue|Green|Yellow|Pink|Purple|Brown|Beige|Navy|Grey|Gray|Silver|Gold|Rose|Cream|Ivory|Tan|Burgundy|Olive|Teal|Lavender|Coral|Peach|Neutral|Cognac|Khaki|Charcoal|Tangerine|Orange|Lemon|Lime|Turquoise|Celadon|Coquelicot|Powder|Pearl|Nino|Bronze|Camel|Antarctic|Grege|Hortensia)\s*$",
                title_text, re.IGNORECASE
            )
            if color_match:
                data["color"] = color_match.group(1).title()
                log.info(f"  Found color from title: {data['color']}")

    # Also extract "in [color]" pattern from description
    if not data.get("color"):
        color_list = ['Black','White','Red','Blue','Green','Yellow','Pink','Purple','Brown','Beige','Navy',
                      'Grey','Gray','Silver','Gold','Rose','Cream','Ivory','Tan','Burgundy','Olive',
                      'Teal','Lavender','Coral','Peach','Neutral','Cognac','Khaki','Charcoal',
                      'Tangerine','Orange','Lemon','Lime','Turquoise','Celadon','Coquelicot','Powder',
                      'Pearl','Bronze','Camel','Antarctic','Grege','Hortensia','Milky','Orange']
        in_color_pattern = r'\bin\s+(' + '|'.join(color_list) + r')\b'
        desc_match = re.search(in_color_pattern, full_text, re.IGNORECASE)
        if desc_match:
            data["color"] = desc_match.group(1).title()
            log.info(f"  Found color from description: {data['color']}")

    return data

# ══════════════════════════════════════════════════════════════════════════════
#  LISTING FETCHER (Rate Limit Safe)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_listing_smart(session, start_url, desired_brand, max_pages):
    parsed = urlparse(start_url)
    path_parts = [p for p in parsed.path.split('/') if p]
    collection_handle = "all-bags"

    if "collections" in path_parts:
        idx = path_parts.index("collections")
        if len(path_parts) > idx + 1:
            collection_handle = path_parts[idx + 1]

    url_page = 1
    qs = parse_qs(parsed.query)
    if 'page' in qs:
        try:
            url_page = int(qs['page'][0])
        except (ValueError, IndexError):
            url_page = 1
    start_page_num = max(1, url_page)

    if desired_brand:
        api_url = f"{BASE_URL}/collections/{desired_brand.lower().replace(' ', '-')}/products.json"
        log.info(f"Using brand collection: {api_url}")
    else:
        api_url = f"{BASE_URL}/collections/{collection_handle}/products.json"
        log.info(f"Using original collection: {api_url}")

    all_products = []
    page = start_page_num
    
    # Calculate end page
    if max_pages in (0, None):
        end_page = 999999
        log.info("Auto-detect mode: will fetch all pages")
    else:
        end_page = start_page_num + max_pages - 1
        log.info(f"Target: Fetching {max_pages} pages (from page {start_page_num} to {end_page})")

    while page <= end_page:
        # 2. REDUCED LIMIT: 50 instead of 250 to avoid size-based blocking
        params = {"limit": 50, "page": page}
        log.info(f"Fetching page {page}...")
        
        try:
            # Increased timeout
            resp = session.get(api_url, params=params, timeout=30)
            
            # Handle 429 manually if retries fail
            if resp.status_code == 429:
                log.warning("Rate limit hit (429). Sleeping for 60 seconds...")
                time.sleep(60)
                continue # Retry this page

            if resp.status_code == 404:
                log.error(f"Collection not found: {api_url}")
                break

            raw_batch = resp.json().get("products", [])
            if not raw_batch:
                log.info(f"Page {page}: no products returned, stopping")
                break

            batch = raw_batch
            filtered = [p for p in batch if is_handbag(p)]

            all_products.extend(filtered)
            log.info(f"Page {page}: {len(raw_batch)} raw, {len(filtered)} handbags, Total: {len(all_products)}")

            # Check if we reached the end (API returns less than requested limit)
            if len(raw_batch) < 50:
                log.info(f"Page {page}: less than 50 products, reached end of collection")
                break
                
            page += 1
            
            # 3. RANDOM DELAY: Sleep between 2 and 4 seconds between pages (reduced from 3-6)
            sleep_time = random.uniform(2.0, 4.0)
            log.info(f"Sleeping for {sleep_time:.1f}s to avoid rate limit...")
            time.sleep(sleep_time)

        except Exception as e:
            log.error(f"Error fetching page {page}: {e}")
            break

    return all_products

# ══════════════════════════════════════════════════════════════════════════════
#  WORKER
# ══════════════════════════════════════════════════════════════════════════════

def process_product(product_data, session, index, total):
    handle = product_data.get("handle")
    brand = product_data.get("vendor", "Unknown")
    title = product_data.get("title", "Unknown")
    product_url = f"{BASE_URL}/products/{handle}"
    
    print(f"[{index}/{total}] Scraping: {title} ({brand})...")
    
    soup = None
    try:
        resp = session.get(product_url, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
        # Increased delay for complete data extraction
        time.sleep(random.uniform(1.0, 2.0))
    except Exception as e:
        log.error(f"Error fetching {product_url}: {e}")

    # Extract condition from API data first
    condition_id_api = None
    condition_name_api = None

    api_tags = [t.lower().strip() for t in product_data.get("tags", [])]
    for tag in api_tags:
        clean_tag = tag.replace("condition:", "").replace("condition-", "").strip()
        if clean_tag in CONDITION_NAME_TO_ID:
            condition_id_api = CONDITION_NAME_TO_ID[clean_tag]
            condition_name_api = get_condition_name(condition_id_api)
            break

    parsed_data = parse_product_page(soup)

    if condition_id_api is not None:
        condition_id = condition_id_api
        condition_name = condition_name_api
    else:
        condition_id = parsed_data.get("condition_id", 4)
        condition_name = parsed_data.get("condition_name", "Excellent")
    
    variants = product_data.get("variants", [])
    images = product_data.get("images", [])

    price = "0"
    if variants:
        price = str(variants[0].get("price", "0"))
        if len(price) > 2 and price.isdigit():
            price = f"{int(price) / 100:.2f}"

    img_urls = [re.sub(r'\?v=\d+$', '', img.get("src")) for img in images if img.get("src")]
    body_html = product_data.get("body_html", "")
    clean_desc = BeautifulSoup(body_html, "lxml").get_text(separator=" ", strip=True)

    specs = parsed_data["specs"]
    condition_desc_text = CONDITION_DESCRIPTIONS.get(condition_name, {}).get("description", "")
    condition_description = {"description": condition_desc_text}

    # Log extracted data for debugging
    log.info(f"  Extracted specs: hardware={specs.get('hardware')}, exterior={specs.get('exterior_material')}, interior={specs.get('interior_material')}")
    log.info(f"  Extracted dims: {parsed_data.get('dims')}, color: {parsed_data.get('color')}")
    log.info(f"  Extracted subcategory: {parsed_data.get('subcategory')}")

    # Extract Material
    actual_material = None
    material_patterns = [
        r'(?:crafted|made)\s+(?:of\s+)?(\w+(?:\s+\w+)?\s+leather)',
        r'(\w+(?:\s+\w+)? leather)',
    ]
    for pat in material_patterns:
        match = re.search(pat, clean_desc, re.IGNORECASE)
        if match:
            actual_material = match.group(1).strip()
            break
            
    subcategory = parsed_data.get("subcategory") or get_specific_subcategory(title)

    prod_desc = {
        "material": actual_material,
        "hardware": specs.get("hardware"),
        "Exterior": specs.get("exterior_material"),
        "Interior": specs.get("interior_material"),
        "color": parsed_data.get("color"),
        "origin": specs.get("origin"),
        "includes": specs.get("includes"),
        "item_number": parsed_data.get("item_number") or str(product_data.get("id", "")),
        "description": clean_desc if clean_desc else "No description available"
    }
    
    gender = "Women"
    title_lower = title.lower()
    if re.search(r"\bmen\b", title_lower):
        gender = "Men"

    result = {
        "category": product_data.get("product_type", "bags").lower(),
        "subcategory": subcategory,
        "brand": brand,
        "model_title": title,
        "gender": gender,
        "product_description": prod_desc,
        "size": None,
        "dims": parsed_data.get("dims"),
        "condition": condition_id,
        "condition_description": condition_description,
        "url": product_url,
        "shop": "Fashionphile",
        "price": price,
        "currency": "USD",
        "sold": not any(v.get("available", True) for v in variants),
        "image_urls": img_urls,
        "main_image_url": None
    }
    
    print(f"  - Completed: {title[:60]}... - Condition: {condition_name}")
    
    return result

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def scrape_fashionphile(run_url: str, output_json: str = "handbags_data.json", max_pages: int = 0):
    session = build_session()
    
    parsed = urlparse(run_url)
    qs = parse_qs(parsed.query)
    brand_filter = None
    for k, v in qs.items():
        if 'vendor' in k.lower():
            brand_filter = v[0]
            break
    
    print("=" * 70)
    print("  FASHIONPHILE SCRAPER v3.8 - Anti-Rate-Limit Fix")
    print("=" * 70)
    print(f"  Target: {brand_filter if brand_filter else 'All Brands'}")
    print(f"  Max Pages Setting: {max_pages}")
    print("=" * 70)
    
    # Build output filename as brandname_fashionphile.json
    brand_slug = (brand_filter if brand_filter else "all").lower().replace(" ", "_").replace("+", "_")
    output_json = f"{brand_slug}_fashionphile.json"

    products = fetch_listing_smart(session, run_url, brand_filter, max_pages)
    print(f"\nFound {len(products)} handbag products\n")
    
    if not products:
        return []

    results = []
    total = len(products)
    
    # Reduced to 1 worker for complete data extraction
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {}
        for idx, p in enumerate(products, 1):
            future = executor.submit(process_product, p, session, idx, total)
            futures[future] = p
        
        for future in as_completed(futures):
            try:
                rec = future.result()
                results.append(rec)
            except Exception as e:
                log.error(f"Worker error: {e}")
    
    results.sort(key=lambda x: (x.get("brand", ""), x.get("model_title", "")))

    # Ensure the output directory exists and write the file inside it
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, os.path.basename(output_json))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nOutput saved to: {output_path}")
    return results

if __name__ == "__main__":
    results = scrape_fashionphile(
        run_url="https://www.fashionphile.com/collections/all-bags?refinementList%5Bvendor%5D%5B0%5D=MCM&sortBy=shopify_products_published_at_desc",
        max_pages=0
    )