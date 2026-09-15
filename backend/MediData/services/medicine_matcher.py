import os
import pandas as pd
from rapidfuzz import process, fuzz

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_PATH = os.path.abspath(
    os.path.join(
        CURRENT_DIR,
        "..",
        "..",
        "datasets",
        "Medicine_Details.csv"
    )
)

_dataset_loaded = False
_df = None
_medicine_names = []
_medicine_lookup = {}
_medicines_list = []


def _load_dataset():
    global _dataset_loaded, _df, _medicine_names, _medicine_lookup, _medicines_list
    if _dataset_loaded:
        return

    if not os.path.exists(DATASET_PATH):
        print(f"Warning: Dataset not found at {DATASET_PATH}")
        _dataset_loaded = True
        return

    try:
        df = pd.read_csv(DATASET_PATH)
        df = df.fillna("")

        # Normalize known fields once and fill optional columns consistently.
        required_columns = [
            "Medicine Name", "Composition", "Uses", "Side_effects",
            "Image URL", "Manufacturer", "Excellent Review %",
            "Average Review %", "Poor Review %",
        ]
        if "Medicine Name" not in df.columns:
            raise ValueError("Dataset is missing the Medicine Name column")
        df = df.reindex(columns=required_columns, fill_value="")
        for column in required_columns:
            df[column] = df[column].astype(str).str.strip()

        _medicine_names = df["Medicine Name"].tolist()

        lookup = {}
        items_list = []
        for row in df.to_dict("records"):
            name = row["Medicine Name"]
            if not name or name in lookup:
                continue

            entry = {
                "name": name,
                "composition": row.get("Composition", ""),
                "uses": row.get("Uses", ""),
                "side_effects": row.get("Side_effects", ""),
                "image_url": row.get("Image URL", ""),
                "manufacturer": row.get("Manufacturer", ""),
                "excellent_review": row.get("Excellent Review %", ""),
                "average_review": row.get("Average Review %", ""),
                "poor_review": row.get("Poor Review %", ""),
            }
            lookup[name] = entry
            items_list.append(entry)

        _df = df
        _medicine_lookup = lookup
        _medicines_list = items_list
        _dataset_loaded = True
    except Exception as e:
        print(f"Error loading medicine dataset: {e}")
        _dataset_loaded = True


# Initialize on module load
_load_dataset()


def find_medicine_details(medicine_name, min_score=80):
    """
    Fuzzy match a medicine name from a bill against the medicine database.
    """
    _load_dataset()
    if not medicine_name or not _medicine_names:
        return None

    medicine_name = str(medicine_name).strip()

    # Direct exact lookup first
    if medicine_name in _medicine_lookup:
        row = _medicine_lookup[medicine_name]
        return {
            "matched_name": medicine_name,
            "composition": row["composition"],
            "uses": row["uses"],
            "side_effects": row["side_effects"],
            "manufacturer": row["manufacturer"],
            "image_url": row["image_url"],
            "match_score": 100,
        }

    result = process.extractOne(
        medicine_name,
        _medicine_names,
        scorer=fuzz.WRatio
    )

    if not result:
        return None

    match_name, score, _ = result

    if score < min_score:
        return None

    row = _medicine_lookup.get(match_name)
    if not row:
        return None

    return {
        "matched_name": match_name,
        "composition": row.get("composition", ""),
        "uses": row.get("uses", ""),
        "side_effects": row.get("side_effects", ""),
        "manufacturer": row.get("manufacturer", ""),
        "image_url": row.get("image_url", ""),
        "match_score": round(score, 1),
    }


def search_medicines(query="", limit=12):
    """
    Search medicines by query with prefix, substring, and fuzzy matching.
    """
    _load_dataset()
    if not _medicines_list:
        return []

    q = str(query).strip().lower()
    if not q:
        return _medicines_list[:limit]

    # Fast tiered matching
    exact_prefix = []
    contains_name = []
    contains_comp = []

    for item in _medicines_list:
        name_lower = item["name"].lower()
        comp_lower = item["composition"].lower()
        uses_lower = item["uses"].lower()

        if name_lower.startswith(q):
            exact_prefix.append(item)
        elif q in name_lower:
            contains_name.append(item)
        elif q in comp_lower or q in uses_lower:
            contains_comp.append(item)

        if len(exact_prefix) >= limit:
            return exact_prefix[:limit]

    combined = exact_prefix + contains_name + contains_comp
    if len(combined) >= limit:
        return combined[:limit]

    # If few results, supplement with RapidFuzz
    fuzzy_matches = process.extract(
        query,
        _medicine_names,
        scorer=fuzz.WRatio,
        limit=limit
    )

    seen_names = {item["name"] for item in combined}
    for match_name, score, _ in fuzzy_matches:
        if score >= 65 and match_name not in seen_names:
            detail = _medicine_lookup.get(match_name)
            if detail:
                combined.append(detail)
                seen_names.add(match_name)
            if len(combined) >= limit:
                break

    return combined[:limit]


def get_medicine_by_name(name):
    """
    Get full details for an exact or best-match medicine.
    """
    _load_dataset()
    if not name:
        return None

    name = str(name).strip()
    if name in _medicine_lookup:
        return _medicine_lookup[name]

    # Fallback to fuzzy match
    match = find_medicine_details(name, min_score=75)
    if match:
        return _medicine_lookup.get(match["matched_name"])
    return None
