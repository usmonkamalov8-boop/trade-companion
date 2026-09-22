"""Trade Companion execution engine: Binance futures (directional profile) and spot grid (grid profile).

Runs as its own service (tcexec) so that restarting the API never interrupts open trades, and so that the exchange keys
live in one small process. The API only forwards requests to it."""
