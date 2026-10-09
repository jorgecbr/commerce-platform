package com.ordex.inventory;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.kafka.annotation.EnableKafka;

/**
 * Inventory service: stock levels and reservations.
 *
 * <p>Owns its own database and never reads the orders database. The two
 * services agree on events published to Kafka, which is the only contract
 * between them.
 */
@SpringBootApplication
@EnableKafka
public class InventoryServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(InventoryServiceApplication.class, args);
    }
}