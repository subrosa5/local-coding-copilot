# Risk limits

The maximum notional value of a single order is 1000000 USD.
Orders above this limit are rejected before they reach the matching engine.

A client can have a lower per-account limit configured by risk operations.
The effective limit is the minimum of the global and per-account values.
