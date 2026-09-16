"""
Tests for the OCR engine layer.

Everything here runs without model weights, a GPU or a network connection:
`rebuild_rows` is a pure function over bounding boxes, and the dispatcher is
exercised through monkeypatched engines. That keeps the suite usable in CI.
"""

import pytest

from app import ocr_engines
from app.ocr_engines import rebuild_rows


def box(x0, y0, x1, y1):
    """Axis-aligned quadrilateral in the four-point form PP-OCR returns."""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class TestRebuildRows:
    def test_cells_on_one_line_become_one_row(self):
        """The case the naive newline-join implementation destroys."""
        boxes = [
            box(100, 200, 400, 230),
            box(450, 202, 540, 232),
            box(600, 201, 650, 231),
            box(700, 200, 780, 230),
        ]
        texts = ["BLOOD SUGAR BY GLUCOMETER", "13/11/25", "1 No", "80.00"]
        scores = [0.99, 0.98, 0.97, 0.99]

        result = rebuild_rows(boxes, texts, scores)

        assert result.count("\n") == 0
        assert result.startswith("BLOOD SUGAR BY GLUCOMETER")
        assert result.endswith("80.00")
        for token in texts:
            assert token in result

    def test_separate_lines_stay_separate(self):
        boxes = [box(100, 200, 300, 230), box(100, 300, 300, 330)]
        result = rebuild_rows(boxes, ["Row one", "Row two"], [0.9, 0.9])
        assert result.splitlines() == ["Row one", "Row two"]

    def test_row_membership_tolerates_slight_tilt(self):
        """A photographed bill is never perfectly level."""
        boxes = [box(100, 200, 200, 230), box(250, 206, 350, 236), box(400, 212, 500, 242)]
        result = rebuild_rows(boxes, ["A", "B", "C"], [0.9, 0.9, 0.9])
        assert len(result.splitlines()) == 1

    def test_wide_gap_renders_as_column_break(self):
        boxes = [box(100, 200, 200, 230), box(900, 200, 1000, 230)]
        result = rebuild_rows(boxes, ["Item", "500.00"], [0.9, 0.9])
        assert ocr_engines.COLUMN_GAP in result

    def test_adjacent_words_joined_by_single_space(self):
        boxes = [box(100, 200, 200, 230), box(205, 200, 300, 230)]
        result = rebuild_rows(boxes, ["Bill", "Date"], [0.9, 0.9])
        assert result == "Bill Date"

    def test_detections_are_ordered_left_to_right(self):
        """Input order follows detection confidence, not reading order."""
        boxes = [box(700, 200, 780, 230), box(100, 200, 400, 230)]
        result = rebuild_rows(boxes, ["99.00", "CONSULTATION"], [0.9, 0.9])
        assert result.index("CONSULTATION") < result.index("99.00")

    def test_low_score_detections_dropped(self):
        boxes = [box(100, 200, 200, 230), box(250, 200, 350, 230)]
        result = rebuild_rows(boxes, ["keep", "noise"], [0.95, 0.10], min_score=0.5)
        assert result == "keep"

    def test_empty_input(self):
        assert rebuild_rows([], [], []) == ""

    def test_all_detections_below_threshold(self):
        assert rebuild_rows([box(0, 0, 10, 10)], ["x"], [0.01], min_score=0.5) == ""

    def test_whitespace_only_text_ignored(self):
        assert rebuild_rows([box(0, 0, 10, 10)], ["   "], [0.99]) == ""

    def test_malformed_box_skipped_without_raising(self):
        boxes = [box(100, 200, 200, 230), "not-a-box"]
        result = rebuild_rows(boxes, ["good", "bad"], [0.9, 0.9])
        assert result == "good"

    def test_non_numeric_score_skipped(self):
        boxes = [box(100, 200, 200, 230), box(250, 200, 350, 230)]
        result = rebuild_rows(boxes, ["good", "bad"], [0.9, None])
        assert result == "good"

    def test_zero_height_boxes_do_not_divide_by_zero(self):
        boxes = [box(100, 200, 200, 200), box(250, 200, 350, 200)]
        assert rebuild_rows(boxes, ["A", "B"], [0.9, 0.9])


class TestEngineDispatch:
    """ocr_page: PP-OCR primary, Tesseract fallback."""

    @pytest.fixture(autouse=True)
    def _engine_defaults(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "USE_OCR_HINT", True)
        monkeypatch.setattr(ocr_engines, "OCR_ENGINE", "ppocr")
        monkeypatch.setattr(ocr_engines, "OCR_MIN_CHARS", 40)
        monkeypatch.setattr(ocr_engines, "OCR_MAX_CHARS", 6000)

    def test_ppocr_result_used_when_it_reads_the_page(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "P" * 100)
        monkeypatch.setattr(
            ocr_engines, "ocr_page_tesseract", lambda img: pytest.fail("should not run")
        )
        assert ocr_engines.ocr_page(object()) == "P" * 100

    def test_falls_back_when_ppocr_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "T" * 100)
        assert ocr_engines.ocr_page(object()) == "T" * 100

    def test_falls_back_when_ppocr_yield_is_too_low(self, monkeypatch):
        """A near-empty read is worse than no hint -- retry with Tesseract."""
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "abc")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "T" * 100)
        assert ocr_engines.ocr_page(object()) == "T" * 100

    def test_tesseract_engine_skips_ppocr_entirely(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "OCR_ENGINE", "tesseract")
        monkeypatch.setattr(
            ocr_engines, "ocr_page_ppocr", lambda img: pytest.fail("should not run")
        )
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "T" * 100)
        assert ocr_engines.ocr_page(object()) == "T" * 100

    def test_both_engines_failing_yields_empty_hint(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "")
        assert ocr_engines.ocr_page(object()) == ""

    def test_hint_is_capped(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "OCR_MAX_CHARS", 50)
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "P" * 5000)
        assert len(ocr_engines.ocr_page(object())) == 50

    def test_use_ocr_hint_false_disables_all_ocr(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "USE_OCR_HINT", False)
        monkeypatch.setattr(
            ocr_engines, "ocr_page_ppocr", lambda img: pytest.fail("should not run")
        )
        assert ocr_engines.ocr_page(object()) == ""


class TestPPOCRFailureHandling:
    def test_missing_package_degrades_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "_get_ppocr_engine", lambda: None)
        assert ocr_engines.ocr_page_ppocr(object()) == ""

    def test_engine_exception_is_swallowed(self, monkeypatch):
        """A failing inference must degrade to Tesseract, not 500 the request."""

        class StubImage:
            def convert(self, _mode):
                return self

        def exploding_engine(_array):
            raise RuntimeError("inference failed")

        monkeypatch.setattr(ocr_engines, "_get_ppocr_engine", lambda: exploding_engine)
        assert ocr_engines.ocr_page_ppocr(StubImage()) == ""
