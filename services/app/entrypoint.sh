#!/bin/bash

set -e

# printenv > /etc/environment
# export PYTHONPATH="$FLASK_APP_DIR:$PYTHONPATH"

echo "SQL USER: " $SQL_USER
echo "SQL HOST: " $SQL_HOST
echo "FLASK_APP_DIR: $cd ${FLASK_APP_DIR}"

while ! pg_isready -h $SQL_HOST -p $SQL_PORT -q; do
    echo "Waiting for postgrew..."
    sleep 1
done

echo "PostgreSQL started"
echo "LIVE: $LIVE"

# Check if the 'chatbot' database exists
if psql -h $SQL_HOST -U $SQL_USER -lqt | cut -d \| -f 1 | grep -qw "chatbot"; then
    echo "Database 'chatbot' already exists"
else
    echo "Database 'chatbot' does not exist. Creating..."
    psql -h $SQL_HOST -U $SQL_USER -c "CREATE DATABASE chatbot"
fi

cd ${FLASK_APP_DIR}
# alembic revision --autogenerate -m "${NEW_MIGRATION_MESSAGE}" # IMPT RUN URSELF FIRST!
# alembic upgrade 55183dbfb8e4
# python3 ./alembic/scripts/data_migration.py
# alembic upgrade 5ee15a07d356
echo "Migrations complete."

host="$1"
shift
cmd="$@"

# until curl -s --cacert /etc/chatbot/certs/ca/ca.crt -u elastic:"$ELASTIC_PASSWORD" https://"$host":9200/_cluster/health | grep -q '"status":"green"'; do
#   >&2 echo "Elasticsearch is unavailable - sleeping"
#   sleep 10
# done

# >&2 echo "Elasticsearch is up - starting server"

exec $cmd