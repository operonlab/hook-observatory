FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY shared/ shared/
COPY invest/ invest/
COPY config.py main.py ./

EXPOSE 10012
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10012"]
