FROM python:3.10-slim

# Added dumb-init and required system dependencies for Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg libglib2.0-0 libnss3 libfontconfig1 \
    libxss1 libasound2 libxtst6 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
    libdrm2 libxcomposite1 libxrandr2 libxdamage1 libx11-xcb1 libxcb1 \
    libx11-6 libxext6 libxfixes3 libdbus-glib-1-2 fonts-liberation \
    dumb-init \
    && apt-get clean

WORKDIR /app

# Pre-create cache directory to ensure permissions
RUN mkdir -p /app/chrome_cache

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY noon_api.py .

EXPOSE 5000

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["python", "noon_api.py"]
