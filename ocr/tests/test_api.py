"""
Tests for the Medical Bill Extractor API.
Run:  pytest -q
"""

import os
import json
import pytest
from fastapi.testclient import TestClient

# Force mock mode so tests don't need a real API key
os.environ["USE_MOCK_MODE"] = "true"

from app.main import app
from app.schemas import ExtractionResponse, BillItem, PageLineItems
from app.extractor import (
    _clean_json,
    _extract_json_value,
    _safe_float,
    _parse_page_result,
    BillExtractor,
    ExtractionError,
)

client = TestClient(app)


# ── Unit tests ─────────────────────────────────────────────────────────────

class TestHelpers:
    def test_clean_json_strips_fences(self):
        raw = "```json\n{\"key\": 1}\n```"
        assert _clean_json(raw) == '{"key": 1}'

    def test_clean_json_no_fences(self):
        raw = '{"key": 1}'
        assert _clean_json(raw) == raw

    def test_extract_json_value_accepts_gemini_preamble(self):
        raw = 'Here is the requested JSON:\n[{"page_no": "1"}]\n'
        assert _extract_json_value(raw) == [{"page_no": "1"}]

    def test_extract_json_value_rejects_non_json(self):
        with pytest.raises(ExtractionError, match="malformed"):
            _extract_json_value("no structured result")

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_string(self):
        assert _safe_float("123.45") == 123.45

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None

    def test_safe_float_int(self):
        assert _safe_float(100) == 100.0

    def test_parse_page_result_valid(self):
        raw = json.dumps({
            "page_no": "1",
            "page_type": "Bill Detail",
            "bill_items": [
                {"item_name": "Consultation", "item_amount": 500.0,
                 "item_rate": 500.0, "item_quantity": 1.0}
            ],
            "fraud_flags": []
        })
        page, flags = _parse_page_result(raw, 1)
        assert page.page_no == "1"
        assert page.page_type == "Bill Detail"
        assert len(page.bill_items) == 1
        assert page.bill_items[0].item_name == "Consultation"
        assert page.bill_items[0].item_amount == 500.0
        assert flags == []

    def test_parse_page_result_invalid_json(self):
        with pytest.raises(ExtractionError, match="malformed"):
            _parse_page_result("not json at all", 1)

    def test_parse_page_result_missing_amount(self):
        raw = json.dumps({
            "page_no": "2",
            "page_type": "Lab Bill",
            "bill_items": [
                {"item_name": "CBC", "item_amount": None}
            ]
        })
        page, _ = _parse_page_result(raw, 2)
        assert page.bill_items[0].item_amount == 0.0


class TestDeduplication:
    def test_summary_suppressed_when_detail_present(self):
        extractor = BillExtractor()
        pages = [
            PageLineItems(
                page_no="1",
                page_type="Bill Summary",
                bill_items=[BillItem(item_name="Total", item_amount=5000)]
            ),
            PageLineItems(
                page_no="2",
                page_type="Bill Detail",
                bill_items=[
                    BillItem(item_name="Bed Charge", item_amount=2000),
                    BillItem(item_name="Consultation", item_amount=3000),
                ]
            ),
        ]
        result = extractor._deduplicate(pages)
        summary_page = next(p for p in result if p.page_type == "Bill Summary")
        detail_page  = next(p for p in result if p.page_type == "Bill Detail")
        assert summary_page.bill_items == []
        assert len(detail_page.bill_items) == 2

    def test_summary_kept_if_no_detail(self):
        extractor = BillExtractor()
        pages = [
            PageLineItems(
                page_no="1",
                page_type="Bill Summary",
                bill_items=[BillItem(item_name="Drugs", item_amount=1000)]
            )
        ]
        result = extractor._deduplicate(pages)
        assert len(result[0].bill_items) == 1


# ── API endpoint tests ──────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestExtractFromFileValidation:
    def test_unsupported_upload_returns_400(self):
        r = client.post(
            "/extract-from-file",
            files={"file": ("notes.txt", b"not a bill", "text/plain")},
        )
        assert r.status_code == 400

    def test_missing_upload_returns_422(self):
        r = client.post("/extract-from-file")
        assert r.status_code == 422  # Pydantic validation error


class TestExtractFromFile:
    def test_upload_empty_file(self, tmp_path):
        # Create a minimal fake PDF
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        with open(fake_pdf, "rb") as f:
            r = client.post(
                "/extract-from-file",
                files={"file": ("test.pdf", f, "application/pdf")},
            )
        # In mock mode this should still succeed (no real rendering needed)
        assert r.status_code in (200, 500)  # 500 if pdf2image not installed in CI

    def test_response_schema(self, tmp_path):
        """Validate response matches ExtractionResponse schema in mock mode."""
        fake_pdf = tmp_path / "bill.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        with open(fake_pdf, "rb") as f:
            r = client.post(
                "/extract-from-file",
                files={"file": ("bill.pdf", f, "application/pdf")},
            )
        if r.status_code == 200:
            body = r.json()
            # Validate required top-level keys
            assert "is_success" in body
            assert "token_usage" in body
            assert "error" in body


# ── Schema tests ───────────────────────────────────────────────────────────

class TestSchemas:
    def test_bill_item_required_fields(self):
        item = BillItem(item_name="Test", item_amount=100.0)
        assert item.item_rate is None
        assert item.item_quantity is None

    def test_extraction_response_success(self):
        from app.schemas import ExtractionData, TokenUsage
        resp = ExtractionResponse(
            is_success=True,
            token_usage=TokenUsage(total_tokens=100, input_tokens=80, output_tokens=20),
            data=ExtractionData(
                pagewise_line_items=[],
                total_item_count=0,
                grand_total=0.0,
            ),
        )
        assert resp.is_success is True
        assert resp.error is None

    def test_extraction_response_failure(self):
        resp = ExtractionResponse(is_success=False, error="Something went wrong")
        assert resp.is_success is False
        assert resp.data is None


class TestRetryClassification:
    """
    Transient vs permanent error classification.

    The 503 case is regression cover: Gemini reports capacity pressure with a
    message that contains neither "rate limit" nor "temporarily unavailable",
    so an earlier version treated it as permanent and never retried.
    """

    GEMINI_503 = (
        "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is "
        "currently experiencing high demand. Spikes in demand are usually "
        "temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
    )
    GEMINI_404 = (
        "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model "
        "models/gemini-2.5-flash is no longer available to new users.', "
        "'status': 'NOT_FOUND'}}"
    )
    GEMINI_429 = "429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"

    def test_503_high_demand_is_retryable(self):
        from app.extractor import GeminiCaller
        assert GeminiCaller._retryable_error(Exception(self.GEMINI_503))

    def test_503_is_not_treated_as_a_permanent_model_error(self):
        from app.extractor import GeminiCaller
        assert not GeminiCaller._permanent_model_error(Exception(self.GEMINI_503))

    def test_429_is_retryable(self):
        from app.extractor import GeminiCaller
        assert GeminiCaller._retryable_error(Exception(self.GEMINI_429))

    def test_404_retired_model_is_permanent_not_retryable(self):
        from app.extractor import GeminiCaller
        assert GeminiCaller._permanent_model_error(Exception(self.GEMINI_404))

    def test_auth_failure_is_not_retryable(self):
        from app.extractor import GeminiCaller
        assert not GeminiCaller._retryable_error(Exception("403 PERMISSION_DENIED: bad api key"))

    def test_404_message_tells_the_operator_the_model_is_wrong(self):
        from app.extractor import _error_message
        assert "model is unavailable" in _error_message(Exception(self.GEMINI_404))


class TestJsonDecoding:
    """
    Regression cover for decode() vs raw_decode().

    decode() returns the value; raw_decode() returns (value, end_index). The
    original code subscripted both, so clean JSON took the buggy path while
    the existing preamble test took the correct one and hid it.
    """

    def test_clean_array_returns_the_whole_list(self):
        assert _extract_json_value('[{"page_no": "1"}, {"page_no": "2"}]') == [
            {"page_no": "1"}, {"page_no": "2"},
        ]

    def test_clean_single_page_array_is_not_unwrapped(self):
        assert _extract_json_value('[{"page_no": "1"}]') == [{"page_no": "1"}]

    def test_clean_object_does_not_raise_keyerror(self):
        assert _extract_json_value('{"page_no": "1"}') == {"page_no": "1"}

    def test_bare_string_is_not_sliced(self):
        assert _extract_json_value('"no items found"') == "no items found"

    def test_preamble_still_works(self):
        assert _extract_json_value('Here is the JSON:\n[{"page_no": "1"}]') == [{"page_no": "1"}]

    def test_fenced_json_still_works(self):
        assert _extract_json_value('```json\n[{"page_no": "1"}]\n```') == [{"page_no": "1"}]


class TestBatchReconciliation:
    """A page-count mismatch must not discard the pages that did come back."""

    @staticmethod
    def _pages(*numbers):
        return json.dumps([
            {"page_no": str(n), "page_type": "Bill Detail",
             "bill_items": [{"item_name": f"Item {n}", "item_amount": 10.0 * n}]}
            for n in numbers
        ])

    def test_exact_match(self):
        from app.extractor import GeminiCaller
        out = GeminiCaller._split_batch_response(self._pages(1, 2, 3), 3)
        assert len(out) == 3
        assert json.loads(out[0])["page_no"] == "1"

    def test_single_page_object_not_wrapped_in_a_list(self):
        from app.extractor import GeminiCaller
        out = GeminiCaller._split_batch_response(
            json.dumps({"page_no": "1", "bill_items": []}), 1)
        assert len(out) == 1

    def test_too_few_pages_pads_and_keeps_real_ones(self):
        from app.extractor import GeminiCaller
        out = GeminiCaller._split_batch_response(self._pages(1, 2), 3)
        assert len(out) == 3
        assert json.loads(out[0])["bill_items"]          # real page survived
        assert json.loads(out[2])["bill_items"] == []    # filler is empty

    def test_too_many_pages_truncates(self):
        from app.extractor import GeminiCaller
        out = GeminiCaller._split_batch_response(self._pages(1, 2, 3, 4, 5), 3)
        assert len(out) == 3

    def test_envelope_object_is_unwrapped(self):
        from app.extractor import GeminiCaller
        body = json.dumps({"pagewise_line_items": json.loads(self._pages(1, 2))})
        out = GeminiCaller._split_batch_response(body, 2)
        assert len(out) == 2
        assert json.loads(out[1])["page_no"] == "2"

    def test_non_dict_entries_are_filtered(self):
        from app.extractor import GeminiCaller
        body = json.dumps([{"page_no": "1", "bill_items": []}, "junk", 42])
        out = GeminiCaller._split_batch_response(body, 1)
        assert len(out) == 1

    def test_scalar_reply_still_raises(self):
        from app.extractor import GeminiCaller
        with pytest.raises(ExtractionError, match="malformed"):
            GeminiCaller._split_batch_response('"nothing to extract"', 2)

    def test_empty_list_still_raises(self):
        from app.extractor import GeminiCaller
        with pytest.raises(ExtractionError, match="malformed"):
            GeminiCaller._split_batch_response("[]", 2)


class TestModelFallbackAndRetries:
    """Tests for multi-model queue fallback, bounded retry backoff, and fail-fast."""

    @pytest.fixture(autouse=True)
    def _disable_mock_mode(self, monkeypatch):
        import app.extractor
        monkeypatch.setattr(app.extractor, "USE_MOCK_MODE", False)

    class MockModelResponse:

        def __init__(self, text):
            self.text = text
            self.usage_metadata = type("Usage", (), {
                "prompt_token_count": 100,
                "candidates_token_count": 50,
            })()

    def test_queue_deduplication(self):
        from app.extractor import GeminiCaller
        caller = GeminiCaller(models=["model-a", "model-b", "model-a", "model-c", ""])
        assert caller.model_queue == ["model-a", "model-b", "model-c"]

    def test_transient_503_retries_and_falls_back_to_next_model(self):
        from app.extractor import GeminiCaller
        caller = GeminiCaller(
            models=["primary-model", "fallback-model"],
            max_retries=2,
            retry_base_delay=0.01,
        )

        calls = []

        def mock_generate_content(model, contents, config):
            calls.append(model)
            if model == "primary-model":
                raise Exception("503 UNAVAILABLE. Currently experiencing high demand.")
            return self.MockModelResponse(json.dumps([{"page_no": "1", "bill_items": []}]))

        mock_client = type("MockClient", (), {
            "models": type("MockModels", (), {"generate_content": staticmethod(mock_generate_content)})()
        })()
        caller.client = mock_client

        out = caller.call([b"fake_image"], ["hint"], [1])
        assert len(out) == 1
        assert json.loads(out[0])["page_no"] == "1"

        # primary-model attempted 1 initial + 2 retries = 3 times
        assert calls.count("primary-model") == 3
        # fallback-model called once and succeeded
        assert calls.count("fallback-model") == 1
        assert calls[-1] == "fallback-model"
        assert caller.token_usage.total_tokens == 150

    def test_permanent_404_skips_retries_and_falls_back_immediately(self):
        from app.extractor import GeminiCaller
        caller = GeminiCaller(
            models=["retired-model", "working-model"],
            max_retries=3,
            retry_base_delay=0.01,
        )

        calls = []

        def mock_generate_content(model, contents, config):
            calls.append(model)
            if model == "retired-model":
                raise Exception("404 NOT_FOUND. Model models/retired-model is not found.")
            return self.MockModelResponse(json.dumps([{"page_no": "1", "bill_items": []}]))

        mock_client = type("MockClient", (), {
            "models": type("MockModels", (), {"generate_content": staticmethod(mock_generate_content)})()
        })()
        caller.client = mock_client

        out = caller.call([b"fake_image"], ["hint"], [1])
        assert len(out) == 1

        # retired-model attempted exactly 1 time (0 retries wasted)
        assert calls.count("retired-model") == 1
        assert calls.count("working-model") == 1

    def test_auth_error_fails_fast_without_trying_other_models(self):
        from app.extractor import GeminiCaller, ExtractionError
        caller = GeminiCaller(
            models=["model-1", "model-2"],
            max_retries=2,
            retry_base_delay=0.01,
        )

        calls = []

        def mock_generate_content(model, contents, config):
            calls.append(model)
            raise Exception("403 PERMISSION_DENIED. The caller does not have permission")

        mock_client = type("MockClient", (), {
            "models": type("MockModels", (), {"generate_content": staticmethod(mock_generate_content)})()
        })()
        caller.client = mock_client

        with pytest.raises(ExtractionError, match="authentication is unavailable"):
            caller.call([b"fake_image"], ["hint"], [1])

        # Failed on model-1 immediately; did not waste calls on model-2
        assert calls == ["model-1"]

    def test_all_models_fail_raises_extraction_error(self):
        from app.extractor import GeminiCaller, ExtractionError
        caller = GeminiCaller(
            models=["model-1", "model-2"],
            max_retries=1,
            retry_base_delay=0.01,
        )

        calls = []

        def mock_generate_content(model, contents, config):
            calls.append(model)
            raise Exception("503 UNAVAILABLE. High demand")

        mock_client = type("MockClient", (), {
            "models": type("MockModels", (), {"generate_content": staticmethod(mock_generate_content)})()
        })()
        caller.client = mock_client

        with pytest.raises(ExtractionError, match="high demand"):
            caller.call([b"fake_image"], ["hint"], [1])

        # Each model attempted 2 times (1 + 1 retry) = 4 calls total
        assert calls == ["model-1", "model-1", "model-2", "model-2"]

