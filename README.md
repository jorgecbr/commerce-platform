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
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Services

| Service | Stack | Responsibility |
|---|---|---|
| `orders-service` | Python 3.12 · FastAPI | Order lifecycle, pricing, payments |
| `inventory-service` | Java 21 · Spring Boot | Stock levels, reservations |

Each service owns its database. They never read each other's tables.

## Architecture

```mermaid
flowchart LR
    Client([Client])

    subgraph orders["orders-service · Python"]
        direction TB
        OAPI["REST API"]
        OAPP["Application<br/>use cases"]
        ODOM["Domain<br/>Order · Payment · Money"]
        OAPI --> OAPP --> ODOM
    end

    subgraph inv["inventory-service · Java"]
        direction TB
        IAPI["REST + Kafka"]
        IDOM["Stock reservations"]
        IAPI --> IDOM
    end

    Bus{{"Kafka"}}
    PG1[("PostgreSQL<br/>orders")]
    PG2[("PostgreSQL<br/>inventory")]
    Cache[("Redis")]

    Client -->|REST| OAPI
    OAPP --> PG1
    OAPP -.->|cache| Cache
    OAPP <-->|order events| Bus
    Bus <-->|stock events| IAPI
    IAPI --> PG2

    style ODOM fill:#1f6feb,color:#fff
    style IDOM fill:#6DB33F,color:#fff
    style Bus fill:#8b5cf6,color:#fff
```

### Inside `orders-service`

Three layers with the dependency rule pointing inwards:

```
app/
├── domain/         entities, value objects, invariants. Imports nothing.
├── application/    use cases and the ports they depend on
└── adapters/       http, db, cache, events
```

`domain/` imports nothing from the rest of the codebase — no ORM, no web
framework, no broker client. Business rules are therefore testable in
isolation and portable to another runtime without rewriting them.

## How an order flows

```mermaid
sequenceDiagram
    participant C as Client
    participant O as orders-service
    participant K as Kafka
    participant I as inventory-service

    C->>O: POST /orders
    O->>O: validate + persist order (PENDING)
    O->>O: write OrderPlaced to the outbox
    O->>O: commit
    O-->>C: 201 Created
    O->>K: relay publishes order.placed
    K->>I: order.placed
    I->>I: reserve stock
    I->>K: inventory.reserved
    K->>O: inventory.reserved
    O->>O: confirm order (CONFIRMED)
    O->>K: order.confirmed
    I->>I: commit the reservation
```

If stock is unavailable the inventory service emits `inventory.rejected` and
the order is cancelled instead, with the reservation released. The order
service owns the decision, so the flow is a saga orchestrated from one place
rather than spread across both services.

### Why the outbox

The order is written to PostgreSQL and the event is written to the **same
transaction**. A separate relay then publishes to Kafka. Publishing to the
broker first and committing to the database afterwards would allow an event
for an order that was never stored; the reverse order can lose the event but
the relay recovers it. See
[`app/adapters/db/outbox.py`](orders-service/app/adapters/db/outbox.py).

## Development

```shell
make up       # start PostgreSQL, Redis and Kafka
make run      # orders-service on :8000
make test     # full suite
make check    # lint + types + dependencies + tests
```

## Testing

```shell
cd orders-service
uv sync
uv run pytest
```

Unit tests cover the domain and the use cases with in-memory fakes and need
no running infrastructure. Integration tests run against containers.

## Documentation

- [`docs/architecture/c4-context.md`](docs/architecture/c4-context.md) — system context and ubiquitous language
- [`orders-service/README.md`](orders-service/README.md) — service internals

## License

MIT — see [LICENSE](LICENSE).