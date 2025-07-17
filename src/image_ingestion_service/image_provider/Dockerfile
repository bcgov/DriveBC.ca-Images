FROM python:3.11-slim


# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg2 apt-transport-https && \
    curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 unixodbc-dev gcc g++ && \
    apt-get clean && \ 
    rm -rf /var/lib/apt/lists/*


WORKDIR /app

RUN mkdir -p /app/ReplayTheDay/json && chmod 777 /app/ReplayTheDay/json


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Add non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY app ./app

# Create directory + set permissions
RUN mkdir -p /app/app/images/webcams/originals && \
    mkdir -p /app/app/images/webcams/watermarked && \
    chown -R appuser:appgroup /app/app/images/webcams/originals && \
    chown -R appuser:appgroup /app/app/images/webcams/watermarked && \
    chmod -R 775 /app/app/images/webcams


# Switch to non-root user
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
