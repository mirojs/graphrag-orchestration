# Stage 1: Builder - Install all dependencies
FROM python:3.11-slim as builder

WORKDIR /tmp

# Install system dependencies needed for compilation
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install to user site packages
COPY requirements.txt .
# Copy local optional stubs used for base builds (e.g., graspologic stub)
COPY third_party/graspologic_stub third_party/graspologic_stub
# Upgrade pip to latest before installs to avoid resolver bugs on older pip
RUN pip install --upgrade pip --no-warn-script-location --root-user-action=ignore \
    && pip install --user --no-cache-dir --no-warn-script-location --root-user-action=ignore -r requirements.txt

# Stage 2: Runtime - Minimal final image
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed packages from builder (not build tools)
COPY --from=builder /root/.local /root/.local

# Create data directories
RUN mkdir -p /app/data/graphrag /app/data/lancedb /app/data/cache

# Copy application code
# Cache bust: 2025-12-16-optimization - Multi-stage build for smaller image
COPY . .

# Set PATH to use pip-installed packages from /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
