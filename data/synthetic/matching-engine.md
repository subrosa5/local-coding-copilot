# Matching engine

The matching engine matches orders using price-time priority.
Limit orders with the same price are processed in arrival order.

Every accepted order produces an order event.
Fill events are emitted after a successful match and include the execution price.
