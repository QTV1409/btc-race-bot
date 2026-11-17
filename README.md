# btc-race-bot

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/QTV1409/btc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/QTV1409/btc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

A BTC trading bot for make.fun's "Race a BTC trading bot live for 24 hours" bounty: it buys the opening dip of Coinbase Wrapped BTC (cbBTC) once the price bounces, holds through the 24-hour race window, and sells only on a disaster drop. It trades $1,000 of paper money against replayed 1-minute on-chain bars — no real funds, no real trades.

How it works: the bot speaks the bars-replay protocol (one `hello`, then one `batch` per minute with the bar that just closed, answering each batch with its `orders`). It watches the first 12 bars, remembers the lowest close, and buys the full cash balance the first time a close bounces 15 bps above that low. While holding it sells everything only if a close falls 250 bps below its entry close. After a stop-out it stays flat. Everything is integer arithmetic, so two runs on the same bars produce the same orders byte for byte.

Local check (dev window, 1,440 bars): net PnL +$2.65 USDC after every fee, 1 trade, max drawdown 2.1% — above the dev gate of $0, so it races.

## Run it

```sh
python3 main.py
```

The bot reads newline-delimited JSON on stdin (hello, then batches, then done) and writes one reply line per batch on stdout. See the kit's `protocol.schema.json` for the message shapes.

---

<sub>Entered on [make.fun](https://make.fun/?ref=9qs5x4yn&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
