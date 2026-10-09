package com.ordex.inventory.domain;

import com.ordex.inventory.domain.error.InsufficientStockException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("StockItem")
class StockItemTest {

    @Test
    @DisplayName("reservation takes units out of availability")
    void reserveReducesAvailability() {
        var item = new StockItem("SKU-001", 10);

        item.reserve(3);

        assertThat(item.available()).isEqualTo(7);
    }

    @Test
    @DisplayName("reservation cannot take more than is available")
    void reserveRejectsMoreThanAvailable() {
        var item = new StockItem("SKU-001", 2);

        assertThatThrownBy(() -> item.reserve(3))
                .isInstanceOf(InsufficientStockException.class)
                .hasMessageContaining("only 2 available");
    }

    @Test
    @DisplayName("a refused reservation leaves availability untouched")
    void failedReservationIsAtomic() {
        var item = new StockItem("SKU-001", 2);

        assertThatThrownBy(() -> item.reserve(5)).isInstanceOf(InsufficientStockException.class);

        // Nothing was taken: a partial reservation would leave the order in a
        // state neither service knows how to resolve.
        assertThat(item.available()).isEqualTo(2);
    }

    @Test
    @DisplayName("quantity must be positive")
    void rejectsNonPositiveQuantity() {
        var item = new StockItem("SKU-001", 10);

        assertThatThrownBy(() -> item.reserve(0)).isInstanceOf(InsufficientStockException.class);
        assertThatThrownBy(() -> item.reserve(-1)).isInstanceOf(InsufficientStockException.class);
    }

    @Test
    @DisplayName("release puts reserved units back")
    void releaseRestoresAvailability() {
        var item = new StockItem("SKU-001", 10);
        item.reserve(4);

        item.release(4);

        assertThat(item.available()).isEqualTo(10);
    }

    @Test
    @DisplayName("release and reserve cancel each other out")
    void releaseCompensatesReserve() {
        var item = new StockItem("SKU-001", 10);

        item.reserve(6);
        item.release(6);

        assertThat(item.available()).isEqualTo(10);
    }

    @Test
    @DisplayName("initial availability cannot be negative")
    void rejectsNegativeInitialStock() {
        assertThatThrownBy(() -> new StockItem("SKU-001", -1))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("a SKU cannot be blank")
    void rejectsBlankSku() {
        assertThatThrownBy(() -> new StockItem("  ", 10))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("identity is the SKU, not the amount")
    void identityIsSku() {
        assertThat(new StockItem("SKU-001", 10))
                .isEqualTo(new StockItem("SKU-001", 99))
                .hasSameHashCodeAs(new StockItem("SKU-001", 99))
                .isNotEqualTo(new StockItem("SKU-002", 10));
    }
}