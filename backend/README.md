# MediData — AI-Powered Medical Bill Intelligence & Medicine Explorer

MediData is a modern health-tech web application that extracts structured items from hospital bills, pharmacy invoices, and prescriptions, cross-references active compounds against an 11,800+ clinical medicine dataset, and benchmarks real-time market prices.

---

## Key Features

- **Document Analysis**: Drag-and-drop ingestion of medical invoices (PDF, PNG, JPG, WEBP up to 15 MB).
- **Automated Classification**: Segregates line items into *Medicines*, *Lab Tests*, *Medical Devices*, and *Hospital Room/Doctor Services*.
- **Clinical Intelligence**: RapidFuzz fuzzy matching against 11,800+ pharmaceutical formulations with active compositions, therapeutic indications, side-effects, and manufacturers.
- **Market Price Comparison**: Real-time price and MRP benchmarking via 1mg API with calculated patient savings.
- **Live Medicine Explorer**: Debounced live search across brand names, active salt compositions, and clinical uses.
- **Interactive Modals & Analytics**: Detailed clinical profile drawers and financial summaries.
- **Secure Authentication**: User registration, login, profile management, and scan history.

---

## Architecture

```text
User Browser (Modern Health-Tech UI)
     │
     ├── HTTP / JSON ──► Django Web Application (Port 8000)
     │                     ├── Classifier & RapidFuzz Matcher (11.8k dataset)
     │                     ├── 1mg Real-Time Market Price Service
     │                     └── Postgres / SQLite Database Layer
     │                                │
     │                           HTTP │ Multipart Upload
     │                                ▼
     └──────────────────► FastAPI OCR Service (Port 8001)
                           ├── Tesseract OCR / PDF Plumber / Poppler
                           └── Gemini LLM Structured Extraction
```

---

## Prerequisites

- **Python 3.10+**
- **PostgreSQL** (or SQLite for local development)
- **FastAPI OCR Service** (optional for OCR bill analysis, located in `../Medical-Bill-Extract-main`)

---

## Quick Start

### 1. Environment Configuration

Create a `.env` file in the project root:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
OCR_API_URL=http://127.0.0.1:8001/extract-from-file

# Database (Leave blank to use local SQLite, or set for PostgreSQL/Neon)
PGDATABASE=neondb
PGUSER=neondb_owner
PGPASSWORD=your-postgres-password
PGHOST=your-postgres-host
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Migrations & Tests

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py test
```

### 4. Start Development Server

```bash
python manage.py runserver 8000
```

Access MediData in your browser at `http://127.0.0.1:8000/`.

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/analyse/` | Upload PDF/image bill for OCR extraction & clinical analysis |
| `GET` | `/api/medicines/search/?q={query}` | Autocomplete search across 11,800+ medicines |
| `GET` | `/api/medicines/detail/?name={name}` | Clinical profile & live 1mg price for a specific drug |
| `GET` | `/api/history/` | User's past analyzed bill documents |
| `POST` | `/register/` | User registration |
| `POST` | `/login/` | User authentication |

---

## License

This project is licensed under the MIT License.

