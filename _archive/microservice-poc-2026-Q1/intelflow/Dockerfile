FROM python:3.12-slim

WORKDIR /app

# Install shared library first
COPY ../../libs/svc-shared /tmp/svc-shared
RUN pip install --no-cache-dir /tmp/svc-shared && rm -rf /tmp/svc-shared

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY intelflow/ intelflow/
COPY config.py main.py ./

EXPOSE 10011
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10011"]
