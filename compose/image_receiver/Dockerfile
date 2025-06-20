FROM python:3.12-slim

WORKDIR /app

# Install unixODBC system package (required by pyodbc)
RUN apt-get update && \
    apt-get install -y --no-install-recommends unixodbc && \
    rm -rf /var/lib/apt/lists/*

COPY ./src/image_ingestion_service/image_receiver/requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src/image_ingestion_service/image_receiver /app 

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
