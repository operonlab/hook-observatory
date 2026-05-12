FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files first for layer caching
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -r pyproject.toml 2>/dev/null || uv pip install --system .

# Copy application source
COPY . .

# Install the package itself
RUN uv pip install --system -e . --no-deps

# Expose service port
EXPOSE 10103

# Use AGENT_METRICS_HOST=0.0.0.0 so the container listens on all interfaces.
# pydantic-settings reads AGENT_METRICS_* env vars automatically (see config.py).
CMD ["python", "-m", "uvicorn", "agent_metrics.main:app", \
     "--host", "0.0.0.0", \
     "--port", "10103"]
