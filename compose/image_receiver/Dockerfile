FROM python:3.13.7-slim

WORKDIR /app

# Install required tools and Microsoft ODBC Driver 17 for SQL Server
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gnupg \
        curl \
        ca-certificates \
        apt-transport-https && \
    curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql17 \
        unixodbc && \
    rm -rf /var/lib/apt/lists/*

COPY ./src/image_ingestion_service/image_receiver/requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src/image_ingestion_service/image_receiver /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
