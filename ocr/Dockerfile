FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# onnxruntime and OpenMP both size their thread pools from the host CPU count,
# which on a small shared instance means many threads contending over one core.
ENV OMP_NUM_THREADS=2

# Use HTTPS for Debian repositories
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources

# poppler-utils   PDF -> image rendering
# tesseract-ocr   fallback OCR engine + the OSD model used for page rotation
# libgl1/libglib  required by opencv, which rapidocr depends on
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-osd \
    libgl1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Fail the build rather than the first request if the bundled PP-OCR weights
# are missing from the wheel.
RUN python -c "from pathlib import Path; import rapidocr; \
    models = list((Path(rapidocr.__file__).parent / 'models').glob('*.onnx')); \
    assert models, 'PP-OCR weights missing from the rapidocr wheel'; \
    print('bundled PP-OCR models:', [m.name for m in models])"

COPY app ./app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
