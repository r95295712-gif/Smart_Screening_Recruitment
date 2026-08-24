FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    build-essential \
    libpq-dev \
    openssl \
    postgresql-client \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/base.txt /app/requirements/base.txt
RUN pip install --no-cache-dir -r /app/requirements/base.txt

COPY . /app
RUN chmod +x /app/docker/entrypoint.sh /app/docker/backup/backup.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
