# inventory-service

Stock levels and reservations. Java 21 · Spring Boot 3 · Maven.

> Architecture and system-level context live in the [repository README](../README.md).

## Layout

```
src/main/java/com/ordex/inventory/
├── domain/            entities and business errors. No Spring annotations
│                       except the JPA mapping, and no knowledge of Kafka.
├── application/       use cases with transaction boundaries.
├── infrastructure/
│   ├── persistence/   Spring Data repositories
│   └── messaging/     Kafka listeners
└── web/               REST controllers and error translation.
```

The dependency arrow points inwards: `web` and `infrastructure` depend on
`application`, which depends on `domain`.

## Domain

`StockItem` is an entity with identity (the SKU) and one invariant:
`available >= 0`. The only way to change the count goes through
`reserve(int)`, which checks before it mutates, so an invalid state is not
representable from outside.

It carries a `@Version` column. Without optimistic locking, two concurrent
orders for the last unit both read `available = 1`, both write 0, and one
customer ends up with an order that cannot be shipped.

`ReservationService.reserve` is **all lines or nothing**. It runs in one
transaction, so a shortage on the last line rolls back the decrements already
applied by earlier ones. `release` is the compensating action used when the
order saga cancels.

## Messaging

| Topic | Direction | Payload |
|---|---|---|
| `orders.events` | consumed | `order.placed`, `order.cancelled` |
| `inventory.events` | published | `inventory.reserved`, `inventory.rejected` |

The listener answers with `reserved` or `rejected` and never publishes
`order.cancelled` itself: `orders-service` is the saga orchestrator and owns
the decision of what happens next.

A business rejection (`InsufficientStockException`, `UnknownSkuException`) is
logged and answered, not retried — retrying a shortage would never succeed.

Offsets are committed only after the handler returns (`enable-auto-commit:
false`, `ack-mode: record`), which gives at-least-once delivery.

## Database

Flyway owns the schema (`src/main/resources/db/migration`) and Hibernate runs
with `ddl-auto: validate`, so a migration that was forgotten is caught at boot
rather than at the first query.

The check constraint `available >= 0` repeats the domain invariant at the
database level, so a write that bypasses the domain cannot break it either.

## Build and test

```shell
mvn test           # unit tests, no infrastructure needed
mvn verify         # build the jar
mvn spring-boot:run  # run on :8080
```

```shell
curl localhost:8080/actuator/health
curl localhost:8080/stock/SKU-001
curl -X PUT localhost:8080/stock/SKU-009 -H 'content-type: application/json' \
     -d '{"available": 42}'
```