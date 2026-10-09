package com.ordex.inventory.domain.error;

/** The catalogue has no item with this SKU. */
public class UnknownSkuException extends RuntimeException {

    public UnknownSkuException(String sku) {
        super("Unknown SKU: " + sku);
    }
}
