# Simple single-stage build for Green-But-Dead Detector
FROM python:3.11-slim

LABEL maintainer="sre-team"
LABEL description="Green-But-Dead Detector"

# Create non-root user
RUN useradd -m -u 1000 detector && mkdir -p /app/config

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=detector:detector src/ ./src/
COPY --chown=detector:detector config/*.example.yaml ./config/

# Set environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER detector

CMD ["python", "src/main.py"]
