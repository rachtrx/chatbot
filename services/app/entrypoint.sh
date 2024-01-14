#!/bin/sh

set -e

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! pg_isready -h $SQL_HOST -p $SQL_PORT -q; do
      echo "Waiting for PostgreSQL to start..."
      sleep 1
  done

    echo "PostgreSQL started"
    echo "Creating the database tables..."
    flask create_db
    echo "Tables created"
fi

host="$1"
shift
cmd="$@"

# until curl -s --cacert /etc/chatbot/certs/ca/ca.crt -u elastic:"$ELASTIC_PASSWORD" https://"$host":9200/_cluster/health | grep -q '"status":"green"'; do
#   >&2 echo "Elasticsearch is unavailable - sleeping"
#   sleep 10
# done

# >&2 echo "Elasticsearch is up - executing command"


service cron start
echo "cron service started"

# flask create_new_index
# flask loop_files

exec $cmd