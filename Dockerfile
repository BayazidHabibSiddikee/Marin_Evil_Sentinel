FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose the API port
EXPOSE 5090 5091

# Environment variables for database (adjust as needed)
ENV PG_HOST=localhost
ENV PG_PORT=5432
ENV PG_DB_NAME=postgres
ENV PG_USER=postgres
ENV PG_PASSWORD=postgres

# Make run.sh executable
RUN chmod +x run.sh

# Run both services
CMD ["./run.sh"]
