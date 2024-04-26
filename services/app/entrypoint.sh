#!/bin/bash

set -e

printenv > /etc/environment

export PYTHONPATH="$FLASK_APP_DIR:$PYTHONPATH"

echo "SQL USER: " $SQL_USER
echo "SQL HOST: " $SQL_HOST

while ! pg_isready -h $SQL_HOST -p $SQL_PORT -q; do
    echo "Waiting for postgrew..."
    sleep 1
done

echo "PostgreSQL started"

# Check if the 'chatbot' database exists
if psql -h $SQL_HOST -U $SQL_USER -lqt | cut -d \| -f 1 | grep -qw "chatbot"; then
    echo "Database 'chatbot' already exists"
else
    echo "Database 'chatbot' does not exist. Creating..."
    psql -h $SQL_HOST -U $SQL_USER -c "CREATE DATABASE chatbot"
fi

cd ${FLASK_APP_DIR}
# alembic revision --autogenerate -m "${NEW_MIGRATION_MESSAGE}" # IMPT RUN URSELF FIRST!
alembic upgrade head
echo "Migrations complete."

host="$1"
shift
cmd="$@"

# until curl -s --cacert /etc/chatbot/certs/ca/ca.crt -u elastic:"$ELASTIC_PASSWORD" https://"$host":9200/_cluster/health | grep -q '"status":"green"'; do
#   >&2 echo "Elasticsearch is unavailable - sleeping"
#   sleep 10
# done

# >&2 echo "Elasticsearch is up - executing command"

flask setup_azure

service cron start
echo "cron service started"

# flask create_new_index
# flask loop_files

exec $cmd