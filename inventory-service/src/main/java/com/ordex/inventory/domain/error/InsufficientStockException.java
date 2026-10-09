package com.ordex.inventory.domain.error;

/** Not enough stock to satisfy a reservation. Carries the numbers so the caller can report them. */
public class InsufficientStockException extends RuntimeException {

    private final String sku;
    private final int requested;
    private final int available;

    public InsufficientStockException(String sku, int requested, int available) {
        super("Cannot reserve " + requested + " of " + sku + ", only " + available + " available");
        this.sku = sku;
        this.requested = requested;
        this.available = available;
    }

    public String sku() {
        return sku;
    }

    public int requested() {
        return requested;
    }

    public int available() {
        return available;
    }
}
