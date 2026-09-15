# MediData

MediData is an intelligent medical bill intelligence and medicine information platform. It empowers patients and healthcare consumers to upload hospital bills or pharmacy invoices (PDF or image formats), extract itemized billing lines with high precision using a hybrid OCR and AI pipeline, identify medicines, fetch comprehensive drug details (composition, indications, side effects, manufacturers), and cross-reference prices against market benchmarks to detect potential overcharges.

---

## Features

- **Medical Bill Upload**: Multi-format document ingestion supporting both multi-page PDFs and invoice images (PNG, JPG, JPEG, WEBP).
- **Hybrid OCR Pipeline**: High-accuracy text and document rendering powered by Poppler and Tesseract OCR.
- **Gemini-Powered Extraction**: State-of-the-art vision and structured data extraction leveraging Google Gemini via the modern `google-genai` SDK with automatic JSON recovery and fallbacks.
- **Medicine Extraction & Item Classification**: Automatic categorization of bill items into medicines, laboratory investigations, medical devices, and hospital services.
- **Medicine Matching & Information**: Rapid fuzzy matching against comprehensive medicine databases for verified composition, usage instructions, precautions, and side effects.
- **Price Comparison & Overcharge Detection**: Benchmarks bill items against market prices (e.g., 1mg marketplace data) to surface unit savings and price discrepancies.
- **Django Web Interface**: Responsive, interactive user interface and full backend application managing authentication, user history, bill processing, and price dashboards.
- **FastAPI OCR Service**: High-performance asynchronous microservice dedicated to bill conversion, OCR rendering, and AI extraction.
- **Docker Containerization**: Production-ready container image for the OCR service bundling Poppler, Tesseract, and Python dependencies.
- **Optional Redis Caching**: Scalable caching layer support for medicine lookup and query acceleration.

---

## Architecture

```
Browser (User Web Interface)
   │
   ▼
Django Backend + Frontend (Port 8000)
   │  • User authentication & scan history
   │  • Medicine fuzzy matching & details
   │  • Market price comparison (1mg)
   │
   ▼ (HTTP POST /extract-from-file)
FastAPI OCR Service (Port 8001)
   │
   ▼
Poppler (PDF to Image) + Tesseract (Pre-OCR Hints)
   │
   ▼
Google Gemini API (`google-genai` SDK)
   │  • Multimodal bill understanding
   │  • Structured line-item JSON extraction
   │  • Fraud and duplicate detection flags
```

---

## Repository Structure

```text
MediData/
├── backend/                       # Django full-stack web application
│   ├── manage.py                  # Django administrative CLI
│   ├── MediData/                  # Core application (models, views, services, templates, static)
│   │   ├── forms.py               # Form definitions (PDF upload, registration)
│   │   ├── models.py              # User profiles & AnalysisResult models
│   │   ├── services/              # Medicine matcher, classifier, and 1mg integration
│   │   │   ├── classifier.py      # Item category classifier
│   │   │   ├── comparator.py      # Price comparison logic
│   │   │   ├── medicine_matcher.py# RapidFuzz dataset lookup
│   │   │   └── onemg.py           # 1mg API integration
│   │   ├── static/                # CSS, JavaScript, icons
│   │   ├── templates/             # HTML templates (home, auth, dashboard)
│   │   ├── tests.py               # Unit and integration test suite
│   │   ├── urls.py                # App routing
│   │   └── views.py               # Bill upload & analysis orchestration
│   ├── myproject/                 # Django project settings & WSGI/ASGI configuration
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── datasets/                  # Medicine dataset (Medicine_Details.csv)
│   ├── requirements.txt           # Python dependencies for Django backend
│   └── .env.example               # Backend environment variables template
│
├── ocr/                           # FastAPI OCR & Gemini extraction microservice
│   ├── app/                       # FastAPI application package
│   │   ├── main.py                # FastAPI endpoints (/health, /extract-from-file)
│   │   ├── extractor.py           # Pipeline: PDF -> Images -> OCR -> Gemini -> JSON
│   │   └── schemas.py             # Pydantic data schemas & response contracts
│   ├── tests/                     # Unit and API test suite (pytest)
│   │   └── test_api.py
│   ├── Dockerfile                 # Multi-stage image with Poppler + Tesseract
│   ├── render.yaml                # Render deployment blueprint
│   ├── requirements.txt           # Python dependencies for OCR service
│   └── .env.example               # OCR environment variables template
│
├── .gitignore                     # Repository-wide ignore rules
└── README.md                      # Project documentation
```

---

## Environment Variables

> **IMPORTANT**: Never commit real secret keys or API keys to version control. Copy `.env.example` to `.env` in each service directory and configure your local settings.

### Backend (`backend/.env`)

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `SECRET_KEY` | Django cryptographic secret key | *(Required in production)* |
| `DEBUG` | Enable Django debug mode (`True`/`False`) | `True` |
| `ALLOWED_HOSTS` | Comma-separated list of permitted host headers | `localhost,127.0.0.1` |
| `OCR_API_URL` | Endpoint to the running FastAPI OCR service | `http://127.0.0.1:8001/extract-from-file` |
| `CSRF_TRUSTED_ORIGINS`| Allowed origins for CSRF protection | `http://localhost:8000,http://127.0.0.1:8000` |
| `PGHOST` | *(Optional)* PostgreSQL database host | `localhost` |
| `PGDATABASE` | *(Optional)* PostgreSQL database name | `medidata` |
| `PGUSER` | *(Optional)* PostgreSQL database user | `postgres` |
| `PGPASSWORD` | *(Optional)* PostgreSQL database password | *(Secret)* |
| `PGPORT` | *(Optional)* PostgreSQL port | `5432` |
| `REDIS_URL` | *(Optional)* Redis server connection URL | `redis://127.0.0.1:6379/1` |

### OCR Service (`ocr/.env`)

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `GOOGLE_API_KEY` | Google Gemini API key | *(Required for AI extraction)* |
| `GEMINI_MODEL` | Primary Gemini model ID | `gemini-2.5-flash` |
| `GEMINI_MODEL_FALLBACKS` | Comma-separated fallback models | `gemini-1.5-flash` |
| `MAX_RETRIES` | Max retry attempts for API calls | `2` |
| `BATCH_SIZE` | Page processing batch size | `3` |
| `PDF_DPI` | Rasterization resolution for PDF pages | `200` |
| `TESSERACT_CMD` | Explicit path to `tesseract` binary (Windows) | *(Optional if in PATH)* |
| `POPPLER_PATH` | Explicit path to Poppler `bin` directory (Windows) | *(Optional if in PATH)* |
| `USE_MOCK_MODE` | Mock Gemini calls with stub data for offline tests | `false` |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins | `http://127.0.0.1:8000,http://localhost:8000` |

---

## Running the OCR Service

### Option A: Local Python Environment

1. Navigate to the `ocr/` directory:
   ```bash
   cd ocr
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Ensure Poppler and Tesseract OCR are installed on your host system and added to your PATH (or configured in `ocr/.env`).
5. Copy configuration and populate variables:
   ```bash
   cp .env.example .env
   ```
6. Start the FastAPI server on port 8001:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```
7. Verify health:
   ```bash
   curl http://127.0.0.1:8001/health
   ```

### Option B: Running OCR with Docker (Recommended)

Docker automatically packages all system dependencies (Poppler, Tesseract OCR, and Python libraries) into a reproducible container:

1. Build the Docker image from the repository root:
   ```bash
   docker build -t medidata-ocr ./ocr
   ```
2. Run the container mapping host port 8001 to container port 8000:
   ```bash
   docker run --rm --name medidata-ocr -p 8001:8000 --env-file ./ocr/.env medidata-ocr
   ```

---

## Running the Django Application

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy environment configuration:
   ```bash
   cp .env.example .env
   ```
5. Apply database migrations:
   ```bash
   python manage.py migrate
   ```
6. Start the development server:
   ```bash
   python manage.py runserver 127.0.0.1:8000
   ```
7. Open `http://127.0.0.1:8000` in your web browser.

---

## Testing

### Django Tests
Run the Django automated test suite (verifying services, classifier, fuzzy matcher, forms, and views):
```bash
cd backend
python manage.py test
```

### OCR Service Tests
Run the FastAPI and extraction test suite:
```bash
cd ocr
python -m pytest -q
```

