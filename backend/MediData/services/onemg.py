import re
import requests
from django.core.cache import cache

session = requests.Session()


def _clean_price(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^\d.]", "", str(val))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def search_onemg(medicine_name):
    if not medicine_name:
        return None

    cleaned_name = medicine_name.strip()
    safe_key_name = re.sub(r"[^a-zA-Z0-9_-]", "_", cleaned_name.lower())
    cache_key = f"onemg_{safe_key_name}"


    # Safe cache check
    try:
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
    except Exception as e:
        # Cache backend offline/error - proceed with live request
        pass

    url = "https://www.1mg.com/pwa-api/api/v4/search/all"

    params = {
        "q": cleaned_name,
        "city": "Gurgaon",
        "page_number": 0,
        "per_page": 10,
        "types": "sku,allopathy"
    }

    headers = {
        "X-1mgLabs-Platform": "mWeb",
        "X-Access-Key": "1mg_client_access_key",
        "Accept": "application/vnd.healthkartplus.v4+json",
        "X-City": "Gurgaon",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        r = session.get(
            url,
            params=params,
            headers=headers,
            timeout=(3, 6)
        )
        r.raise_for_status()

        data = r.json()
        results = data.get("data", {}).get("search_results", [])

        if not results:
            return None

        first = results[0]
        prices = first.get("prices", {}) or {}

        price = prices.get("discounted_price")
        if price is None or str(price).lower() == "nan":
            price = prices.get("mrp")

        numeric_price = _clean_price(price)
        numeric_mrp = _clean_price(prices.get("mrp"))

        result = {
            "platform": "1mg",
            "name": first.get("name", cleaned_name),
            "mrp": prices.get("mrp"),
            "price": price,
            "numeric_price": numeric_price,
            "numeric_mrp": numeric_mrp,
            "available": bool(numeric_price is not None and numeric_price > 0),
        }

        # Safe cache store (24 hours)
        try:
            cache.set(cache_key, result, timeout=60 * 60 * 24)
        except Exception:
            pass

        return result

    except Exception as e:
        print(f"1mg API Lookup notice: {e}")
        return None