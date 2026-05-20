# ─── Estágio 1: builder ─────────────────────────────────────
# Lector
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements.txt


# ─── Estágio 2: runtime ──────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="lector"
LABEL description="Lector — leitor local de PDFs e Jupyter Notebooks"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-por \
    tesseract-ocr-eng \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Copia o pacote app/ inteiro
COPY app/ ./app/

RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Aponta para app/main.py → objeto `app`
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
