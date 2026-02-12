FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY doi_metadata/ doi_metadata/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "doi_metadata.api:app", "--host", "0.0.0.0", "--port", "8000"]
