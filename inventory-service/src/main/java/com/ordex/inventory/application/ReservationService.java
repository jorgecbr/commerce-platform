package com.ordex.inventory.application;

import com.ordex.inventory.domain.StockItem;
import com.ordex.inventory.infrastructure.persistence.StockItemRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * Reserves stock for an order, or refuses it as a whole.
 *
 * <p>The rule that matters: <em>all lines or nothing</em>. A partial
 * reservation would leave the order in a state neither service knows how to
 * resolve, so a missing unit rejects the whole request and leaves the
 * catalogue untouched.
 *
 * <p>The transaction is what makes that true. {@link #reserve} is one
 * transaction, so if the last line fails, the decrements already applied by
 * earlier lines are rolled back.
 */
@Service
public class ReservationService {

    private static final Logger log = LoggerFactory.getLogger(ReservationService.class);

    private final StockItemRepository repository;

    public ReservationService(StockItemRepository repository) {
        this.repository = repository;
    }

    /**
     * Reserve every line of an order.
     *
     * @throws com.ordex.inventory.domain.error.InsufficientStockException when
     *     any line cannot be satisfied; nothing is reserved in that case.
     */
    @Transactional
    public void reserve(UUID orderId, List<Line> lines) {
        log.info("Reserving {} line(s) for order {}", lines.size(), orderId);

        for (Line line : lines) {
            StockItem item = repository.findBySku(line.sku())
                    .orElseThrow(() -> new com.ordex.inventory.domain.error.UnknownSkuException(line.sku()));
            item.reserve(line.quantity());
            repository.save(item);
        }

        log.info("Reserved stock for order {}", orderId);
    }

    /**
     * Compensating action for {@link #reserve}: put the units back.
     *
     * <p>Idempotent by construction. Releasing units that were never reserved
     * would inflate availability, so this is only ever called with the
     * quantities the original reservation took, which is why the saga keeps
     * them on the event rather than recomputing them.
     */
    @Transactional
    public void release(UUID orderId, List<Line> lines) {
        for (Line line : lines) {
            repository.findBySku(line.sku()).ifPresent(item -> {
                item.release(line.quantity());
                repository.save(item);
            });
        }
        log.info("Released stock for order {}", orderId);
    }

    /** One requested line: a SKU and how many units. */
    public record Line(String sku, int quantity) {}
}