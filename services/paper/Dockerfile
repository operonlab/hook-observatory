FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project definition first (layer caching)
COPY pyproject.toml .
RUN uv pip install --system .

# Copy source code
COPY src/ src/

EXPOSE 10010
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "10010"]
