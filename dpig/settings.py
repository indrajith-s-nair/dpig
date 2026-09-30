"""
Django settings for Digital Public Infrastructure Governance (DPIG) project.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-dpig-core-secret-2026')

DEBUG = os.getenv('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')
ENABLE_DEMO_ROLE_SWITCHER = os.getenv('ENABLE_DEMO_ROLE_SWITCHER', 'True' if DEBUG else 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]

# Firebase Hosting & Cloud Run Reverse Proxy Configuration
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

default_csrf_origins = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    'https://*.vercel.app',
    'https://*.web.app',
    'https://*.firebaseapp.com',
    'https://*.run.app',
    'https://*.repl.co',
    'https://*.replit.app',
    'https://*.replit.dev',
]
csrf_env = os.getenv('CSRF_TRUSTED_ORIGINS')
if csrf_env:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_env.split(',') if origin.strip()]
    for origin in default_csrf_origins:
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)
else:
    CSRF_TRUSTED_ORIGINS = default_csrf_origins

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'dpig.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.app_global_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'dpig.wsgi.application'
ASGI_APPLICATION = 'dpig.asgi.application'

# Database configuration: Cloud SQL PostgreSQL, DATABASE_URL, or SQLite fallback
DATABASE_URL = os.getenv('DATABASE_URL')
CLOUD_SQL_CONNECTION_NAME = os.getenv('CLOUD_SQL_CONNECTION_NAME')

DB_ENGINE = os.getenv('DB_ENGINE', 'django.db.backends.postgresql')
DB_NAME = os.getenv('POSTGRES_DB', 'dpig_db')
DB_USER = os.getenv('POSTGRES_USER', 'dpig_user')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'dpig_secure_pass_2026')
DB_HOST = os.getenv('POSTGRES_HOST', 'localhost')
DB_PORT = os.getenv('POSTGRES_PORT', '5432')

if DATABASE_URL:
    try:
        import dj_database_url
        DATABASES = {
            'default': dj_database_url.config(
                default=DATABASE_URL,
                conn_max_age=600,
                ssl_require=True if 'sslmode=require' in DATABASE_URL else False
            )
        }
        USE_SQLITE = False
    except ImportError:
        import urllib.parse
        parsed_db = urllib.parse.urlparse(DATABASE_URL)
        DB_ENGINE = 'django.db.backends.postgresql'
        DB_NAME = parsed_db.path.lstrip('/')
        DB_USER = parsed_db.username or ''
        DB_PASSWORD = urllib.parse.unquote(parsed_db.password or '')
        DB_HOST = parsed_db.hostname or ''
        DB_PORT = str(parsed_db.port or '5432')
        db_options = {}
        if parsed_db.query:
            query_params = urllib.parse.parse_qs(parsed_db.query)
            if 'sslmode' in query_params:
                db_options['sslmode'] = query_params['sslmode'][0]
        db_config = {
            'ENGINE': DB_ENGINE,
            'NAME': DB_NAME,
            'USER': DB_USER,
            'PASSWORD': DB_PASSWORD,
            'HOST': DB_HOST,
        }
        if DB_PORT:
            db_config['PORT'] = DB_PORT
        if db_options:
            db_config['OPTIONS'] = db_options
        DATABASES = {'default': db_config}
        USE_SQLITE = False
elif CLOUD_SQL_CONNECTION_NAME:
    # Cloud SQL Unix domain socket on Cloud Run
    DB_HOST = f'/cloudsql/{CLOUD_SQL_CONNECTION_NAME}'
    DB_PORT = ''
    USE_SQLITE = False
else:
    USE_SQLITE_ENV = os.getenv('USE_SQLITE')
    if USE_SQLITE_ENV is not None:
        USE_SQLITE = USE_SQLITE_ENV.lower() in ('true', '1')
    else:
        USE_SQLITE = (DB_HOST in ('localhost', '127.0.0.1')) and not os.path.exists('/.dockerenv')


if USE_SQLITE:
    sqlite_path = os.getenv('SQLITE_PATH')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': Path(sqlite_path) if sqlite_path else (BASE_DIR / 'db.sqlite3'),
        }
    }
else:
    db_config = {
        'ENGINE': DB_ENGINE,
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
    }
    if DB_PORT:
        db_config['PORT'] = DB_PORT
    DATABASES = {'default': db_config}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email Configuration from .env
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Digital Public Infrastructure Portal <indrajith.nair.s@gmail.com>')
NOTIFICATION_FALLBACK_EMAIL = os.getenv('NOTIFICATION_FALLBACK_EMAIL', 'indrajith.nair.s@gmail.com')

# Google Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')

# Google Maps Platform
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Celery Configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Periodic tasks (Beat Schedule)
CELERY_BEAT_SCHEDULE = {
    'check-sla-breaches-every-5-mins': {
        'task': 'core.tasks.monitor_sla_deadlines_task',
        'schedule': 300.0,
    },
    'refresh-policymaker-insights-hourly': {
        'task': 'core.tasks.refresh_policymaker_insights_task',
        'schedule': 3600.0,
    },
}

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Production / Staging Security Headers
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# Static files storage with Whitenoise
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False

# CSRF & Session Cookie Settings
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
CSRF_COOKIE_PATH = '/'
SESSION_COOKIE_PATH = '/'

# Internal API Secret for Machine-to-Machine & Webhook Ingestion (n8n, bots, cron)
INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')


