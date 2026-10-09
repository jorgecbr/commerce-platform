package com.ordex.inventory.application;

import com.ordex.inventory.domain.error.InsufficientStockException;
import com.ordex.inventory.domain.error.UnknownSkuException;
import com.ordex.inventory.infrastructure.persistence.StockItemRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@DisplayName("ReservationService")
class ReservationServiceTest {

    private final StockItemRepository repository = mock(StockItemRepository.class);
    private ReservationService service;
    private UUID orderId;

    @BeforeEach
    void setUp() {
        service = new ReservationService(repository);
        orderId = UUID.randomUUID();
    }

    @Test
    @DisplayName("every line is reserved when stock is sufficient")
    void reservesAllLines() {
        when(repository.findBySku("SKU-001")).thenReturn(Optional.of(item("SKU-001", 10)));
        when(repository.findBySku("SKU-002")).thenReturn(Optional.of(item("SKU-002", 10)));

        service.reserve(orderId, List.of(line("SKU-001", 2), line("SKU-002", 3)));

        verify(repository, org.mockito.Mockito.times(2)).save(any());
    }

    @Test
    @DisplayName("a shortage on the last line rejects the whole order")
    void rejectsEverythingWhenOneLineIsShort() {
        when(repository.findBySku("SKU-001")).thenReturn(Optional.of(item("SKU-001", 10)));
        when(repository.findBySku("SKU-002")).thenReturn(Optional.of(item("SKU-002", 1)));

        assertThatThrownBy(() -> service.reserve(orderId, List.of(line("SKU-001", 2), line("SKU-002", 5))))
                .isInstanceOf(InsufficientStockException.class);
    }

    @Test
    @DisplayName("a reservation exceeding stock is not persisted")
    void doesNotSaveWhenShort() {
        var item = item("SKU-001", 1);
        when(repository.findBySku("SKU-001")).thenReturn(Optional.of(item));

        assertThatThrownBy(() -> service.reserve(orderId, List.of(line("SKU-001", 9))))
                .isInstanceOf(InsufficientStockException.class);

        // In production the surrounding @Transactional rolls the whole thing
        // back; this asserts the entity itself was not mutated.
        assertThat(item.available()).isEqualTo(1);
    }

    @Test
    @DisplayName("an unknown SKU is a business rejection, not a server error")
    void rejectsUnknownSku() {
        when(repository.findBySku("SKU-NOPE")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.reserve(orderId, List.of(line("SKU-NOPE", 1))))
                .isInstanceOf(UnknownSkuException.class);
    }

    @Test
    @DisplayName("release returns units to availability")
    void releaseRestoresStock() {
        var item = item("SKU-001", 7);
        when(repository.findBySku("SKU-001")).thenReturn(Optional.of(item));

        service.release(orderId, List.of(line("SKU-001", 3)));

        assertThat(item.available()).isEqualTo(10);
        verify(repository).save(item);
    }

    @Test
    @DisplayName("releasing an unknown SKU does nothing instead of failing the saga")
    void releaseToleratesUnknownSku() {
        when(repository.findBySku("SKU-GONE")).thenReturn(Optional.empty());

        service.release(orderId, List.of(line("SKU-GONE", 3)));

        // A compensation must never be the thing that breaks the flow.
        verify(repository, never()).save(any());
    }

    private static ReservationService.Line line(String sku, int quantity) {
        return new ReservationService.Line(sku, quantity);
    }

    private static com.ordex.inventory.domain.StockItem item(String sku, int available) {
        return new com.ordex.inventory.domain.StockItem(sku, available);
    }
}