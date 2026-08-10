#!/bin/sh
set -e
alembic upgrade head
exec supervisord -c /app/supervisord.conf -n
