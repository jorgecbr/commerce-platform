#!/usr/bin/env bash
#
# End-to-end verification of the order saga.
#
# Unit tests prove each layer in isolation. This proves the seam between the
# two services, which is where the real bugs live: an event that omits a field
# its consumer needs will pass every unit test in the repository and still
# break the flow.
#
# Two journeys are checked:
#
#   1. Happy path   order placed -> stock reserved -> order confirmed
#   2. Compensation no stock     -> order cancelled  -> nothing reserved
#
# The second one is the reason the saga exists. A system that only proves the
# happy path proves nothing about distributed consistency.
#
# Exits non-zero on the first failed expectation, so CI fails loudly.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API="http://localhost:8000"
RESERVED_SKU="SKU-001"
REJECTED_SKU="SKU-OUT-OF-STOCK"

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

query() {
    docker compose exec -T postgres psql -U orders -d "$1" -tAc "$2" 2>/dev/null | tr -d ' \r'
}

order_status() { query orders "select status from orders where id = '$1'"; }

stock() { query inventory "select available from stock_items where sku = '$1'"; }

# The API is reached over the published port when the host can route to
# containers, and from inside the compose network when it cannot. Some
# virtualised environments block host-to-container traffic entirely, and the
# check should still run there rather than report a false failure.
api_reachable() { curl -sS -m 5 -o /dev/null "$API/health/live" 2>/dev/null; }

place_order() {
    local body="{\"customer_id\":\"$1\",\"lines\":[{\"sku\":\"$2\",\"quantity\":$3,\"unit_price\":\"10.00\",\"currency\":\"USD\"}]}"
    if api_reachable; then
        curl -sS -m 30 -X POST "$API/orders" -H 'content-type: application/json' -d "$body"
    else
        docker compose exec -T orders-service curl -sS -m 30 -X POST "$API/orders" \
            -H 'content-type: application/json' -d "$body"
    fi
}

# Polls until the order leaves PENDING. Distributed work takes time, and a
# fixed sleep is either slow or flaky.
await_status() {
    local order_id="$1" expected="$2" other="${3:-}"
    for _ in $(seq 1 30); do
        local current
        current="$(order_status "$order_id" || true)"
        if [ "$current" = "$expected" ]; then
            return 0
        fi
        if [ -n "$other" ] && [ "$current" = "$other" ]; then
            return 1
        fi
        sleep 2
    done
    return 1
}

# --------------------------------------------------------------------------
step "0. Stack must be running"
# --------------------------------------------------------------------------
for service in postgres redis kafka orders-service orders-worker inventory-service; do
    status="$(docker compose ps --format "{{.Service}}:{{.Status}}" "$service" 2>/dev/null || true)"
    case "$status" in
        *healthy*|*Up*) pass "$service" ;;
        *) fail "$service is not running. Start it with: make up" ;;
    esac
done

# Migrations must have been applied, otherwise every later step fails for a
# reason that has nothing to do with the saga.
[ -n "$(query orders 'select tablename from pg_tables where tablename = '\''orders'\''')" ] \
    || fail "orders table missing. Run: make migrate"
pass "schema applied"

# --------------------------------------------------------------------------
step "1. Happy path: order -> stock reserved -> order confirmed"
# --------------------------------------------------------------------------
before="$(stock "$RESERVED_SKU")"
[ -n "$before" ] || fail "cannot read stock for $RESERVED_SKU"
printf '  stock before: %s\n' "$before"

response="$(place_order "verify-happy" "$RESERVED_SKU" 3)"
order_id="$(printf '%s' "$response" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])' 2>/dev/null || true)"
[ -n "$order_id" ] || fail "POST /orders did not return an id: $response"
printf '  order id: %s\n' "$order_id"

[ "$(order_status "$order_id")" = "pending" ] || fail "a new order must start pending"
pass "order created and pending"

await_status "$order_id" "confirmed" "cancelled" \
    || fail "order never reached 'confirmed' (stuck at '$(order_status "$order_id")')"
pass "saga confirmed the order"

after="$(stock "$RESERVED_SKU")"
[ "$after" = "$((before - 3))" ] \
    || fail "stock should be $((before - 3)) after ordering 3 units, found $after"
pass "inventory service reserved 3 units ($before -> $after)"

published="$(query orders "select count(*) from outbox_events where aggregate_id = '$order_id' and published_at is not null")"
[ "$published" -ge 2 ] || fail "expected at least 2 published events, found $published"
pass "outbox published both events"

seen="$(query orders "select count(*) from processed_messages")"
[ "$seen" -ge 1 ] || fail "the saga consumer recorded nothing"
pass "saga consumer registered the message in its inbox"

# --------------------------------------------------------------------------
step "2. Compensation: no stock -> order cancelled -> nothing reserved"
# --------------------------------------------------------------------------
reserved_before="$(stock "$RESERVED_SKU")"

response="$(place_order "verify-compensation" "$REJECTED_SKU" 5)"
order_id="$(printf '%s' "$response" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])' 2>/dev/null || true)"
[ -n "$order_id" ] || fail "POST /orders did not return an id: $response"
printf '  order id: %s (sku %s has 0 units)\n' "$order_id" "$REJECTED_SKU"

await_status "$order_id" "cancelled" "confirmed" \
    || fail "order never reached 'cancelled' (stuck at '$(order_status "$order_id")')"
pass "saga cancelled the order instead of confirming it"

reserved_after="$(stock "$RESERVED_SKU")"
[ "$reserved_after" = "$reserved_before" ] \
    || fail "an unrelated sku changed from $reserved_before to $reserved_after"
pass "no stock was wrongly reserved"

cancelled_event="$(query orders "select count(*) from outbox_events where aggregate_id = '$order_id' and event_type = 'order.cancelled'")"
[ "$cancelled_event" -ge 1 ] || fail "no order.cancelled event was published"
pass "order.cancelled published for the compensating action"

# --------------------------------------------------------------------------
step "3. Every journey behaved as expected"
# --------------------------------------------------------------------------
printf '\n  happy path       order -> reserved %s units -> confirmed\n' 3
printf '  compensation     order -> no stock  -> cancelled, nothing reserved\n\n'
printf '\033[32mThe saga works end to end.\033[0m\n'