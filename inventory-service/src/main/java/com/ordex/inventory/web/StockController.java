package com.ordex.inventory.web;

import com.ordex.inventory.application.ReservationService;
import com.ordex.inventory.domain.StockItem;
import com.ordex.inventory.infrastructure.persistence.StockItemRepository;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Read and write access to stock levels. */
@RestController
@RequestMapping("/stock")
public class StockController {

    private final StockItemRepository repository;
    private final ReservationService reservations;

    public StockController(StockItemRepository repository, ReservationService reservations) {
        this.repository = repository;
        this.reservations = reservations;
    }

    /** Current availability for one SKU. */
    @GetMapping("/{sku}")
    public StockItem bySku(@PathVariable String sku) {
        return repository.findBySku(sku)
                .orElseThrow(() -> new StockNotFoundException(sku));
    }

    /** Every tracked SKU. */
    @GetMapping
    public List<StockItem> all() {
        return repository.findAll();
    }

    /** Set the available units for a SKU, creating the item if needed. */
    @PutMapping("/{sku}")
    public StockItem setStock(@PathVariable String sku, @RequestBody Map<String, Integer> body) {
        int available = body.getOrDefault("available", 0);
        return repository.save(new StockItem(sku, available));
    }

    /**
     * Reserve units directly, outside an order flow. Used by the smoke tests
     * and by the support tooling; the normal path is the Kafka listener.
     */
    @PostMapping("/{sku}/reserve")
    public ResponseEntity<Void> reserve(@PathVariable String sku, @RequestBody Map<String, Integer> body) {
        int quantity = body.getOrDefault("quantity", 0);
        reservations.reserve(UUID.randomUUID(), List.of(new ReservationService.Line(sku, quantity)));
        return ResponseEntity.noContent().build();
    }

    @ExceptionHandler(StockNotFoundException.class)
    public ResponseEntity<Map<String, String>> notFound(StockNotFoundException exc) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("error", "stock-not-found", "detail", exc.getMessage()));
    }

    @ExceptionHandler(com.ordex.inventory.domain.error.InsufficientStockException.class)
    public ResponseEntity<Map<String, Object>> insufficient(
            com.ordex.inventory.domain.error.InsufficientStockException exc) {
        return ResponseEntity.badRequest().body(Map.of(
                "error", "insufficient-stock",
                "sku", exc.sku(),
                "requested", exc.requested(),
                "available", exc.available()));
    }

    /** Thrown when a SKU is not in the catalogue. */
    static class StockNotFoundException extends RuntimeException {
        StockNotFoundException(String sku) {
            super("Unknown SKU: " + sku);
        }
    }
}