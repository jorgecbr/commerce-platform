package com.ordex.inventory.infrastructure.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ordex.inventory.application.ReservationService;
import com.ordex.inventory.domain.error.InsufficientStockException;
import com.ordex.inventory.domain.error.UnknownSkuException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Consumes {@code order.placed} and answers with {@code inventory.reserved}
 * or {@code inventory.rejected}.
 *
 * <p>This is the reactive half of the saga; orders-service is the orchestrator
 * and owns the decision of what happens next. This service only reports what
 * it could or could not do, and never publishes {@code order.cancelled}
 * itself: one component deciding keeps the flow readable.
 */
@Component
public class OrderPlacedListener {

    private static final Logger log = LoggerFactory.getLogger(OrderPlacedListener.class);

    private static final String ORDERS_TOPIC = "orders.events";
    private static final String INVENTORY_TOPIC = "inventory.events";

    private final ReservationService reservations;
    private final KafkaTemplate<String, String> kafka;
    private final ObjectMapper mapper = new ObjectMapper();

    public OrderPlacedListener(ReservationService reservations, KafkaTemplate<String, String> kafka) {
        this.reservations = reservations;
        this.kafka = kafka;
    }

    @KafkaListener(topics = ORDERS_TOPIC, groupId = "${app.kafka.consumer-group:inventory-service}")
    @Transactional
    public void onOrderPlaced(String message) throws Exception {
        JsonNode payload = mapper.readTree(message);

        if (!"order.placed".equals(payload.path("event_type").asText())) {
            return;
        }

        UUID orderId = UUID.fromString(payload.path("order_id").asText());
        List<ReservationService.Line> lines = parseLines(payload);

        try {
            reservations.reserve(orderId, lines);
            publish(orderId, "inventory.reserved", "inventory.reserved", payload);
        } catch (InsufficientStockException | UnknownSkuException exc) {
            // A business rejection is not an error: it is the expected answer
            // when stock ran out. Retrying it would never succeed.
            log.info("Order {} rejected: {}", orderId, exc.getMessage());
            publish(orderId, "inventory.rejected", "inventory.rejected", payload);
        }
    }

    @KafkaListener(topics = INVENTORY_TOPIC, groupId = "${app.kafka.consumer-group:inventory-service}")
    @Transactional
    public void onOrderCancelled(String message) throws Exception {
        JsonNode payload = mapper.readTree(message);

        if (!"order.cancelled".equals(payload.path("event_type").asText())) {
            return;
        }

        UUID orderId = UUID.fromString(payload.path("order_id").asText());
        List<ReservationService.Line> lines = parseLines(payload);

        // The compensating action: whatever was reserved goes back.
        reservations.release(orderId, lines);
        log.info("Released stock for cancelled order {}", orderId);
    }

    private List<ReservationService.Line> parseLines(JsonNode payload) {
        List<ReservationService.Line> lines = new ArrayList<>();
        JsonNode array = payload.path("lines");
        for (JsonNode line : array) {
            lines.add(new ReservationService.Line(
                    line.path("sku").asText(),
                    line.path("quantity").asInt()));
        }
        return lines;
    }

    private void publish(UUID orderId, String eventType, String typeName, JsonNode original) {
        var node = mapper.createObjectNode();
        node.put("event_type", eventType);
        node.put("order_id", orderId.toString());
        node.put("reason", typeName.equals("inventory.rejected") ? "insufficient_stock" : "");
        node.set("lines", original.path("lines"));
        node.put("occurred_at", java.time.Instant.now().toString());

        // Keyed by order id so all events about one order keep their order
        // across partitions.
        kafka.send(INVENTORY_TOPIC, orderId.toString(), node.toString());
    }
}