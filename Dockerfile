# Production / Staging Dockerfile for Digital Public Infrastructure Governance (DPIG)
# Compatible with Google Cloud Run, Firebase Hosting rewrites, and Docker Compose
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install runtime curl and libpq for healthchecks and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . /app/
RUN chmod +x /app/docker-entrypoint.sh

# Pre-collect static files during container build
RUN mkdir -p /app/staticfiles /app/media
RUN USE_SQLITE=True python manage.py collectstatic --noinput || true

EXPOSE 8080
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD []
