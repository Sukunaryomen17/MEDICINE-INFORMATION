"""
OCR engines behind one interface.

Two engines, chosen per page:

  ppocr      PP-OCRv6 detection + recognition, executed through RapidOCR on
             onnxruntime. Primary engine. Its detector copes with skewed,
             photographed and handwritten pages that Tesseract's line finder
             gives up on.
  tesseract  Fallback, and the only engine when OCR_ENGINE=tesseract. Kept
             because it is cheap, always present in the image, and because its
             per-word confidence is *calibrated* (see OCR_MIN_CONFIDENCE).

Why PP-OCR text is rebuilt into rows
------------------------------------
PP-OCR detects text regions, not lines of a table. On an itemised bill it
returns one detection per *cell*, so joining the detections with newlines --
which is what the obvious implementation does -- shreds

    BLOOD SUGAR BY GLUCOMETER   13/11/25   1 No   80.00   73.60

into five separate lines and destroys the association between an item and its
amount. That association is the single most useful thing the hint can carry.
`rebuild_rows` groups detections back into visual rows using the bounding
boxes the detector already returns, which costs nothing extra and recovers the
table. Measured on the sample bills: 187 detections -> 44 rows on a printed
hospital bill, matching Tesseract's line count while keeping PP-OCR's better
recognition.

Confidence is NOT symmetric between the engines
-----------------------------------------------
Tesseract's mean word confidence tracks page quality well (73.9 / 87.2 / 43.0 /
84.3 across the sample bills, with 43.0 on the page where it collapsed into
noise), so OCR_MIN_CONFIDENCE is a usable gate for it. PP-OCR's recognition
scores do not: it reported 98.7 / 98.6 / 91.2 / 99.2 on the same four pages,
including the one it read poorly. Do not add a mean-score gate to the PP-OCR
path -- it will never fire. The PP-OCR path is gated on *yield* instead
(OCR_MIN_CHARS), which is what actually distinguishes a read page from a
failed one.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ── Configuration ──────────────────────────────────────────────────────────

# Which engine supplies the text hint: "ppocr" (default) or "tesseract".
# "ppocr" still falls back to Tesseract per page when it comes up empty.
OCR_ENGINE = os.getenv("OCR_ENGINE", "ppocr").strip().lower()

# The hint is an accuracy aid, not a dependency -- the model receives the page
# image either way. Set false to skip OCR entirely and save the per-page cost.
USE_OCR_HINT = os.getenv("USE_OCR_HINT", "true").strip().lower() == "true"

# Hint budget. The previous pipeline hard-coded 1500, which truncated 27-33% of
# the text on dense multi-item bills -- exactly the bills where the hint is
# worth having.
OCR_MAX_CHARS = int(os.getenv("OCR_MAX_CHARS", "6000"))

# Tesseract only: the hint is discarded when mean word confidence is below
# OCR_MIN_CONFIDENCE *and* fewer than OCR_MIN_WORDS words were read. Both
# conditions are required. Confidence alone was throwing away real pages: a
# dense 6-page bill scored 33.3 across 955 words -- noisy, but plainly a read
# page rather than a collapse, and the whole hint was dropped.
OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "35"))
OCR_MIN_WORDS = int(os.getenv("OCR_MIN_WORDS", "40"))

# PP-OCR only: drop individual detections recognised below this score.
OCR_REC_MIN_SCORE = float(os.getenv("OCR_REC_MIN_SCORE", "0.5"))

# PP-OCR only: below this many characters the page is treated as a failed read
# and Tesseract is tried instead.
OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "40"))

# PP-OCR only: a result thinner than this is *suspicious* rather than failed,
# so Tesseract is run as a second opinion and the richer of the two is kept.
# PP-OCR's detector occasionally under-segments a page Tesseract reads well
# (one invoice yielded 32 detections / 478 chars against Tesseract's 904, and
# raising the detector input size did not recover it). Measured across 50
# pages of real bills, only 7 fall below this, so the extra pass is rare.
OCR_THIN_CHARS = int(os.getenv("OCR_THIN_CHARS", "800"))

# Row reconstruction. Two detections share a row when their vertical centres
# are within OCR_ROW_Y_TOL * (median detection height). Within a row, a
# horizontal gap wider than OCR_ROW_GAP * (median height) is rendered as a
# column break rather than a single space.
OCR_ROW_Y_TOL = float(os.getenv("OCR_ROW_Y_TOL", "0.6"))
OCR_ROW_GAP = float(os.getenv("OCR_ROW_GAP", "0.75"))

# Correct 90-degree page rotation via Tesseract's OSD before OCR *and* before
# the image is handed to the model. A sideways page costs accuracy in both.
# Measured: a rotated handwritten pharmacy bill went from unreadable to a
# correctly ordered column header row once this was applied.
OCR_AUTOROTATE = os.getenv("OCR_AUTOROTATE", "true").strip().lower() == "true"

# 180-degree flips are NOT applied by default, and this is not timidity.
# OSD infers 90/270 from the geometry of text lines, which is reliable; it
# infers 0-vs-180 from glyph asymmetry, which fails on table-heavy forms with
# few words. On a 5-page hospital bill OSD reported 180 on every page -- twice
# at confidence 5.86, higher than several correct readings, so a confidence
# threshold does not separate them. Applying those flips turned an upright
# page upside down and took Tesseract from 2563 characters to zero on all five
# pages. The costs are asymmetric: wrongly flipping a page destroys it, while
# declining to flip a genuinely inverted one leaves it no worse than before
# (and PP-OCR's textline orientation classifier still copes). Enable only if
# your scans are reliably fed upside down.
OCR_AUTOROTATE_180 = os.getenv("OCR_AUTOROTATE_180", "false").strip().lower() == "true"

# Secondary guard: ignore any OSD call made with less confidence than this.
OCR_OSD_MIN_CONFIDENCE = float(os.getenv("OCR_OSD_MIN_CONFIDENCE", "2.0"))

COLUMN_GAP = "   "

_NUMERIC = re.compile(r"\d[\d,]*\.?\d*")


# ── Optional dependencies ──────────────────────────────────────────────────

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter

    _tesseract_cmd = os.getenv("TESSERACT_CMD")
    if _tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
    TESSERACT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in stripped installs
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract or Pillow is unavailable; Tesseract OCR is disabled")

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMPY_AVAILABLE = False
    logger.warning("numpy is unavailable; PP-OCR is disabled")


_ppocr_engine: Optional[Any] = None
_ppocr_lock = threading.Lock()
_ppocr_unavailable = False


def _get_ppocr_engine():
    """
    Build the PP-OCR engine once, under a lock.

    Model load costs ~90 MB of resident memory and a second of wall clock, so a
    double-initialisation race would be expensive rather than merely untidy.
    Returns None (permanently, via _ppocr_unavailable) if the package is
    missing, so callers degrade to Tesseract instead of retrying per page.
    """
    global _ppocr_engine, _ppocr_unavailable

    if _ppocr_unavailable or not NUMPY_AVAILABLE:
        return None
    if _ppocr_engine is not None:
        return _ppocr_engine

    with _ppocr_lock:
        if _ppocr_engine is not None:
            return _ppocr_engine
        try:
            from rapidocr import RapidOCR

            _ppocr_engine = RapidOCR()
            logger.info("PP-OCR (RapidOCR/onnxruntime) initialised")
            return _ppocr_engine
        except ImportError:
            _ppocr_unavailable = True
            logger.warning(
                "OCR_ENGINE=%s but rapidocr is not installed "
                "(pip install rapidocr onnxruntime); using Tesseract",
                OCR_ENGINE,
            )
            return None
        except Exception as error:  # noqa: BLE001
            _ppocr_unavailable = True
            logger.warning("PP-OCR failed to initialise (%s); using Tesseract", error)
            return None


# ── Image preparation ──────────────────────────────────────────────────────

def enhance_image(img):
    """Contrast/sharpness boost. Helps Tesseract; PP-OCR is fed the raw page."""
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img.filter(ImageFilter.MedianFilter(size=3))


def autorotate_page(img) -> Tuple[Any, int]:
    """
    Straighten a page rotated in 90-degree steps, using Tesseract's OSD.

    Returns (image, degrees_corrected). Any failure returns the page unchanged
    -- OSD raises on pages with too little text to judge, which is common and
    not an error worth surfacing.
    """
    if not (OCR_AUTOROTATE and TESSERACT_AVAILABLE):
        return img, 0
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        rotation = int(osd.get("rotate", 0)) % 360
        confidence = float(osd.get("orientation_conf", 0) or 0)

        if not rotation:
            return img, 0
        if confidence < OCR_OSD_MIN_CONFIDENCE:
            logger.info(
                "ignoring %d-degree rotation: OSD confidence %.2f < %.2f",
                rotation, confidence, OCR_OSD_MIN_CONFIDENCE,
            )
            return img, 0
        if rotation == 180 and not OCR_AUTOROTATE_180:
            logger.info(
                "ignoring 180-degree flip (OSD confidence %.2f); OSD cannot tell "
                "0 from 180 reliably on forms. Set OCR_AUTOROTATE_180=true to apply it.",
                confidence,
            )
            return img, 0

        logger.info(
            "rotating page by %d degrees (OSD confidence %.2f) before OCR and extraction",
            rotation, confidence,
        )
        return img.rotate(-rotation, expand=True), rotation
    except Exception as error:  # noqa: BLE001
        logger.debug("orientation detection unavailable for this page: %s", error)
    return img, 0


# ── Row reconstruction ─────────────────────────────────────────────────────

def rebuild_rows(
    boxes: Sequence[Any],
    texts: Sequence[Any],
    scores: Sequence[Any],
    min_score: float = OCR_REC_MIN_SCORE,
    y_tolerance: float = OCR_ROW_Y_TOL,
    gap_factor: float = OCR_ROW_GAP,
) -> str:
    """
    Group PP-OCR detections back into the visual rows of the page.

    `boxes` holds one quadrilateral per detection as four (x, y) points; lists
    and numpy arrays both work. Detections are bucketed by the vertical centre
    of their box, then ordered left to right within each bucket, so a table row
    is reassembled in reading order.

    Pure function with no model dependency, which is what makes it testable
    without downloading weights.
    """
    detections = []
    for box, text, score in zip(boxes, texts, scores):
        try:
            if float(score) < min_score:
                continue
        except (TypeError, ValueError):
            continue

        label = str(text).strip()
        if not label:
            continue

        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        if not xs or not ys:
            continue

        detections.append(
            {
                "text": label,
                "x0": min(xs),
                "x1": max(xs),
                "y_center": (min(ys) + max(ys)) / 2.0,
                "height": max(ys) - min(ys),
            }
        )

    if not detections:
        return ""

    heights = sorted(d["height"] for d in detections)
    median_height = heights[len(heights) // 2] or 1.0

    detections.sort(key=lambda d: (d["y_center"], d["x0"]))

    rows: List[List[dict]] = []
    current = [detections[0]]
    current_center = detections[0]["y_center"]

    for detection in detections[1:]:
        if abs(detection["y_center"] - current_center) <= y_tolerance * median_height:
            current.append(detection)
            # Track the running mean so a row drifting gently down the page
            # (a photographed bill is never perfectly level) stays one row.
            current_center = sum(d["y_center"] for d in current) / len(current)
        else:
            rows.append(current)
            current = [detection]
            current_center = detection["y_center"]
    rows.append(current)

    lines = []
    for row in rows:
        row.sort(key=lambda d: d["x0"])
        parts = [row[0]["text"]]
        for previous, detection in zip(row, row[1:]):
            gap = detection["x0"] - previous["x1"]
            separator = COLUMN_GAP if gap > gap_factor * median_height else " "
            parts.append(separator + detection["text"])
        line = "".join(parts).strip()
        if line:
            lines.append(line)

    return "\n".join(lines).strip()


# ── Engines ────────────────────────────────────────────────────────────────

def ocr_page_ppocr(img) -> str:
    """
    OCR a page with PP-OCR, returning row-reconstructed text.

    Returns "" on any failure, which makes the caller fall back to Tesseract
    rather than losing the hint entirely.
    """
    engine = _get_ppocr_engine()
    if engine is None:
        return ""
    try:
        result = engine(np.array(img.convert("RGB")))
        if result is None or result.txts is None or result.boxes is None:
            return ""
        return rebuild_rows(result.boxes, result.txts, result.scores)
    except Exception as error:  # noqa: BLE001
        logger.warning("PP-OCR failed on this page (%s); falling back to Tesseract", error)
        return ""


def ocr_page_tesseract(img) -> str:
    """
    OCR a page with Tesseract, returning text only if it looks trustworthy.

    Uses image_to_data rather than image_to_string so that text and per-word
    confidence come from a SINGLE pass -- calling both would double the cost of
    the slowest step in this path.

    --psm 6 is deliberate and measured: against pdftotext ground truth it
    scored 80.7% F1 on numeric tokens versus 6.2% for the psm 3 default. Do not
    "fix" it to automatic page segmentation.
    """
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        data = pytesseract.image_to_data(
            enhance_image(img.copy()), config="--psm 6", output_type=pytesseract.Output.DICT
        )

        lines: dict = {}
        confidences: List[float] = []
        for index, word in enumerate(data["text"]):
            if not word.strip():
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence < 0:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(word)
            confidences.append(confidence)

        if not confidences:
            return ""

        mean_confidence = sum(confidences) / len(confidences)
        if mean_confidence < OCR_MIN_CONFIDENCE and len(confidences) < OCR_MIN_WORDS:
            logger.info(
                "dropping Tesseract hint: mean confidence %.1f < %.1f across only "
                "%d words (OCR collapsed on this page; the model still gets the image)",
                mean_confidence, OCR_MIN_CONFIDENCE, len(confidences),
            )
            return ""

        return "\n".join(" ".join(words) for _, words in sorted(lines.items())).strip()
    except Exception as error:  # noqa: BLE001
        logger.warning("Tesseract OCR failed: %s", error)
        return ""


def numeric_tokens(text: str) -> int:
    """Count number-like tokens. On a bill these are the payload."""
    return len(_NUMERIC.findall(text or ""))


def ocr_page(img) -> str:
    """
    Produce the OCR text hint for one page.

    PP-OCR runs first when enabled. Two things can send the page to Tesseract:

      * a failed read (under OCR_MIN_CHARS) -- Tesseract's result is used
        outright;
      * a thin read (under OCR_THIN_CHARS) -- Tesseract runs as a second
        opinion and whichever transcription carries more numeric tokens wins.

    The tie-break counts numbers rather than characters deliberately. On one
    bill Tesseract returned more text (2280 vs 2028 characters) while PP-OCR
    recovered more of the amounts (251 vs 241), and the amounts are what the
    downstream extraction needs.
    """
    if not USE_OCR_HINT:
        return ""

    if OCR_ENGINE != "ppocr":
        return ocr_page_tesseract(img)[:OCR_MAX_CHARS]

    text = ocr_page_ppocr(img)
    if len(text) >= OCR_THIN_CHARS:
        return text[:OCR_MAX_CHARS]

    fallback = ocr_page_tesseract(img)

    if len(text) < OCR_MIN_CHARS:
        if fallback:
            logger.info(
                "PP-OCR yielded only %d characters (< %d); using Tesseract (%d)",
                len(text), OCR_MIN_CHARS, len(fallback),
            )
            return fallback[:OCR_MAX_CHARS]
        return text[:OCR_MAX_CHARS]

    if fallback and numeric_tokens(fallback) > numeric_tokens(text):
        logger.info(
            "thin PP-OCR page (%d chars, %d numbers); Tesseract read more "
            "numbers (%d) so its transcription is used",
            len(text), numeric_tokens(text), numeric_tokens(fallback),
        )
        return fallback[:OCR_MAX_CHARS]

    return text[:OCR_MAX_CHARS]
