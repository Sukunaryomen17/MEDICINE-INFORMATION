# MediData: A Medical Invoice Analyser

Production-ready FastAPI service that extracts structured line items from hospital bills and invoices using a **hybrid OCR + Gemini multimodal pipeline**.

Built for the **Byterverse Hackathon 2026**.

---

## Architecture

```
PDF / Image
    │
    ▼
pdf2image (poppler)          ← Render each page at configurable DPI
    │
    ▼
Pillow image enhancement     ← Contrast / sharpness boost
    │
    ├──▶ Tesseract OSD       ← Correct 90° page rotation (both engines + model)
    │
    ├──▶ PP-OCR (onnxruntime) ← Primary OCR; rows rebuilt from bounding boxes
    │      └─ falls back to ─▶ Tesseract --psm 6 (confidence-gated)
    │
    ▼
Gemini 2.5 Flash (multimodal) ← Page image + OCR hint → structured JSON
    │
    ├── Retry + fallback model list (quota resilience)
    ├── Batch pages to reduce API calls
    │
    ▼
Deduplication logic          ← Suppress Bill Summary when Detail pages exist
    │
    ▼
ExtractionResponse JSON
```

---

## Response Schema

```json
{
  "is_success": true,
  "token_usage": {
    "total_tokens": 1234,
    "input_tokens": 1000,
    "output_tokens": 234
  },
  "data": {
    "pagewise_line_items": [
      {
        "page_no": "1",
        "page_type": "Bill Detail",
        "bill_items": [
          {
            "item_name": "BED CHARGE GENERAL WARD",
            "item_amount": 1500.00,
            "item_rate": 1500.00,
            "item_quantity": 1.0
          }
        ]
      }
    ],
    "total_item_count": 42,
    "grand_total": 73420.25
  },
  "error": null
}
```

`page_type` values: `Bill Summary` | `Bill Detail` | `Pharmacy Bill` | `Lab Bill` | `Other`

---

## Setup

### 1. System dependencies

```bash
# Ubuntu / Debian
sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin

# macOS
brew install poppler tesseract
```

### 2. Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY
```

### 4. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: [http://localhost:8000/docs](http://13.206.108.88:8000/docs)

Frontend: [https://medical-bill-extract-2ashatbzcxn9fkhejaxboe.streamlit.app/](https://medical-bill-extract-2ashatbzcxn9fkhejaxboe.streamlit.app/)

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| POST | `/extract-from-file` | Extract from file upload |

### Extract from file

```bash
curl -X POST http://localhost:8000/extract-from-file \
  -F "file=@/path/to/bill.pdf"
```

---

## Testing

```bash
# Fast (no API key needed – mock mode)
pytest -q

# With real API
USE_MOCK_MODE=false pytest -q -m integration
```

---

## Docker

```bash
docker build -t medidata-ocr .
docker run --rm -p 8001:8000 --env-file .env medidata-ocr
```

---

## Memory footprint

PP-OCR is the memory-hungry part of the service. Measured on a 200 DPI page:

| Stage | Resident |
| :--- | ---: |
| Baseline | 28 MB |
| After `import rapidocr` | 79 MB |
| After model load | 168 MB |
| During first page inference | 609 MB |
| Steady state, 3 pages | 757 MB |

Capping `OMP_NUM_THREADS` and disabling the onnxruntime arena did not reduce
the peak. **A 512 MB instance will be OOM-killed mid-request.** Options, in
order of preference:

1. Size the instance at 1 GB or more and run `OCR_ENGINE=ppocr`.
2. Keep a 512 MB instance and set `OCR_ENGINE=tesseract`. The service works
   unchanged; it only loses PP-OCR's advantage on photographed and handwritten
   bills. `OCR_AUTOROTATE` still applies and still helps Tesseract.
3. Lower `PDF_DPI` to 150, which cuts the detection input size and the peak
   along with it, at some cost to recognition on small print.

PP-OCR was *faster* than Tesseract on every sample page (5.4s vs 7.1s, 5.7s vs
9.1s, 2.8s vs 3.5s, 3.6s vs 3.7s), so this is a memory trade, not a latency one.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | — | **Required.** Google AI API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Primary model |
| `GEMINI_MODEL_FALLBACKS` | empty | Optional supported fallback models |
| `MAX_RETRIES` | `2` | Bounded retries for rate-limit failures |
| `BATCH_SIZE` | `3` | Pages per Gemini API call |
| `PDF_DPI` | `200` | DPI for PDF rendering |
| `OCR_ENGINE` | `ppocr` | `ppocr` (PP-OCR first, Tesseract fallback) or `tesseract` (Tesseract only) |
| `USE_OCR_HINT` | `true` | Set `false` to skip OCR; the model still receives the page image |
| `OCR_MAX_CHARS` | `6000` | Hint budget per page |
| `OCR_MIN_CONFIDENCE` | `35` | Tesseract only: mean word confidence below which the hint is dropped |
| `OCR_REC_MIN_SCORE` | `0.5` | PP-OCR only: discard detections recognised below this score |
| `OCR_MIN_CHARS` | `40` | PP-OCR only: below this yield, the page is retried with Tesseract |
| `OCR_THIN_CHARS` | `800` | PP-OCR only: below this, Tesseract runs as a second opinion; the transcription with more numeric tokens wins |
| `OCR_MIN_WORDS` | `40` | Tesseract only: a hint is dropped only if confidence is low *and* fewer words than this were read |
| `OCR_AUTOROTATE_180` | `false` | Apply 180° flips. Off by default — OSD cannot tell 0 from 180 reliably on forms |
| `OCR_OSD_MIN_CONFIDENCE` | `2.0` | Ignore orientation calls below this confidence |
| `OCR_ROW_Y_TOL` | `0.6` | Row grouping tolerance, as a multiple of median detection height |
| `OCR_ROW_GAP` | `0.75` | Horizontal gap rendered as a column break, same units |
| `OCR_AUTOROTATE` | `true` | Correct 90° page rotation via Tesseract OSD |
| `TESSERACT_CMD` | empty | Optional local Windows Tesseract path; leave empty in Docker |
| `POPPLER_PATH` | empty | Optional local Windows Poppler path; leave empty in Docker |
| `MAX_UPLOAD_BYTES` | `20971520` | Maximum upload size in bytes |
| `USE_MOCK_MODE` | `false` | Return dummy data (no API calls) |
| `CORS_ORIGINS` | `http://127.0.0.1:8000,http://localhost:8000` | Comma-separated Django origins allowed to call the API |

---

## Differentiators

1. **Multimodal extraction** — Page images are sent directly to Gemini so it can read tables, handwriting, stamps, and rotated text that OCR alone misses.
2. **Two OCR engines, chosen per page** — PP-OCRv6 (run on onnxruntime, weights bundled in the wheel) reads the page first; any page it reads poorly falls back to Tesseract. Measured on the sample bills: on a rotated handwritten pharmacy bill Tesseract returned noise (`ov`, `3 8 0`, `a b`) at mean confidence 43, where PP-OCR recovered the full column header row.
3. **Rows rebuilt from bounding boxes** — PP-OCR detects cells, not table rows, so joining its output with newlines shreds `BLOOD SUGAR BY GLUCOMETER  13/11/25  1 No  80.00  73.60` into five fragments. Grouping detections by vertical centre restores the row, which is the association the model most needs. 187 detections → 44 rows on a printed hospital bill.
4. **Calibrated quality gate** — Tesseract's mean word confidence tracks page quality (73.9 / 87.2 / 43.0 / 84.3 across the samples); PP-OCR's recognition scores do not (98.7 / 98.6 / 91.2 / 99.2 on the same pages, including the one it read badly). The Tesseract path is therefore gated on confidence and the PP-OCR path on yield.
3. **Fraud detection** — Gemini is prompted to flag mismatched fonts, white-out over text, and rate × quantity mismatches.
4. **Anti-double-counting** — Bill Summary pages are automatically suppressed when Detail pages are present.
5. **Multilingual support** — Tesseract with Hindi (`hin`) language pack handles bilingual bills.
6. **Quota resilience** — Automatic retry with exponential back-off + model fallback list.
7. **Pre-processing** — Contrast enhancement and median filtering improve OCR quality on low-quality scans.

---

## Project Structure

```
.
├── app/
│   ├── main.py        # FastAPI routes
│   ├── extractor.py   # Core pipeline (render + Gemini + aggregation)
│   ├── ocr_engines.py # PP-OCR / Tesseract engines, row rebuild, autorotate
│   └── schemas.py     # Pydantic models
├── tests/
│   └── test_api.py    # Unit + API tests
├── Dockerfile
├── render.yaml
├── requirements.txt
├── pytest.ini
└── .env.example
```
