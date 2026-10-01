web: ./docker-entrypoint.sh
worker: celery -A dpig worker -l INFO --concurrency=2
beat: celery -A dpig beat -l INFO
