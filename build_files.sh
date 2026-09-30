#!/usr/bin/env bash
# ==============================================================================
# Vercel Build Script for DPIG (Django 5.1)
# Installs dependencies and collects static files into staticfiles/
# ==============================================================================
set -e

echo "==> [Vercel Build] Installing Python dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "==> [Vercel Build] Collecting static files..."
python3 manage.py collectstatic --noinput --clear

echo "==> [Vercel Build] Build completed successfully."
