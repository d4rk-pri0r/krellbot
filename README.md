# Krellbot

Open Crypto Automation, Simplified.

Lightweight. Easy to install in one line. Designed for the agentic AI era, with security baked in from the ground up. Open platform. Open source code.

We provide the intelligence. You keep 100% of your trades.

This repository is the engine. It is free. It runs on your computer. It does not hold your money, and it does not send your exchange key to krellbot.dev.

Strategy packs are a separate download. The pack format is open, so you can write your own.

Site: https://krellbot.dev
Docs: https://krellbot.dev/docs/
Security: [SECURITY.md](SECURITY.md)

## Commands

```
krellbot keys add <venue> --file <key-file>   # store a key in the OS keychain
krellbot backtest <pack.json> --venue kraken  # run a DSL pack over candle data, no orders
krellbot arm <pack.json> --venue kraken --mode paper
krellbot service install                      # schedule the hourly tick for this user
krellbot ui                                   # serve a loopback dashboard at 127.0.0.1
krellbot community install <id>               # pull a pack from the community index
krellbot telemetry enable                     # opt in to anonymous usage telemetry
```

Live arm and live tick are documented in [docs/live.md](docs/live.md). The dashboard, telemetry shape, and community library are documented in [docs/dashboard.md](docs/dashboard.md), [docs/telemetry.md](docs/telemetry.md), and [docs/community.md](docs/community.md).

## Working on the engine

```
git clone https://github.com/d4rk-pri0r/krellbot
cd krellbot
uv run pytest -q
uv run krellbot list
```
