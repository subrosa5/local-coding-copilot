# Market data

A market data update is considered stale when its timestamp is older than five seconds.
Stale updates are discarded and a staleness metric is incremented.

The gateway validates the instrument identifier before publishing an update.
Unknown instruments are rejected without changing the order book.
