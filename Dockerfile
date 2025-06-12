# Multi-stage build for smaller final image
FROM ubuntu:22.04 as base

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install system dependencies in a single layer
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    gnupg \
    unzip \
    curl \
    jq \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Google Chrome in separate layer for better caching
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google-chrome-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# === PYTHON DEPENDENCIES STAGE ===
FROM base as python-deps

# Create symlink for python
RUN ln -s /usr/bin/python3 /usr/bin/python

# Upgrade pip in separate layer
RUN python -m pip install --upgrade pip

# Copy requirements first for better Docker layer caching
COPY requirements.txt /tmp/requirements.txt

# Install Python packages with optimizations
RUN pip install --no-cache-dir \
    --disable-pip-version-check \
    -r /tmp/requirements.txt \
    && python -c "import seleniumbase; import requests; import selenium; import pandas; print('All packages imported successfully')"

# === FINAL STAGE ===
FROM python-deps as final

# Set environment variables for Chrome
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROME_PATH=/usr/bin/google-chrome
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create working directory
WORKDIR /workspace

# Create runner user but don't switch to it (GitHub Actions will handle this)
RUN useradd -m -s /bin/bash runner \
    && chown -R runner:runner /workspace

# Pre-warm Python imports to speed up first run
RUN python -c "import seleniumbase, requests, json, time, sys, os" || true

# Set the default command
CMD ["/bin/bash"] 
