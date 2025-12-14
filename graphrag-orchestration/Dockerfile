FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
# Upgrade pip to latest before installs to avoid resolver bugs on older pip
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
# Cache bust: 2025-12-13-14:15 - DI integration with blob download fix
COPY . .

# Create data directories
RUN mkdir -p /app/data/graphrag /app/data/lancedb /app/data/cache

# Expose port (mapped to 8001 externally via docker-compose)
EXPOSE 8000

# Set Python to unbuffered mode for immediate logging
ENV PYTHONUNBUFFERED=1

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
