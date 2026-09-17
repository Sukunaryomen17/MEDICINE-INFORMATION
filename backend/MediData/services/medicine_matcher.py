"""
Brand-first medicine matching.

Why not fuzzy-match the whole name
----------------------------------
Bill lines and dataset names are mostly "<brand> <strength> <form>", and a
plain WRatio over that whole string is dominated by the strength digits. That
is fatal here because strengths are not distinctive: 247 different brands in
this dataset carry the token "40" and 232 carry "500". Measured on 400
perturbed real names the old approach matched 15.2% correctly and returned a
*different drug* 44.2% of the time -- every one of them scoring 85.5, the
value WRatio returns for a broad class of partial matches, which is why a
threshold of 80 let them all through.

So the name is split instead. The alphabetic brand core decides identity, the
strength only confirms or contradicts it, and the dosage form is discarded.
A query whose brand core does not match anything is answered with None, on
the principle that no clinical information beats another drug's.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz, process, utils

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", "datasets", "Medicine_Details.csv"))

# Dosage forms and packaging: present in both bill lines and dataset names,
# and identical across thousands of different drugs, so they carry no identity.
FORM_WORDS = {
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps",
    "injection", "inj", "syrup", "syp", "suspension", "susp", "cream", "gel",
    "drop", "drops", "ointment", "oint", "solution", "soln", "powder",
    "infusion", "lotion", "spray", "inhaler", "sachet", "kit", "respules",
    "mouth", "paint", "granules", "rotacaps", "vial", "ampoule", "strip",
}

# Words that are part of the brand and DO distinguish products, so they stay:
# sr, pr, er, xr, mr, ds, cv, cd, forte, plus, gold, advance, total, duo...

QUANTITY_PATTERNS = [
    r"\b\d+\s*x\s*\d+\b",          # 1X10
    r"\b\d+\s*'?s\b",              # 10S, 10'S
    r"\b\d+\s*(?:tab|tabs|strip|strips|nos|no|pcs|pc|unit|units)\b",
    r"\bq(?:ty|uantity)\s*[:.]?\s*\d+\b",
]

STRENGTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|gm|g|ml|iu|%)?", re.I)
NON_ALNUM = re.compile(r"[^a-z0-9.\s]+")

# Administrative and billing vocabulary. A line built only from these is not a
# medicine however well it fuzzy-matches: "GST 12%" scored 85.5 against
# "Dersol 12% Ointment" under the old matcher.
BILLING_STOPWORDS = {
    "gst", "cgst", "sgst", "igst", "vat", "tax", "discount", "round", "off",
    "advance", "paid", "total", "payable", "balance", "due", "charge",
    "charges", "fee", "fees", "amount", "subtotal", "net", "gross", "bill",
    "payment", "card", "cash", "credit", "debit", "service", "processing",
    "registration", "misc", "miscellaneous", "rent", "room", "ward", "bed",
    "nursing", "doctor", "visit", "consultation", "icu", "ot", "anesthesia",
    "ambulance", "diet", "oxygen", "physiotherapy", "dialysis", "transfusion",
}


def _strip_quantities(text: str) -> str:
    for pattern in QUANTITY_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    return text


def normalise(text: str) -> str:
    """Lowercase, drop punctuation and packaging noise, collapse whitespace."""
    text = str(text or "").lower().replace("-", " ").replace("/", " ")
    text = _strip_quantities(text)
    # Keep dots only between digits (strengths like 2.6); "TAB." must reduce to
    # "tab" so it is recognised as a dosage form rather than a brand word.
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    text = NON_ALNUM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_name(text: str) -> Tuple[str, frozenset]:
    """
    Return (brand core, strengths).

    The core keeps alphabetic brand words in order, dropping dosage forms. The
    strengths are the bare numbers, which confirm a match but never drive it.
    """
    normalised = normalise(text)
    strengths = {float(m.group(1)) for m in STRENGTH_RE.finditer(normalised) if m.group(1)}
    words = [
        w for w in normalised.split()
        if w not in FORM_WORDS and not any(ch.isdigit() for ch in w)
    ]
    return " ".join(words), frozenset(strengths)


def looks_like_billing_line(core: str) -> bool:
    words = [w for w in core.split() if w]
    return bool(words) and all(w in BILLING_STOPWORDS for w in words)


class MedicineIndex:
    """Dataset rows indexed by brand core and by composition molecule."""

    def __init__(self, dataset_path: str = DATASET_PATH):
        self.rows: List[dict] = []
        self.cores: List[str] = []
        self.strengths: List[frozenset] = []
        self.by_name: Dict[str, dict] = {}
        self.by_core: Dict[str, List[int]] = {}
        self.molecules: List[str] = []
        self.molecule_rows: Dict[str, List[int]] = {}
        self._load(dataset_path)

    def _load(self, dataset_path: str) -> None:
        if not os.path.exists(dataset_path):
            return
        columns = ["Medicine Name", "Composition", "Uses", "Side_effects",
                   "Image URL", "Manufacturer", "Excellent Review %",
                   "Average Review %", "Poor Review %"]
        frame = pd.read_csv(dataset_path).fillna("")
        if "Medicine Name" not in frame.columns:
            return
        frame = frame.reindex(columns=columns, fill_value="")
        for column in columns:
            frame[column] = frame[column].astype(str).str.strip()

        for record in frame.to_dict("records"):
            name = record["Medicine Name"]
            if not name or name in self.by_name:
                continue
            entry = {
                "name": name,
                "composition": record.get("Composition", ""),
                "uses": record.get("Uses", ""),
                "side_effects": record.get("Side_effects", ""),
                "image_url": record.get("Image URL", ""),
                "manufacturer": record.get("Manufacturer", ""),
                "excellent_review": record.get("Excellent Review %", ""),
                "average_review": record.get("Average Review %", ""),
                "poor_review": record.get("Poor Review %", ""),
            }
            index = len(self.rows)
            core, strengths = split_name(name)
            self.rows.append(entry)
            self.cores.append(core)
            self.strengths.append(strengths)
            self.by_name[name] = entry
            self.by_core.setdefault(core, []).append(index)

            for molecule in self._molecules(entry["composition"]):
                if molecule not in self.molecule_rows:
                    self.molecule_rows[molecule] = []
                    self.molecules.append(molecule)
                self.molecule_rows[molecule].append(index)

    @staticmethod
    def _molecules(composition: str) -> List[str]:
        """'Amoxycillin (500mg) + Clavulanic Acid (125mg)' -> both molecules."""
        parts = re.split(r"[+,]", str(composition or ""))
        out = []
        for part in parts:
            molecule = normalise(re.sub(r"\(.*?\)", " ", part))
            molecule = " ".join(w for w in molecule.split() if not any(c.isdigit() for c in w))
            if len(molecule) >= 4:
                out.append(molecule)
        return out

    def molecule_count(self, row_index: int) -> int:
        return max(1, len(self._molecules(self.rows[row_index].get("composition", ""))))

    def __len__(self) -> int:
        return len(self.rows)


_INDEX: Optional[MedicineIndex] = None

# A brand core must reach this before its clinical data is shown. Set high
# deliberately: the cost of a wrong molecule's side-effect profile is far worse
# than the cost of showing nothing.
BRAND_MIN_SCORE = float(os.getenv("MEDICINE_BRAND_MIN_SCORE", "88"))
# Contradicted strengths subtract this. Same brand core, wrong strength is
# usually a different pack of the right drug, so it is a demotion not a veto.
STRENGTH_PENALTY = float(os.getenv("MEDICINE_STRENGTH_PENALTY", "12"))
STRENGTH_BONUS = 4.0
CANDIDATE_DEPTH = 25

# token_set_ratio returns 100 whenever the candidate's tokens are a subset of
# the query's, so a two-letter brand scores perfectly against any line that
# happens to contain it -- "X-RAY CHEST PA VIEW" matched "PA 650mg Tablet".
# token_sort_ratio separates the two cleanly: real prefix matches stay above 55
# ("crocin" vs "crocin advance" is 60) while spurious containment collapses
# ("x ray chest pa view" vs "pa" is 19). Used as a floor, not as the score.
MIN_COVERAGE = float(os.getenv("MEDICINE_MIN_COVERAGE", "55"))


def get_index() -> MedicineIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = MedicineIndex()
    return _INDEX


def _result(entry: dict, score: float) -> dict:
    return {
        "matched_name": entry["name"],
        "composition": entry.get("composition", ""),
        "uses": entry.get("uses", ""),
        "side_effects": entry.get("side_effects", ""),
        "manufacturer": entry.get("manufacturer", ""),
        "image_url": entry.get("image_url", ""),
        "match_score": round(score, 1),
    }


def _score_candidates(index: MedicineIndex, candidates, q_strengths,
                      prefer_simple: bool = False) -> Optional[Tuple[int, float]]:
    """
    Rank candidate rows, letting strength confirm or contradict the brand.

    prefer_simple breaks ties toward products with fewer molecules. A bill line
    reading "Diclofenac 50" should land on a diclofenac product, not on a
    three-drug combination that merely contains diclofenac.
    """
    best = None
    best_key = None
    for row_index, core_score in candidates:
        score = core_score
        c_strengths = index.strengths[row_index]
        if q_strengths and c_strengths:
            if q_strengths & c_strengths:
                score = min(100.0, score + STRENGTH_BONUS)
            else:
                score -= STRENGTH_PENALTY
        elif q_strengths and not c_strengths:
            score -= STRENGTH_PENALTY / 2

        key = (score, -index.molecule_count(row_index)) if prefer_simple else (score,)
        if best_key is None or key > best_key:
            best, best_key = (row_index, score), key
    return best


def _brand_match(index: MedicineIndex, core: str, q_strengths) -> Optional[Tuple[int, float]]:
    if not core:
        return None

    # Exact-core rows are seeded at 100 but do NOT short-circuit: scoring them
    # together with the fuzzy candidates lets strength decide between them.
    # "Augmentin 625" has core "augmentin", which matches "Augmentin 1.2gm
    # Injection" exactly while the product actually wanted, "Augmentin 625 Duo
    # Tablet", has core "augmentin duo". Returning early handed back the
    # injection on a strength that plainly contradicted it.
    candidates = [(i, 100.0) for i in index.by_core.get(core, [])]

    hits = process.extract(
        core, index.cores, scorer=fuzz.token_set_ratio,
        processor=utils.default_process, limit=CANDIDATE_DEPTH,
    )
    seen = {i for i, _ in candidates}
    candidates += [
        (row_index, score) for _, score, row_index in hits
        if row_index not in seen
        and score >= BRAND_MIN_SCORE
        and fuzz.token_sort_ratio(core, index.cores[row_index],
                                  processor=utils.default_process) >= MIN_COVERAGE
    ]
    if not candidates:
        return None
    return _score_candidates(index, candidates, q_strengths)


def _molecule_match(index: MedicineIndex, core: str, q_strengths) -> Optional[Tuple[int, float]]:
    """
    Generic fallback: bills often name the molecule, not a brand.

    "TAB. PARACETAMOL 500MG" has no brand to find, but the composition column
    does contain paracetamol. Scored below a brand hit because a molecule
    identifies the drug without identifying the product.
    """
    if not core or not index.molecules:
        return None
    hit = process.extractOne(
        core, index.molecules, scorer=fuzz.token_set_ratio,
        processor=utils.default_process,
    )
    if not hit or hit[1] < BRAND_MIN_SCORE:
        return None
    rows = index.molecule_rows.get(index.molecules[hit[2]], [])
    if not rows:
        return None
    scored = _score_candidates(
        index, [(i, float(hit[1])) for i in rows], q_strengths, prefer_simple=True,
    )
    if scored is None:
        return None
    return scored[0], min(scored[1], 95.0)


def find_medicine_details(medicine_name, min_score: float = BRAND_MIN_SCORE) -> Optional[dict]:
    """Identify a bill line. Returns None rather than a plausible wrong drug."""
    index = get_index()
    if not medicine_name or not len(index):
        return None

    core, q_strengths = split_name(medicine_name)
    if not core or looks_like_billing_line(core):
        return None

    # Both paths are scored and the stronger wins. Running the molecule path
    # only when the brand path fails was wrong: a brand hit whose strength is
    # contradicted still clears the bar, so "TAB. PARACETAMOL 500MG" settled
    # for a diclofenac combination at 88 while a plain paracetamol 500 product
    # was sitting in the composition index.
    best = _brand_match(index, core, q_strengths)
    molecule = _molecule_match(index, core, q_strengths)
    if molecule and (best is None or molecule[1] > best[1]):
        best = molecule

    if best is None or best[1] < min_score:
        return None
    return _result(index.rows[best[0]], best[1])


def get_medicine_by_name(name) -> Optional[dict]:
    index = get_index()
    if not name:
        return None
    name = str(name).strip()
    if name in index.by_name:
        return index.by_name[name]
    match = find_medicine_details(name)
    return index.by_name.get(match["matched_name"]) if match else None


def search_medicines(query="", limit=12) -> List[dict]:
    index = get_index()
    if not len(index):
        return []
    q = str(query or "").strip().lower()
    if not q:
        return index.rows[:limit]

    prefix, contains, composition = [], [], []
    for entry in index.rows:
        name = entry["name"].lower()
        if name.startswith(q):
            prefix.append(entry)
            if len(prefix) >= limit:
                return prefix[:limit]
        elif q in name:
            contains.append(entry)
        elif q in entry["composition"].lower() or q in entry["uses"].lower():
            composition.append(entry)

    combined = prefix + contains + composition
    if len(combined) >= limit:
        return combined[:limit]

    seen = {e["name"] for e in combined}
    for _, score, row_index in process.extract(
        q, index.cores, scorer=fuzz.token_set_ratio,
        processor=utils.default_process, limit=limit,
    ):
        entry = index.rows[row_index]
        if score >= 75 and entry["name"] not in seen:
            combined.append(entry)
            seen.add(entry["name"])
        if len(combined) >= limit:
            break
    return combined[:limit]
