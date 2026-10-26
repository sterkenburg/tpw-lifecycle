# TPW Lifecycle Platform — Cloud Run
# Supports both Streamlit dashboard and FastAPI via environment variable

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates gcc libc6-dev && rm -rf /var/lib/apt/lists/*
ENV GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
COPY security/ /opt/security/
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /opt/security/requirements-runtime.txt
RUN pip install --no-deps --no-build-isolation -e .
RUN python -I /opt/security/repair_brotli.py && python -I /opt/security/verify_runtime.py

# Copy source
COPY config/ config/
COPY src/ src/
COPY jobs/ jobs/

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Default: run FastAPI API
# Override with: docker run -e APP_MODE=dashboard ...
ENV APP_MODE=api
ENV PORT=8080

EXPOSE 8080

CMD if [ "$APP_MODE" = "dashboard" ]; then \
        streamlit run src/dashboard/app.py \
            --server.port=$PORT \
            --server.address=0.0.0.0 \
            --server.headless=true \
            --server.enableCORS=false; \
    else \
        uvicorn src.api.main:app \
            --host 0.0.0.0 \
            --port $PORT; \
    fi
