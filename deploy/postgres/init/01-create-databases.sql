-- Runs once, when the postgres container initialises its data directory.
--
-- Each service owns its database. inventory-service never reads the orders
-- tables: the two agree on Kafka events, which is the only contract between
-- them. Sharing one database would make that boundary a convention rather
-- than a guarantee.

SELECT 'CREATE DATABASE orders'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'orders')\gexec

SELECT 'CREATE DATABASE inventory'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'inventory')\gexec