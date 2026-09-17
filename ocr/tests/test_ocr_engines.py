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
    """
    ocr_page: PP-OCR primary, Tesseract as failure fallback and thin-page
    second opinion.
    """

    @pytest.fixture(autouse=True)
    def _engine_defaults(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "USE_OCR_HINT", True)
        monkeypatch.setattr(ocr_engines, "OCR_ENGINE", "ppocr")
        monkeypatch.setattr(ocr_engines, "OCR_MIN_CHARS", 40)
        monkeypatch.setattr(ocr_engines, "OCR_THIN_CHARS", 800)
        monkeypatch.setattr(ocr_engines, "OCR_MAX_CHARS", 6000)

    def test_healthy_ppocr_page_skips_tesseract_entirely(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "P" * 900)
        monkeypatch.setattr(
            ocr_engines, "ocr_page_tesseract", lambda img: pytest.fail("should not run")
        )
        assert ocr_engines.ocr_page(object()) == "P" * 900

    def test_failed_ppocr_read_uses_tesseract(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "T" * 100)
        assert ocr_engines.ocr_page(object()) == "T" * 100

    def test_near_empty_ppocr_read_uses_tesseract(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: "abc")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "T" * 100)
        assert ocr_engines.ocr_page(object()) == "T" * 100

    def test_thin_page_keeps_tesseract_when_it_reads_more_numbers(self, monkeypatch):
        """The real sample_8 shape: PP-OCR under-segments, Tesseract does better."""
        ppocr = "Consultation charge and bed charge listed 1.00 2.00"
        tess = "Consultation 1.00 Bed 2.00 Lab 3.00 Pharmacy 4.00 Misc 5.00"
        # Precondition: thin enough for a second opinion, not a failed read.
        assert ocr_engines.OCR_MIN_CHARS <= len(ppocr) < ocr_engines.OCR_THIN_CHARS
        assert ocr_engines.numeric_tokens(tess) > ocr_engines.numeric_tokens(ppocr)

        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: ppocr)
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: tess)
        assert ocr_engines.ocr_page(object()) == tess

    def test_thin_page_keeps_ppocr_when_it_reads_more_numbers(self, monkeypatch):
        """The real sample_2 shape: Tesseract has more text, PP-OCR more amounts."""
        ppocr = "Consultation 1.00 Bed 2.00 Lab 3.00 Pharmacy 4.00 Misc 5.00"
        tess = "a considerably longer transcription carrying far fewer numeric tokens 1.00"
        assert ocr_engines.OCR_MIN_CHARS <= len(ppocr) < ocr_engines.OCR_THIN_CHARS
        assert len(tess) > len(ppocr)                                   # more text
        assert ocr_engines.numeric_tokens(ppocr) > ocr_engines.numeric_tokens(tess)  # fewer numbers

        monkeypatch.setattr(ocr_engines, "ocr_page_ppocr", lambda img: ppocr)
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: tess)
        assert ocr_engines.ocr_page(object()) == ppocr

    def test_thin_page_keeps_ppocr_when_tesseract_is_empty(self, monkeypatch):
        monkeypatch.setattr(
            ocr_engines, "ocr_page_ppocr",
            lambda img: "Consultation 1.00 Bed 2.00 Lab 3.00 Pharmacy 4.00")
        monkeypatch.setattr(ocr_engines, "ocr_page_tesseract", lambda img: "")
        assert ocr_engines.ocr_page(object()) == "Consultation 1.00 Bed 2.00 Lab 3.00 Pharmacy 4.00"

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


class TestNumericTokens:
    def test_counts_amounts(self):
        assert ocr_engines.numeric_tokens("BED CHARGE 1 No 1500.00 1380.00") == 3

    def test_handles_thousands_separators(self):
        assert ocr_engines.numeric_tokens("TOTAL 71,925.00") == 1

    def test_empty(self):
        assert ocr_engines.numeric_tokens("") == 0
        assert ocr_engines.numeric_tokens(None) == 0


class TestAutorotateGuards:
    """
    Regression cover for a flip that destroyed five pages of a real bill.

    OSD reported 180 on an already-upright hospital bill at confidence 5.86 --
    higher than several correct readings -- so confidence alone cannot be the
    guard. 90/270 stay trusted; 180 is opt-in.
    """

    class StubImage:
        def __init__(self): self.rotated_by = None
        def rotate(self, angle, expand=False):
            self.rotated_by = angle
            return self

    def _osd(self, monkeypatch, rotate, conf):
        monkeypatch.setattr(ocr_engines, "OCR_AUTOROTATE", True)
        monkeypatch.setattr(ocr_engines, "TESSERACT_AVAILABLE", True)
        monkeypatch.setattr(ocr_engines, "OCR_OSD_MIN_CONFIDENCE", 2.0)

        class FakeTess:
            class Output:
                DICT = "dict"

            @staticmethod
            def image_to_osd(img, output_type=None):
                return {"rotate": rotate, "orientation_conf": conf}

        monkeypatch.setattr(ocr_engines, "pytesseract", FakeTess)

    def test_270_is_applied(self, monkeypatch):
        self._osd(monkeypatch, 270, 6.60)
        img = self.StubImage()
        out, rot = ocr_engines.autorotate_page(img)
        assert rot == 270 and img.rotated_by == -270

    def test_90_is_applied(self, monkeypatch):
        self._osd(monkeypatch, 90, 3.0)
        img = self.StubImage()
        _, rot = ocr_engines.autorotate_page(img)
        assert rot == 90

    def test_180_is_ignored_even_at_high_confidence(self, monkeypatch):
        self._osd(monkeypatch, 180, 5.86)
        monkeypatch.setattr(ocr_engines, "OCR_AUTOROTATE_180", False)
        img = self.StubImage()
        out, rot = ocr_engines.autorotate_page(img)
        assert rot == 0 and img.rotated_by is None and out is img

    def test_180_applied_when_explicitly_enabled(self, monkeypatch):
        self._osd(monkeypatch, 180, 5.86)
        monkeypatch.setattr(ocr_engines, "OCR_AUTOROTATE_180", True)
        img = self.StubImage()
        _, rot = ocr_engines.autorotate_page(img)
        assert rot == 180

    def test_low_confidence_rotation_is_ignored(self, monkeypatch):
        self._osd(monkeypatch, 270, 0.5)
        img = self.StubImage()
        _, rot = ocr_engines.autorotate_page(img)
        assert rot == 0 and img.rotated_by is None

    def test_zero_rotation_is_a_no_op(self, monkeypatch):
        self._osd(monkeypatch, 0, 5.6)
        img = self.StubImage()
        out, rot = ocr_engines.autorotate_page(img)
        assert rot == 0 and out is img

    def test_osd_failure_leaves_page_untouched(self, monkeypatch):
        monkeypatch.setattr(ocr_engines, "OCR_AUTOROTATE", True)
        monkeypatch.setattr(ocr_engines, "TESSERACT_AVAILABLE", True)

        class Boom:
            class Output:
                DICT = "dict"

            @staticmethod
            def image_to_osd(img, output_type=None):
                raise RuntimeError("too few characters for OSD")

        monkeypatch.setattr(ocr_engines, "pytesseract", Boom)
        img = self.StubImage()
        out, rot = ocr_engines.autorotate_page(img)
        assert rot == 0 and out is img


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
