#!/usr/bin/env bash
# ==============================================================================
# Vercel Build Script for DPIG (Django 5.1)
# Installs dependencies and collects static files into staticfiles/
# ==============================================================================
set -e

echo "==> [Vercel Build] Installing Python dependencies..."
# Use python3 -m pip install with --break-system-packages to bypass PEP 668 in Vercel build image
python3 -m pip install -r requirements.txt --break-system-packages

echo "==> [Vercel Build] Collecting static files..."
python3 manage.py collectstatic --noinput --clear

echo "==> [Vercel Build] Build completed successfully."
