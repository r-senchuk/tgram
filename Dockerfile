# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies including SQLite with JSON1 extension
RUN apt-get update && apt-get install -y \
    sqlite3 \
    libsqlite3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Make main.py executable
RUN chmod +x main.py

# Set main.py as default entrypoint with flexible command handling
ENTRYPOINT ["python", "main.py"]
CMD []
