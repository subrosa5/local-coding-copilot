# Order lifecycle

A new order is validated before it becomes open.
Only open orders can be cancelled; filled and rejected orders cannot be cancelled.

Rejected orders never enter the order book.
Increasing quantity or changing price resets time priority for an amended order.
