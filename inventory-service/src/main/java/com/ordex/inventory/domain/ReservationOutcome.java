package com.ordex.inventory.domain;

/**
 * Why stock can or cannot be set aside for an order.
 *
 * <p>The distinction is the whole point of the reservation pattern. "Reserve"
 * takes units out of availability without selling them; "release" puts them
 * back. Treating them as "subtract stock" and "add stock" loses the reason and
 * makes it impossible to explain a reservation that outlived its order.
 */
public enum ReservationOutcome {
    /** Every requested line had enough stock. */
    RESERVED,

    /** At least one line could not be satisfied, and nothing was reserved. */
    REJECTED
}