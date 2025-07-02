FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Add non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY app ./app

# Switch to non-root user
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
