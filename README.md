# Commerce Platform

Order management for an online store. Handles the order lifecycle from
checkout to shipment, coordinates stock reservation with the inventory
service, and guarantees that state changes and published events stay
consistent.

[![CI](https://github.com/jorgecbr/commerce-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/jorgecbr/commerce-platform/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Java 21](https://img.shields.io/badge/java-21-ED8B00?logo=openjdk&logoColor=white)](https://openjdk.org/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3-6DB33F?logo=springboot&logoColor=white)](https://spring.io/projects/spring-boot)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Kafka](https://img.shields.io/badge/Kafka-3.9-231F20?logo=apachekafka&logoColor=white)](https://kafka.apache.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Services

| Service | Stack | Responsibility |
|---|---|---|
| `orders-service` | Python 3.12 · FastAPI | Order lifecycle, pricing, payments, saga orchestration |
| `inventory-service` | Java 21 · Spring Boot | Stock levels, reservations |

Each service owns its own database and never reads the other's tables. The
only contract between them is the events published to Kafka.

## Architecture

```mermaid
flowchart LR
    Client([Client])

    subgraph orders["orders-service · Python"]
        direction TB
        OAPI["REST API"]
        OAPP["Application<br/>use cases · saga"]
        ODOM["Domain<br/>Order · Payment · Money"]
        OOUT["Adapters<br/>SQLAlchemy · Redis · Kafka"]
        OAPI --> OAPP --> ODOM
        OOUT --> OAPP
    end

    subgraph inv["inventory-service · Java"]
        direction TB
        IAPI["REST"]
        IAPP["ReservationService"]
        IDOM["StockItem"]
        IAPI --> IAPP --> IDOM
    end

    Bus{{"Kafka"}}
    PG1[("PostgreSQL<br/>orders")]
    PG2[("PostgreSQL<br/>inventory")]
    Cache[("Redis")]

    Client -->|REST| OAPI
    OOUT --> PG1
    OOUT -.->|cache| Cache
    OOUT -->|order.placed<br/>order.cancelled| Bus
    Bus -->|consume| IAPI
    IAPI -->|inventory.reserved<br/>inventory.rejected| Bus
    Bus -->|consume| OOUT
    IAPP --> PG2

    style ODOM fill:#1f6feb,color:#fff
    style IDOM fill:#6DB33F,color:#fff
    style Bus fill:#8b5cf6,color:#fff
```

### Inside `orders-service`

```
app/
├── domain/         entities, value objects, invariants. Imports nothing.
├── application/    use cases, ports, saga decisions
└── adapters/       http, db, cache, events
```

`domain/` imports nothing from the rest of the codebase — no ORM, no web
framework, no broker client. The business rules are therefore testable in
isolation and portable to another runtime without rewriting them.

## How an order flows

```mermaid
sequenceDiagram
    participant C as Client
    participant O as orders-service
    participant K as Kafka
    participant I as inventory-service

    C->>O: POST /orders
    O->>O: validate + persist order (pending)
    O->>O: write OrderPlaced to the outbox
    O->>O: commit
    O-->>C: 201 Created
    O->>K: relay publishes order.placed
    K->>I: order.placed
    I->>I: reserve stock
    I->>K: inventory.reserved
    K->>O: inventory.reserved
    O->>O: saga decides CONFIRMED
    O->>O: confirm order + write OrderConfirmed to outbox
    O->>K: relay publishes order.confirmed
```

When stock is unavailable the inventory service emits `inventory.rejected`
and the saga cancels the order instead, which in turn releases any reservation
already made. `orders-service` owns the decision, so the flow stays readable
in one place rather than spread across every event handler.

## The two problems this design solves

### Publishing an event without losing it

Writing to the database and writing to the broker are two separate systems.
Publishing first and committing second allows an event for an order that was
never stored. Committing first and publishing second can drop the event if the
process dies in between.

Both the order and its `OrderPlaced` event are written in **one
transaction**. A relay then moves outbox rows to Kafka and marks them
published. If the relay dies mid-batch, the row is still unpublished and the
event is sent again.

### Receiving the same event twice

The relay is at-least-once on purpose, so consumers must be idempotent. Each
consumer inserts the message id into an inbox table **before** doing the work;
a duplicate insert fails, and the message is skipped. Inserting after the work
would leave a window where a crash causes the effect to happen twice.

## Data model notes

**Money is stored in minor units.** Amounts are integers, never floats, and the
currency travels with the amount so `Money(1000, "USD") + Money(500, "EUR")`
raises instead of producing a wrong total. Zero-decimal currencies (JPY) and
three-decimal ones (KWD) are handled.

**The order lifecycle is a transition table.** `ALLOWED_TRANSITIONS` maps each
status to the statuses reachable from it, so an illegal transition is not a
branch you can forget to update.

**Optimistic concurrency on both sides.** The `orders` table carries a
`version`; the UPDATE includes the loaded version and a zero row count means
another transaction won. `stock_items` does the same, which is what stops two
orders for the last unit from both succeeding.

## Development

```shell
make up          # PostgreSQL, Redis, Kafka
make migrate     # apply migrations
make run         # orders-service on :8000
make run-java    # inventory-service on :8080
make check       # lint, types, dependencies, tests
```

Seed stock and place an order:

```shell
curl -X PUT localhost:8080/stock/SKU-001 -H 'content-type: application/json' \
     -d '{"available": 100}'

curl -X POST localhost:8000/orders -H 'content-type: application/json' -d '{
  "customer_id": "customer-42",
  "lines": [{"sku": "SKU-001", "quantity": 2, "unit_price": "10.00", "currency": "USD"}]
}'
```

Watch the saga complete:

```shell
docker compose logs -f inventory-service
```

## Testing

```shell
make test              # everything
make test-unit         # no infrastructure required
make test-integration  # needs PostgreSQL, Redis and Kafka
cd inventory-service && mvn test
```

Unit tests cover the domain and the use cases with in-memory fakes, so the
Python suite runs in about a second without any container. Integration tests
run against real PostgreSQL and a real Kafka broker and cover the guarantees
unit tests cannot: that the SQL is valid, that a lost update is rejected, that
the order and its event share a transaction, and that a message delivered
twice is handled once.

| Suite | What it runs |
|---|---|
| `orders-service` | pytest, 130 tests |
| `inventory-service` | JUnit 5, 15 tests |

Integration tests skip themselves when the infrastructure is not reachable,
so a developer without Docker still gets a green local run.

## Documentation

- [`docs/architecture/c4-context.md`](docs/architecture/c4-context.md) — system context and ubiquitous language
- [`orders-service/README.md`](orders-service/README.md) — Python internals
- [`inventory-service/README.md`](inventory-service/README.md) — Java internals

## License

MIT — see [LICENSE](LICENSE).