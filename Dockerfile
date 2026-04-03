FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and all required system dependencies in one step
RUN playwright install chromium --with-deps

COPY . .
