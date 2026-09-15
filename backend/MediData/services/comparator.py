import re

def clean_price(price):

    if not price:
        return None

    if isinstance(price, (int, float)):
        return float(price)

    price = re.sub(r"[^\d.]", "", str(price))

    try:
        return float(price)
    except:
        return None


def compare_prices(apollo_result, onemg_result):

    candidates = []

    if apollo_result:
        apollo_result["numeric_price"] = clean_price(
            apollo_result.get("price")
        )

        if apollo_result["numeric_price"]:
            candidates.append(apollo_result)

    if onemg_result:
        onemg_result["numeric_price"] = clean_price(
            onemg_result.get("price")
        )

        if onemg_result["numeric_price"]:
            candidates.append(onemg_result)

    if not candidates:
        return None

    cheapest = min(
        candidates,
        key=lambda x: x["numeric_price"]
    )

    return {
        "apollo": apollo_result,
        "onemg": onemg_result,
        "best_option": {
            "platform": cheapest["platform"],
            "price": cheapest["numeric_price"]
        }
    }