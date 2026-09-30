# Competitive analysis and priority roadmap

Written 2026-09-30 against engine 0.9.1 (`eeaf59d`). Competitor facts come
from public repositories, docs, and release notes as of September 2026; star
counts are approximate and only given where a 2026 source stated one.

## 1. Where Krellbot stands today

About 9,200 lines of engine, 7,800 lines of tests (300 passing), three runtime
dependencies, CI on Linux, macOS, and Windows for Python 3.10 and 3.13.

What it already does well, and what no competitor does as a whole:

| Strength | Why it matters |
| --- | --- |
| Declarative JSON packs, never executed as code | A downloaded strategy cannot read your keychain or phone home. Freqtrade, Jesse, OctoBot, and Hummingbot strategies are arbitrary Python: installing a stranger's strategy is running a stranger's program. |
| Refuses any key that can withdraw | Checked at arm time and at every live tick, on both venues. |
| Typed `LIVE` gate, CLI-only; dashboard cannot live-arm | Live money needs a human at a terminal. |
| Sells are bounded by the pack's own journal | The bot never touches coins it did not buy. |
| Idempotent client order ids, per-venue lock, atomic writes, `Decimal` money | Crash and retry do not double-order. |
| Loopback dashboard with a 256-bit gate token, Host check, CSRF, no CDN | Stricter than FreqUI's or OctoBot's web UI defaults. |
| Backtest receipts carry `pack_sha256` and `data_manifest_sha256` | Any result can be reproduced byte for byte. No competitor ships this. |
| Causal indicators by construction; `run_series` is proven bit-identical to per-bar evaluation | Lookahead bias is ruled out structurally, not detected afterwards. |
| OS-native scheduling (launchd, systemd user timer, Task Scheduler) | No daemon to babysit, survives sleep. |

What it does not do yet (the gaps the roadmap below closes):

* Two venues (Kraken, Coinbase), spot only, long only, one pack per venue and pair.
* 13 indicators. No RSI, MACD, Bollinger Bands, ADX, or Donchian. No
  arithmetic in conditions (`close > sma20 * 1.02` cannot be written), no
  take-profit, no trailing stop, no time exit, one timeframe per pack.
* Backtest metrics stop at return, CAGR, drawdown, exposure, and trade
  count. No Sharpe, Sortino, win rate, profit factor, or trade list. No
  parameter search, walk-forward, or Monte Carlo.
* No notifications. You learn about a stop-out by opening the dashboard.
* No agent interface. The README says "designed for the agentic AI era";
  there is no MCP server and most commands have no `--json` output.
* No bundled runnable packs outside `tests/fixtures/`. A new user has
  nothing to paper-trade without writing JSON first.
* Stale docs: `docs/getting-started.md` says "Coinbase is not ready" and
  "the client will not place an order until that path exists"; both are
  now false.
* One contributor, 26 commits, no CONTRIBUTING, changelog, issue
  templates, roadmap, or discussion space.

## 2. The local, self-hosted field

| Project | Stars (approx.) | Language | Focus | Venues | Strategy form | Agent / AI | Standout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Freqtrade** | ~53k | Python | Signal bots, spot and futures | 30+ via CCXT | Python class | Community MCP server; FreqAI ML | Hyperopt, lookahead and recursive analysis, Telegram, FreqUI, Docker, monthly releases (2026.9) |
| **Hummingbot** | 6k-15k (sources disagree) | Python / Cython | Market making, arbitrage | 300+ CEX and DEX connectors | Python scripts and V2 controllers | Official MCP server, agent skills | Institutional volume, DEX gateway, Docker-first |
| **Jesse** | 5k+ | Python | Research-grade backtesting | Major CEXs (live via paid plugin) | Python class | Built-in local MCP server, JesseGPT | Clean strategy API, Optuna optimisation, Monte Carlo, rule significance tests, dashboard |
| **OctoBot** | 5.4k+ | Python | Beginner, no-code | 15+ via CCXT | Web UI "tentacles" (plugins) | ChatGPT evaluators | DCA and grid presets, Telegram, optional paid cloud |
| **NautilusTrader** | not checked | Rust core, Python API | Professional, event-driven, multi-asset | Rust-native adapters incl. Kraken | Python strategies | None built in | Nanosecond backtest/live parity, v2 runtime in RC |
| **Passivbot** | not checked | Python / Rust | Perpetual futures grid | Bybit, Binance, OKX, others | Config + optimiser | None | Evolutionary optimiser for grid params |
| **Superalgos** | not checked | JS | Visual designer | CCXT | Node-graph | Limited | Visual strategy building, but heavy install |

Observations that shape the plan:

1. **Freqtrade owns breadth.** Beating it on exchange count, indicators, or
   ML is a multi-year race against a large contributor base. Krellbot should
   not try.
2. **Hummingbot owns market making and DEX.** Stay out.
3. **Agent integration became table stakes in 2025-26.** Hummingbot ships an
   official MCP server, Jesse ships one built in, Freqtrade has a community
   one. All of them hand an agent a tool surface that can run arbitrary
   strategy code and, in Hummingbot's case, place live orders.
4. **Nobody leads on safety.** Every major competitor runs user-supplied
   Python with the exchange key in the same process. Every one of them
   accepts a withdraw-capable key. None produce reproducible, hash-pinned
   backtest receipts.

The open lane: **the safest local crypto bot for people who do not want to
write code, and the only one an AI agent can drive without being able to
lose your money.** Declarative packs plus the existing guardrails make that
claim true in a way competitors cannot copy without breaking their
strategy APIs.

## 3. What would make Krellbot a leading project, by priority

Priorities weigh (a) how much the item moves adoption, (b) how much it
reinforces the safety-first position, and (c) cost. P0 items are cheap and
close the gap between what the README promises and what the code does.

### P0: make the pitch true (weeks 1-3)

**1. Ship an agent interface: `krellbot mcp` and `--json` everywhere.**
The README's headline claim has no code behind it, and this is the single
most differentiating feature available. Declarative packs are ideal for
agents: an LLM can write a pack, `lint` it, `backtest` it, read the
receipt, iterate, and paper-arm it, and none of that can execute code or
move money.

* Stdio MCP server exposing: `list_packs`, `lint_pack`, `write_pack`
  (validated against `schema.json` before it touches disk), `backtest`
  (returns the receipt), `fetch_candles`, `status`, `journal_tail`,
  `paper_arm`, `disarm`, `stop_all`, `doctor`.
* Live arm is **not** a tool, ever. The typed `LIVE` gate stays human-only,
  as the dashboard already enforces. Say so in the docs: this is the
  headline.
* `--json` on `list`, `status`, `journal`, `doctor`, `keys check`, `lint`,
  `community list`, matching the receipt style already used by `backtest`.
* Stdlib only (JSON-RPC over stdio is small), preserving the three-dependency
  footprint.

**2. Five-minute first run.**
* Move 3-5 free reference packs (trend follow, breakout, mean reversion,
  volatility-scaled trend) out of test fixtures into `packs/examples/`,
  each with a committed receipt.
* `krellbot quickstart`: pick an example, fetch public candles, backtest,
  paper-arm, install the service. No key needed.
* Publish to PyPI (the workflow exists) and document `pipx install krellbot`
  / `uv tool install krellbot` beside the `curl | sh` path. Add an official
  container image for NAS and home-server users.
* Fix the stale statements in `docs/getting-started.md`.

**3. Say what the business model is, up front.**
The engine is MIT; the maintained packs cost $39/month. That is a fair
model, but competitors' marketing will frame paid packs as a signal service.
A short `docs/model.md` covering what is free, what is paid, how past
results in the catalog are computed (receipts, fees, slippage, window), and
that a paid pack runs through the same open engine and guardrails, will
pre-empt that.

### P1: table stakes for being taken seriously (months 1-2)

**4. Backtest rigor that matches Jesse and Freqtrade, with receipts as the edge.**
* Metrics: Sharpe, Sortino, Calmar, win rate, profit factor, average
  win/loss, longest drawdown, and a per-trade list in the receipt.
* `krellbot sweep`: grid or random search over declared parameter ranges
  (`len`, `mult`, thresholds), with a mandatory out-of-sample split and a
  walk-forward mode. Report the in-sample vs out-of-sample gap so an overfit
  pack is flagged, not celebrated.
* Monte Carlo trade-order resampling for a drawdown distribution.
* Keep `run_series` bit-identical to the tick path and add a test that
  replays a paper-tick session through the backtester and compares fills.
  Backtest/live parity is Freqtrade's most common complaint.

**5. Pack DSL v2 (schema_version 2, v1 still accepted).**
* Indicators: RSI, MACD (line, signal, histogram), Bollinger Bands, ADX,
  Donchian channel, Keltner channel, OBV, z-score.
* Arithmetic operands: `["close", ">", {"mul": ["sma20", 1.02]}]`, depth-capped
  like conditions are today.
* Exits: take-profit (pct or ATR), trailing stop that only ratchets up
  (consistent with "never lowers a stop"), max bars in trade.
* Informative higher timeframe (a 1h pack reading a 1d trend filter).
* Volatility-targeted sizing as an alternative to fixed `max_account_pct`.
* Everything stays a whitelist; the "never runs code" property is
  non-negotiable.

**6. Portfolio-level circuit breakers.**
A safety-first bot should be the one that stops itself.
* Account-wide max exposure across packs on a venue.
* Daily and rolling drawdown kill switch that disarms entries (exits
  stay on, as the license gate already does).
* Stale-data guard: refuse to enter if the latest candle is older than
  one timeframe plus tolerance.
* All journaled, all visible in `status` and the dashboard.

**7. Outbound-only notifications.**
Telegram is the feature Freqtrade and OctoBot users ask about first.
* Channels: Telegram, Discord webhook, ntfy, generic webhook, email via SMTP.
* Events: fill, stop placed or raised, stop hit, circuit breaker tripped,
  tick error, missed tick (doctor can detect a timer that has not fired).
* Outbound only: no inbound command bot by default. If a command channel is
  added later, it can disarm and stop all but can never arm live.

**8. Engineering hygiene that unlocks contributors.**
* Split `cli.py` (1,700 lines, hand-rolled argv dispatch, lint exceptions
  for bare `except`) into `argparse` subcommand modules. This is a
  prerequisite for items 1, 4, and 7 landing cleanly.
* Add a type checker (pyright or mypy) and coverage reporting to CI.
* Property-based tests for the ledger invariants already stated in the
  docs (`cash >= 0`, `equity == cash + qty * close`).
* Release provenance: PyPI trusted publishing with attestations and an
  SBOM, alongside the existing minisign signature.

### P2: reach (quarter 2)

**9. More venues, same guardrails.**
Kraken plus Coinbase leaves out most of the world's spot volume.
* Hand-written spot adapters for Binance, OKX, and Bybit, each with the
  same withdraw-permission refusal, coid idempotency, and rule reads. Keep
  them hand-written: the key-permission check is the product, and a generic
  CCXT wrapper cannot guarantee it for every exchange.
* Optionally, a `krellbot[ccxt]` extra for public candles only (backtests on
  any market) without enabling live trading there.
* Limit or post-only entries: Kraken maker fees are well below the 40 bps
  taker default the engine assumes, which compounds on every round trip.

**10. Dashboard that people screenshot.**
Still loopback-only, still no CDN.
* Equity curve and drawdown charts per pack (inline SVG, no library).
* Backtest receipt viewer and side-by-side compare.
* Pack editor with live lint, form-based for non-coders. This is what
  OctoBot wins beginners with.
* Paper arm, disarm, stop-all from the page as today; live arm stays out.

**11. Community infrastructure and a verified pack gallery.**
* CONTRIBUTING, issue and PR templates, CHANGELOG, public roadmap,
  GitHub Discussions or a Discord.
* A pack gallery on krellbot.dev where every listed result is a receipt
  anyone can re-run with `krellbot backtest --verify <receipt>`. Freqtrade's
  strategy repositories list numbers nobody can check; a gallery of
  reproducible receipts is a reason to choose Krellbot.
* Good-first-issue labels on indicators and venue adapters, which are
  self-contained and fixture-tested.

### P3: later, or deliberately not

**12. Futures, shorts, and leverage.** High demand, but at odds with the
safety brand. If added, gate it like live mode (env flag plus typed
confirmation), cap leverage low, and require isolated margin.

**13. DCA and grid presets.** Popular with OctoBot and Passivbot users.
They fit as pack templates once DSL v2 has multiple entries per position.

**14. Not worth chasing:** sub-minute timeframes and websockets (conflicts
with the hourly OS-scheduled tick that keeps the bot simple), market making
and DEX (Hummingbot's market), and built-in ML (FreqAI's market). Let agents
do the research through item 1 instead of shipping a model zoo.

## 4. Summary

| Priority | Item | Effort | Adoption impact | Reinforces safety position |
| --- | --- | --- | --- | --- |
| P0 | 1. MCP server and `--json` output | S-M | High | Yes: agent cannot go live |
| P0 | 2. Example packs, quickstart, PyPI and container, doc fixes | S | High | Neutral |
| P0 | 3. Business-model transparency | XS | Medium | Yes |
| P1 | 4. Backtest metrics, sweep, walk-forward, Monte Carlo | M | High | Yes: overfit flagged |
| P1 | 5. DSL v2 indicators, arithmetic, TP, trailing, MTF | M | High | Yes: still no code |
| P1 | 6. Portfolio circuit breakers | S-M | Medium | Strongly |
| P1 | 7. Outbound notifications | S | High | Yes: outbound only |
| P1 | 8. CLI refactor, type checks, provenance | M | Enabler | Yes |
| P2 | 9. Binance, OKX, Bybit; maker orders | L | High | Yes: same key checks |
| P2 | 10. Dashboard charts and pack editor | M | Medium-High | Neutral |
| P2 | 11. Community infra and verified gallery | M | High | Yes |
| P3 | 12-14. Futures, DCA/grid, explicit non-goals | - | - | - |

Krellbot will not out-feature Freqtrade. It can be the project people
recommend when someone asks, "which bot can I trust with my account, and
let my AI assistant run?" Items 1, 2, 4, 5, and 7 are what that
recommendation needs.

## Sources

* Freqtrade releases and FreqAI docs: <https://github.com/freqtrade/freqtrade/releases>, <https://www.freqtrade.io/en/stable/freqai/>
* Freqtrade community MCP server: <https://github.com/kukapay/freqtrade-mcp>
* Hummingbot MCP: <https://hummingbot.org/mcp/>
* Jesse and its MCP server: <https://jesse.trade/>, <https://github.com/jesse-ai/jesse>
* NautilusTrader releases and Kraken adapter: <https://github.com/nautechsystems/nautilus_trader/releases>, <https://nautilustrader.io/docs/latest/integrations/kraken/>
* 2026 comparisons: <https://gainium.io/best/open-source>, <https://alexbobes.com/crypto/best-freqtrade-alternatives/>, <https://coincodecap.com/open-source-trading-bots-on-github>
