#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER docker;
    CREATE DATABASE postgres_fun;
    GRANT ALL PRIVILEGES ON DATABASE postgres_fun TO docker;
    CREATE DATABASE postgres_fun_test;
    GRANT ALL PRIVILEGES ON DATABASE postgres_fun_test TO docker;
EOSQL