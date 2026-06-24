FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates fonts-liberation libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libcairo2 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium --with-deps

RUN useradd -m -u 1000 appuser \
    && cp -r /root/.cache /home/appuser/.cache \
    && chown -R appuser:appuser /home/appuser/.cache

# Increment CACHE_BUST to force Docker to copy fresh app files
ARG CACHE_BUST=9
COPY . .
RUN chown -R appuser:appuser /app

USER appuser

ENV PORT=7860
EXPOSE 7860

CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 1 app:app
