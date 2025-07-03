FROM python:3.11-slim

WORKDIR /app

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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
