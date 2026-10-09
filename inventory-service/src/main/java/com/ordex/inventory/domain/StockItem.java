package com.ordex.inventory.domain;

import com.ordex.inventory.domain.error.InsufficientStockException;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

import java.util.Objects;

/**
 * Units of one product available to sell.
 *
 * <p>An entity: it has identity (the SKU), a lifecycle, and it changes. The
 * {@link Version} column gives it optimistic locking, so two concurrent orders
 * for the last unit cannot both succeed. Without it, both transactions read
 * "available = 1", both write 0, and one customer gets an order that cannot be
 * shipped.
 *
 * <p>Invariant, enforced in {@link #reserve}: {@code available >= 0}. It
 * cannot be violated from outside because the only way to change the count
 * goes through a method that checks first.
 */
@Entity
@Table(name = "stock_items")
public class StockItem {

    @Id
    @Column(name = "sku", nullable = false, length = 32)
    private String sku;

    @Column(name = "available", nullable = false)
    private int available;

    @Version
    @Column(name = "version", nullable = false)
    private long version;

    protected StockItem() {
        // Required by JPA.
    }

    public StockItem(String sku, int available) {
        if (sku == null || sku.isBlank()) {
            throw new IllegalArgumentException("sku must not be blank");
        }
        if (available < 0) {
            throw new IllegalArgumentException("available must not be negative");
        }
        this.sku = sku;
        this.available = available;
    }

    /** Units currently free to sell. */
    public int available() {
        return available;
    }

    public String sku() {
        return sku;
    }

    public boolean canSatisfy(int quantity) {
        return quantity > 0 && available >= quantity;
    }

    /**
     * Take units out of availability.
     *
     * @throws InsufficientStockException when the request cannot be met; the
     *     count is left untouched so a partial reservation never happens.
     */
    public void reserve(int quantity) {
        if (!canSatisfy(quantity)) {
            throw new InsufficientStockException(sku, quantity, available);
        }
        this.available -= quantity;
    }

    /** Return reserved units to availability. Used by the compensating action. */
    public void release(int quantity) {
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be positive");
        }
        this.available += quantity;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof StockItem item)) {
            return false;
        }
        return Objects.equals(sku, item.sku);
    }

    @Override
    public int hashCode() {
        return Objects.hash(sku);
    }
}