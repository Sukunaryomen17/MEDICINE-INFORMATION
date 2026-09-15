import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.extractor import BillExtractor
from app.schemas import ExtractionResponse

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

app = FastAPI(
    title="Medical Bill Extractor API",
    description=(
        "Extracts structured line items from hospital "
        "bills and invoices using a hybrid OCR + LLM pipeline."
    ),
    version="2.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


extractor = BillExtractor()


@app.get("/health")
async def health():

    return {
        "status": "ok",
        "version": "2.0.0",
        "model": os.getenv(
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        ),
    }


@app.post(
    "/extract-from-file",
    response_model=ExtractionResponse,
)
async def extract_from_file(
    file: UploadFile = File(...),
):
    """
    Accept a multipart PDF/image upload
    and extract structured bill line items.
    """

    suffix = (
        Path(file.filename).suffix.lower()
        if file.filename
        else ".pdf"
    )

    allowed_extensions = {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    if suffix not in allowed_extensions:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {suffix}. "
                f"Allowed: {', '.join(sorted(allowed_extensions))}"
            ),
        )

    content = await file.read(MAX_UPLOAD_BYTES + 1)

    if not content:

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Uploaded file exceeds the configured size limit.",
        )

    tmp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as tmp:

            tmp.write(content)

            tmp_path = tmp.name

        result = extractor.extract(
            tmp_path
        )

        return result

    finally:

        if tmp_path:

            try:
                os.unlink(tmp_path)

            except FileNotFoundError:
                pass

            except OSError:
                pass
