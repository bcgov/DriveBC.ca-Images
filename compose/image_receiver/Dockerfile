# ---------- Stage 1: Build with dependencies ----------
FROM python:3.12-alpine AS builder

WORKDIR /build

# Install build dependencies and FreeTDS headers
RUN apk add --no-cache g++ gcc musl-dev unixodbc-dev freetds-dev

# Copy and build Python wheels
COPY ./src/image_ingestion_service/image_receiver/requirements.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ---------- Stage 2: Minimal runtime image ----------
FROM python:3.12-alpine

WORKDIR /app

# Install runtime dependencies: FreeTDS + ODBC runtime libs
RUN apk add --no-cache libstdc++ unixodbc freetds

# Copy wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*

# Copy application code
COPY ./src/image_ingestion_service/image_receiver /app

# Run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
