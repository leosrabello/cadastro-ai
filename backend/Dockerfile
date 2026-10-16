FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# LibreOffice (no GUI) converts Word and Excel uploads to PDF; Liberation fonts keep their layout
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por fonts-dejavu-core \
    libreoffice-writer-nogui libreoffice-calc-nogui fonts-liberation2 \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home /srv app
WORKDIR /srv

COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; print('\n'.join(p['dependencies'] + p['optional-dependencies']['dev']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt
COPY . .

RUN mkdir -p /data/documents /watch && chown -R app:app /data /watch
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
