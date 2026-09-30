"""
DPIG Django Celery initialization
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dpig.settings')

app = Celery('dpig')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
