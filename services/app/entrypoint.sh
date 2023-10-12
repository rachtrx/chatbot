#!/bin/sh

service cron start
echo "cron service started"

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! nc -z $SQL_HOST $SQL_PORT; do
      sleep 0.1
    done

    echo "PostgreSQL started"
fi

if [ "$DATABASE" = "sqlite" ]
then
    echo "Creating the database tables..."
    flask create_db
    echo "Tables created"
fi

exec "$@"