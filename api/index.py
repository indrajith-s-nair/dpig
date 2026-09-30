"""
Vercel Serverless Function Entrypoint for DPIG.
Exposes the WSGI application callable `app` to Vercel's Python Serverless Runtime.
"""
import os
import sys
from pathlib import Path

# Ensure project root directory is on Python search path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dpig.settings')

from dpig.wsgi import app
