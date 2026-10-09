-- Initial schema for the inventory service.
--
-- Flyway owns the schema. The version column implements optimistic locking:
-- two concurrent orders for the last unit cannot both succeed, because the
-- second UPDATE matches no rows and Spring Data raises an
-- OptimisticLockingFailureException instead of silently overwriting.

CREATE TABLE stock_items (
    sku       VARCHAR(32) PRIMARY KEY,
    available INTEGER     NOT NULL,
    version   BIGINT      NOT NULL DEFAULT 0,
    CONSTRAINT ck_stock_available_non_negative CHECK (available >= 0)
);

-- The catalogue the smoke tests seed. A real deployment would have this fed
-- by the product service instead.
INSERT INTO stock_items (sku, available) VALUES
    ('SKU-001', 100),
    ('SKU-002', 50),
    ('SKU-003', 5),
    ('SKU-OUT-OF-STOCK', 0);