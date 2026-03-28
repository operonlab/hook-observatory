FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY shared/ shared/
COPY intelflow/ intelflow/
COPY config.py main.py ./

EXPOSE 10011
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10011"]
