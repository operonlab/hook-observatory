# NOTE: system-monitor is designed for macOS hardware monitoring (psutil battery/disk,
# launchd scheduling). This Dockerfile supports Linux containers for the API-serve
# subset only (hardware metrics will be limited/unavailable without macOS psutil data).
# For full functionality, run natively on macOS via launchctl.

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required by psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.115 \
    uvicorn[standard]>=0.34 \
    psutil>=6.0 \
    pydantic>=2.10 \
    structlog>=24.4 \
    httpx>=0.28

# Copy application source
COPY . .

# Expose service port
EXPOSE 10102

# Start via __main__.py serve subcommand.
# Port is read from config.json "api.port" (default 9526) — override via --port flag.
CMD ["python", "-m", "__main__", "serve", "--host", "0.0.0.0", "--port", "10102"]
