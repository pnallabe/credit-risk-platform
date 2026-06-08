#!/bin/sh
set -e

# Create credit_risk database in postgres server
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    CREATE DATABASE credit_risk;
EOSQL

echo "✅ Database 'credit_risk' created successfully."

# Initialize credit_risk with schema.sql
if [ -f /tmp/schemas/schema.sql ]; then
    echo "Initializing credit_risk database..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "credit_risk" -f /tmp/schemas/schema.sql
fi

# Initialize agent sessions in credit_risk (converting SQLite autoincrement syntax to Postgres SERIAL syntax)
if [ -f /tmp/schemas/002_agent_sessions.sql ]; then
    echo "Translating and running agent session tables to credit_risk..."
    sed 's/INTEGER PRIMARY KEY AUTOINCREMENT/SERIAL PRIMARY KEY/g' /tmp/schemas/002_agent_sessions.sql > /tmp/agent_sessions_pg.sql
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "credit_risk" -f /tmp/agent_sessions_pg.sql
    rm -f /tmp/agent_sessions_pg.sql
fi

# Initialize credit_risk_loans with schema_loans.sql (default POSTGRES_DB)
if [ -f /tmp/schemas/schema_loans.sql ]; then
    echo "Initializing credit_risk_loans database..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "credit_risk_loans" -f /tmp/schemas/schema_loans.sql
fi

echo "✅ All databases initialized successfully."
