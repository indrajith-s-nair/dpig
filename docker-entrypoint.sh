#!/bin/bash
set -e

PORT="${PORT:-8080}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"

echo "==> [DPIG] Starting container with PORT=${PORT}..."

# 1. Database readiness check
if [ "${USE_SQLITE}" = "True" ] || [ "${USE_SQLITE}" = "true" ] || [ "${USE_SQLITE}" = "1" ]; then
    echo "==> [DPIG] Running with SQLite database engine."
else
    # Only wait for TCP connection if host is not a unix domain socket (e.g. Cloud SQL socket)
    PG_HOST="${POSTGRES_HOST:-db}"
    if [ -n "${PG_HOST}" ] && [[ "${PG_HOST}" != /* ]]; then
        echo "==> [DPIG] Verifying PostgreSQL connection to ${PG_HOST}:${POSTGRES_PORT:-5432}..."
        RETRIES=15
        until python -c "
import os, sys, psycopg2
try:
    psycopg2.connect(
        dbname=os.environ.get('POSTGRES_DB', 'dpig_db'),
        user=os.environ.get('POSTGRES_USER', 'dpig_user'),
        password=os.environ.get('POSTGRES_PASSWORD', 'dpig_secure_pass_2026'),
        host=os.environ.get('POSTGRES_HOST', 'db'),
        port=os.environ.get('POSTGRES_PORT', '5432')
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null || [ $RETRIES -le 0 ]; do
            echo "Waiting for PostgreSQL ($RETRIES retries left)..."
            RETRIES=$((RETRIES-1))
            sleep 2
        done
        if [ $RETRIES -le 0 ]; then
            echo "Warning: Database check timed out. Proceeding anyway..."
        else
            echo "==> [DPIG] PostgreSQL database is ready."
        fi
    else
        echo "==> [DPIG] Using Unix domain socket / Cloud SQL for database connectivity."
    fi
fi

# 2. Database migrations
if [ "${RUN_MIGRATIONS}" = "true" ] || [ "${RUN_MIGRATIONS}" = "1" ] || [ "$1" = "gunicorn" ] || [ "$2" = "runserver" ] || [ $# -eq 0 ]; then
    echo "==> [DPIG] Applying database migrations..."
    python manage.py migrate --noinput

    if [ "${SEED_DEMO_DATA}" = "true" ] || [ "${SEED_DEMO_DATA}" = "1" ]; then
        echo "==> [DPIG] Seeding demo cluster (SEED_DEMO_DATA=true)..."
        python manage.py seed_gcc || true
    fi
else
    echo "==> [DPIG] Skipping migrations on auxiliary container ($1)..."
fi

# 3. Ensure media and static storage directories exist
mkdir -p /app/staticfiles /app/media

# 4. Command execution
if [ $# -eq 0 ]; then
    echo "==> [DPIG] Launching Gunicorn server on 0.0.0.0:${PORT}..."
    exec gunicorn \
        --bind "0.0.0.0:${PORT}" \
        --workers "${WEB_CONCURRENCY}" \
        --threads 4 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        dpig.wsgi:application
else
    echo "==> [DPIG] Executing service command: $@"
    exec "$@"
fi
