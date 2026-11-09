# SPDX-License-Identifier: AGPL-3.0-or-later
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_THREAD_LIMIT=1 \
    TRACKER_DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY LICENSE ./

RUN useradd --system --uid 1000 --home /data tracker && mkdir -p /data && chown tracker /data
USER tracker
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

# Behind a reverse proxy set FORWARDED_ALLOW_IPS to the proxy address so https is detected.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
