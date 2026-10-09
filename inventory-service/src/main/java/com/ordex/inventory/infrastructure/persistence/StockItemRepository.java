package com.ordex.inventory.infrastructure.persistence;

import com.ordex.inventory.domain.StockItem;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

/** Persistence for stock items. Spring Data generates the implementation from this interface. */
public interface StockItemRepository extends JpaRepository<StockItem, String> {

    Optional<StockItem> findBySku(String sku);
}