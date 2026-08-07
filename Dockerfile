FROM python:3.13-slim

# Install PostgreSQL client + system deps
RUN apt-get update && apt-get install -y -qq \
    postgresql-client \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Firefox browser (required for AJIO scraping) + system deps
RUN python3 -m playwright install --with-deps firefox \
    && rm -rf /var/lib/apt/lists/*

# Copy app
COPY . .

# Make scripts executable
RUN chmod +x setup.sh

EXPOSE 5000

# Default: run the web dashboard
CMD ["python3", "app.py", "--host", "0.0.0.0", "--port", "5000"]
