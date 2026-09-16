"""Medical-bill extraction pipeline: PDF/image -> OCR -> Gemini -> structured JSON."""
import io, json, logging, os, re, sys, time
from pathlib import Path
from typing import List, Optional, Tuple
from dotenv import load_dotenv
from app.schemas import BillItem, ExtractionData, ExtractionResponse, PageLineItems, TokenUsage

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError as error:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image import failed (%s); PDF rendering is disabled", error)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow is unavailable; image input is disabled")

from app.ocr_engines import OCR_ENGINE, OCR_MAX_CHARS, autorotate_page, ocr_page
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError as error:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai import failed (%s); Gemini extraction is disabled", error)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = [model.strip() for model in os.getenv("GEMINI_MODEL_FALLBACKS", "").split(",") if model.strip()]
MAX_RETRIES = max(0, min(int(os.getenv("MAX_RETRIES", "2")), 3))
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "3")))
PDF_DPI = max(72, int(os.getenv("PDF_DPI", "200")))
POPPLER_PATH = os.getenv("POPPLER_PATH") or None
USE_MOCK_MODE = os.getenv("USE_MOCK_MODE", "false").lower() == "true"
logger.info("Gemini API key: %s", "loaded" if GOOGLE_API_KEY else "not loaded")
logger.info("OCR engine: %s (hint capped at %d characters)", OCR_ENGINE, OCR_MAX_CHARS)
logger.info("interpreter: %s", sys.executable)
logger.info(
    "optional dependencies: pdf2image=%s gemini=%s",
    "ok" if PDF2IMAGE_AVAILABLE else "MISSING",
    "ok" if GEMINI_AVAILABLE else "MISSING",
)

SYSTEM_PROMPT = """You are an expert medical billing analyst. Extract every individual bill line item from each supplied page. Return a JSON ARRAY containing exactly one object per page, in the same order: [{"page_no":"1","page_type":"Bill Summary | Bill Detail | Pharmacy Bill | Lab Bill | Other","bill_items":[{"item_name":"description","item_amount":0.0,"item_rate":null,"item_quantity":null}],"fraud_flags":[]}]. Do not include subtotals or grand totals as line items. Summary pages with only category totals must have an empty bill_items list. Amounts must be numeric, and output must be valid JSON only."""

class ExtractionError(Exception):
    """A safe, classified extraction failure suitable for the API response."""

def _error_message(error: Exception) -> str:
    detail = str(error).lower()
    if any(mark in detail for mark in ("429", "resource_exhausted", "quota", "credits")):
        return "Gemini quota or credits are currently unavailable. Please try again later."
    if any(mark in detail for mark in ("404", "not found", "not supported")):
        return "The configured Gemini model is unavailable. Contact the service administrator."
    if any(mark in detail for mark in ("api key", "authentication", "permission", "403")):
        return "Gemini authentication is unavailable. Contact the service administrator."
    return "Gemini extraction is currently unavailable. Please try again later."

def _encode_image(img) -> bytes:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue()

def _pdf_to_images(pdf_path: str) -> List:
    if not PDF2IMAGE_AVAILABLE: raise ExtractionError("PDF rendering is unavailable because pdf2image is not installed.")
    try: return convert_from_path(pdf_path, dpi=PDF_DPI, poppler_path=POPPLER_PATH)
    except Exception as error:
        logger.exception("PDF rendering failed")
        raise ExtractionError("Unable to render the PDF. Verify that Poppler is installed and configured.") from error

def _clean_json(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?", "", raw.strip(), flags=re.MULTILINE)
    return re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()


def _extract_json_value(raw: str):
    """Decode Gemini JSON, tolerating a surrounding prose/fence wrapper.

    Gemini is asked for JSON-only output, but models can still add a short
    preamble. The old pipeline accepted those responses; keeping that
    tolerance avoids discarding an otherwise valid extraction after the SDK
    migration. This never invents a page result: only a decoded JSON value is
    returned.
    """
    cleaned = _clean_json(raw)
    decoder = json.JSONDecoder()
    try:
        # decode() returns the value itself. raw_decode() returns a
        # (value, end_index) tuple, which is why the fallback below subscripts
        # and this does not -- subscripting here unwrapped a one-page list into
        # a bare page dict, raised KeyError on an object, and sliced the first
        # character off a string.
        return decoder.decode(cleaned)
    except json.JSONDecodeError:
        pass

    for start in (cleaned.find("["), cleaned.find("{")):
        if start < 0:
            continue
        try:
            return decoder.raw_decode(cleaned[start:])[0]
        except json.JSONDecodeError:
            continue
    raise ExtractionError("Gemini returned malformed extraction data.")

def _preview(raw: str, limit: int = 400) -> str:
    """Condense a model reply to one loggable line."""
    text = " ".join(str(raw).split())
    return text[:limit] + ("..." if len(text) > limit else "")

def _safe_float(val) -> Optional[float]:
    try: return None if val is None else float(val)
    except (TypeError, ValueError): return None

def _parse_page_result(raw_json: str, page_no: int) -> Tuple[PageLineItems, list]:
    try: data = json.loads(_clean_json(raw_json))
    except json.JSONDecodeError as error: raise ExtractionError("Gemini returned malformed extraction data.") from error
    if not isinstance(data, dict): raise ExtractionError("Gemini returned malformed extraction data.")
    items = []
    for raw_item in data.get("bill_items", []):
        if not isinstance(raw_item, dict): continue
        try: items.append(BillItem(item_name=str(raw_item.get("item_name", "Unknown")), item_amount=float(raw_item.get("item_amount", 0) or 0), item_rate=_safe_float(raw_item.get("item_rate")), item_quantity=_safe_float(raw_item.get("item_quantity"))))
        except (TypeError, ValueError): logger.warning("Skipping malformed bill item on page %s", page_no)
    return PageLineItems(page_no=str(data.get("page_no", page_no)), page_type=str(data.get("page_type", "Bill Detail")), bill_items=items), data.get("fraud_flags", [])

class GeminiCaller:
    def __init__(self):
        self.client = genai.Client(api_key=GOOGLE_API_KEY) if GEMINI_AVAILABLE and GOOGLE_API_KEY else None
        self.model_queue = [GEMINI_MODEL, *FALLBACK_MODELS]
        self._input_tokens = self._output_tokens = 0
    @property
    def token_usage(self) -> TokenUsage: return TokenUsage(total_tokens=self._input_tokens + self._output_tokens, input_tokens=self._input_tokens, output_tokens=self._output_tokens)
    @staticmethod
    def _permanent_model_error(error): return any(mark in str(error).lower() for mark in ("404", "not found", "not supported"))
    # Transient server-side conditions. Gemini reports capacity pressure as
    # "503 UNAVAILABLE ... currently experiencing high demand", which matched
    # none of the old marks ("temporarily unavailable" never appears in the
    # message), so the most retryable error there is went straight to the
    # give-up branch and MAX_RETRIES never fired.
    RETRYABLE_MARKS = (
        "429", "resource_exhausted", "rate limit",
        "500", "502", "503", "504",
        "unavailable", "overloaded", "high demand",
        "internal error", "deadline_exceeded", "try again",
    )

    @staticmethod
    def _retryable_error(error): return any(mark in str(error).lower() for mark in GeminiCaller.RETRYABLE_MARKS)
    def call(self, page_images: List[bytes], ocr_hints: List[str], page_numbers: List[int]) -> List[str]:
        if USE_MOCK_MODE: return [self._mock_response(page_no) for page_no in page_numbers]
        if not self.client: raise ExtractionError("Gemini is not configured. Set GOOGLE_API_KEY.")
        contents = []
        for image_bytes, ocr_text, page_number in zip(page_images, ocr_hints, page_numbers):
            contents.extend([types.Part.from_text(text=f"PAGE {page_number}. OCR hint:\n{ocr_text or '(unavailable)'}"), types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")])
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", temperature=0.1, max_output_tokens=8192)
        last_error = None
        for model_name in self.model_queue:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = self.client.models.generate_content(model=model_name, contents=contents, config=config)
                    usage = getattr(response, "usage_metadata", None)
                    self._input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                    self._output_tokens += getattr(usage, "candidates_token_count", 0) or 0
                    return self._split_batch_response(response.text or "", len(page_images))
                except Exception as error:
                    last_error = error
                    if self._permanent_model_error(error):
                        logger.warning("Gemini model %s is unavailable; trying the next configured model", model_name); break
                    if not self._retryable_error(error) or attempt == MAX_RETRIES:
                        logger.warning("Gemini model %s failed: %s", model_name, error); break
                    wait = min(2 ** (attempt + 1), 8)
                    logger.warning("Gemini model %s returned a transient error; retry %s/%s in %ss", model_name, attempt + 1, MAX_RETRIES, wait); time.sleep(wait)
        logger.error("All configured Gemini models failed: %s", last_error)
        raise ExtractionError(_error_message(last_error or Exception("No configured Gemini model")))
    # Keys a model plausibly wraps the page array in when it ignores the
    # "return a JSON ARRAY" instruction and returns an object instead.
    ENVELOPE_KEYS = ("pagewise_line_items", "pages", "results", "data", "page_results")

    @staticmethod
    def _split_batch_response(raw: str, expected: int) -> List[str]:
        """
        Normalise Gemini's reply into exactly `expected` page objects.

        A page count that disagrees with the batch used to fail the whole
        document, so one confused page cost every other page in the bill. A
        mismatch is now reconciled and logged: surplus pages are dropped,
        missing ones are filled with empty pages, and the pages that did come
        back survive.
        """
        parsed = _extract_json_value(raw)

        if isinstance(parsed, dict):
            for key in GeminiCaller.ENVELOPE_KEYS:
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break

        if isinstance(parsed, dict):
            parsed = [parsed]

        if not isinstance(parsed, list):
            logger.warning("Gemini returned %s, not a page list: %s", type(parsed).__name__, _preview(raw))
            raise ExtractionError("Gemini returned malformed extraction data.")

        pages = [item for item in parsed if isinstance(item, dict)]
        if not pages:
            logger.warning("Gemini returned no page objects: %s", _preview(raw))
            raise ExtractionError("Gemini returned malformed extraction data.")

        if len(pages) != expected:
            logger.warning(
                "Gemini returned %d page object(s) for a %d-page batch; reconciling. Raw: %s",
                len(pages), expected, _preview(raw),
            )
            pages = pages[:expected]
            pages.extend(
                {"page_no": str(index + 1), "page_type": "Bill Detail", "bill_items": []}
                for index in range(len(pages), expected)
            )

        return [json.dumps(page) for page in pages]
    @staticmethod
    def _mock_response(page_no: int) -> str:
        return json.dumps({"page_no": str(page_no), "page_type": "Bill Detail", "bill_items": [{"item_name": f"Mock Item {page_no}", "item_amount": 100.0 * page_no, "item_rate": 100.0, "item_quantity": 1}], "fraud_flags": []})

class BillExtractor:
    def __init__(self): self.gemini = GeminiCaller()
    def extract(self, file_path: str) -> ExtractionResponse:
        try: return self._run(file_path)
        except ExtractionError as error:
            logger.warning("Extraction failed: %s", error); return ExtractionResponse(is_success=False, error=str(error))
        except Exception:
            logger.exception("Unexpected extraction failure"); return ExtractionResponse(is_success=False, error="Unexpected extraction failure. Please try again later.")
    def _run(self, file_path: str) -> ExtractionResponse:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf": pil_images = _pdf_to_images(file_path)
        else:
            try: pil_images = [Image.open(file_path).convert("RGB")]
            except Exception as error: raise ExtractionError("The uploaded image could not be opened.") from error
        if not pil_images: raise ExtractionError("The document contains no renderable pages.")
        pil_images = [autorotate_page(image)[0] for image in pil_images]
        page_images, page_ocr = [_encode_image(image) for image in pil_images], [ocr_page(image) for image in pil_images]
        all_page_results, all_fraud_flags = [], []
        for batch_start in range(0, len(page_images), BATCH_SIZE):
            batch_images, batch_ocr = page_images[batch_start:batch_start+BATCH_SIZE], page_ocr[batch_start:batch_start+BATCH_SIZE]
            page_numbers = list(range(batch_start + 1, batch_start + len(batch_images) + 1))
            for page_no, raw in zip(page_numbers, self.gemini.call(batch_images, batch_ocr, page_numbers)):
                page_result, fraud_flags = _parse_page_result(raw, page_no); all_page_results.append(page_result); all_fraud_flags.extend(fraud_flags)
        if all_fraud_flags: logger.warning("Fraud flags detected: %s", all_fraud_flags)
        final_pages = self._deduplicate(all_page_results)
        total_items = sum(len(page.bill_items) for page in final_pages)
        grand_total = sum(item.item_amount for page in final_pages if page.page_type != "Bill Summary" for item in page.bill_items)
        return ExtractionResponse(is_success=True, token_usage=self.gemini.token_usage, data=ExtractionData(pagewise_line_items=final_pages, total_item_count=total_items, grand_total=round(grand_total, 2)))
    @staticmethod
    def _deduplicate(pages: List[PageLineItems]) -> List[PageLineItems]:
        if not any(page.page_type != "Bill Summary" for page in pages): return pages
        return [PageLineItems(page_no=page.page_no, page_type=page.page_type, bill_items=[]) if page.page_type == "Bill Summary" else page for page in pages]
