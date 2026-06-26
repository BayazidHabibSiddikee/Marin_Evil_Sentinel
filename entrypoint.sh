#!/bin/sh
# Fix permissions on mounted volumes before starting (runs as root)
chown -R 1000:1000 /app/books /app/code /app/storage /app/static 2>/dev/null || true
chmod -R 775 /app/books 2>/dev/null || true

# Run both services
exec ./run.sh
