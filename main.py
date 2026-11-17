"""Dip-Buy BTC bot for make.fun's "Race a BTC trading bot live for 24 hours".

Speaks agent-fun/bars-replay/v1: the harness sends one hello line, then one
batch per minute (each batch carries the 1-minute bar that just closed, the
fills of the orders sent on the previous batch, and the account), and the bot
answers every batch with exactly one reply carrying its orders for the next
bar. An order decided on a bar fills at the next bar's open, so every signal
here is computed from closes the bot has already seen.

Strategy (long only, one symbol, CBBTC, $1,000 of paper money):

- Opening dip, then hold. The first minutes of a 24-hour window are noisy,
  so the bot watches the first 12 bars, remembers the lowest close seen, and
  buys the full cash balance the first time a close bounces 15 bps above
  that low. Buying the bounce instead of the low itself means the dip has
  turned; buying once and holding means the bot pays the ~36 bps round-trip
  cost (4 bps fee, 2 bps slippage, ~11 bps of pool impact at full size)
  only once, instead of bleeding it away on every 1-minute wiggle.
- Disaster stop only. While holding, the bot sells everything if a close
  falls 250 bps below the close it bought on. That never fires on ordinary
  noise (the dev window's worst dip after entry is about 80 bps), it only
  caps a real crash. There is no trailing stop and no trend exit: on this
  data every exit rule tested (EMA crosses, trailing stops, regime flips)
  lost money on the dev window because the exits fired on noise and the
  re-entries came back late and dear.
- One careful way back in. After a stop-out the bot stays flat until the
  market proves it has turned: only once 240 bars have passed, the 240-bar
  return is positive, and the close has bounced 15 bps off the lowest close
  since the stop does it buy again. A stopped-out dip buyer that keeps
  re-buying the same falling market just pays the round-trip cost again
  for the same loss, so the bar for coming back is deliberately high.

Determinism: only integer arithmetic on the closes, no clock, no random
numbers, no network, no files, no environment reads. Two runs on the same
bars produce the same orders, byte for byte.
"""

import json
import sys

PROTOCOL = "agent-fun/bars-replay/v1"
SYMBOL = "CBBTC"

# Bars to watch before the first entry can fire.
MIN_BAR = 12
# Entry: a close this many bps above the lowest close seen so far.
BOUNCE_BPS = 15
# Exit: a close this many bps below the close the bot bought on.
STOP_BPS = 250
# Orders are capped at 1% of slippage past the close they were decided on.
MAX_SLIPPAGE_BPS = 100
# A buy must spend at least $1 (1,000,000 quote units).
MIN_NOTIONAL = 1_000_000


def _int(value):
    """A u64 (int or decimal string) as a Python int."""
    return int(value)


class Bot:
    """The bot's state, kept current one batch at a time."""

    def __init__(self, hello):
        self.hello = hello
        self.warmup_bars = int(hello.get("warmup_bars") or 0)
        # Closes seen so far, in bar order.
        self.closes = []
        # Lowest close seen while flat and never stopped out.
        self.low = None
        # Close of the bar the current position was bought on, else None.
        self.entry_close = None
        # True after a disaster stop; the bot then stays flat until the
        # re-entry conditions are met.
        self.stopped = False
        # Lowest close since the disaster stop, for the re-entry bounce.
        self.low_since_stop = None
        # Order counter for deterministic client ids.
        self.next_order = 1
        # Cash and held quantity, from the latest batch's account.
        self.cash = _int(hello["capital"]["quote_units"])
        self.qty = 0

    def _client_id(self):
        cid = "o%d" % self.next_order
        self.next_order += 1
        return cid

    def _apply_account(self, account):
        self.cash = _int(account["cash_quote_units"])
        self.qty = 0
        for position in account["positions"]:
            if position["symbol"] == SYMBOL:
                self.qty = _int(position["qty"])

    def on_batch(self, batch):
        """Decide the orders for one batch; returns a list of order dicts."""
        self._apply_account(batch["account"])
        bar = None
        for candidate in batch["bars"]:
            if candidate["symbol"] == SYMBOL:
                bar = candidate
        # A minute with no CBBTC bar: nothing new to decide on.
        if bar is None:
            return []
        if batch["seq"] < self.warmup_bars:
            return []
        close = _int(bar["c"])
        self.closes.append(close)

        if self.qty > 0:
            # Holding: sell everything only on the disaster stop.
            if close * 10000 < self.entry_close * (10000 - STOP_BPS):
                self.stopped = True
                self.entry_close = None
                self.low_since_stop = close
                return [{
                    "side": "sell",
                    "client_id": self._client_id(),
                    "symbol": SYMBOL,
                    "qty": str(self.qty),
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

        if self.stopped:
            # Back in only on a proven turn: a positive 240-bar return and
            # a fresh 15 bps bounce off the lowest close since the stop.
            if self.low_since_stop is None or close < self.low_since_stop:
                self.low_since_stop = close
            bar_index = len(self.closes) - 1
            if (
                bar_index >= 240
                and self.closes[bar_index] > self.closes[bar_index - 240]
                and close * 10000 > self.low_since_stop * (10000 + BOUNCE_BPS)
                and self.cash >= MIN_NOTIONAL
            ):
                self.entry_close = close
                self.stopped = False
                self.low_since_stop = None
                return [{
                    "side": "buy",
                    "client_id": self._client_id(),
                    "symbol": SYMBOL,
                    "notional_quote_units": str(self.cash),
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []
        if self.low is None or close < self.low:
            self.low = close
        bar_index = len(self.closes) - 1
        if bar_index < MIN_BAR:
            return []
        # Entry: the close bounced BOUNCE_BPS above the lowest close so far.
        if close * 10000 > self.low * (10000 + BOUNCE_BPS):
            if self.cash < MIN_NOTIONAL:
                return []
            self.entry_close = close
            return [{
                "side": "buy",
                "client_id": self._client_id(),
                "symbol": SYMBOL,
                "notional_quote_units": str(self.cash),
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]
        return []


def main():
    stream = sys.stdin.buffer
    out = sys.stdout
    bot = None
    for raw in stream:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            if msg.get("protocol") != PROTOCOL:
                raise SystemExit("unexpected protocol: %r" % (msg.get("protocol"),))
            bot = Bot(msg)
        elif kind == "batch":
            if bot is None:
                raise SystemExit("batch before hello")
            orders = bot.on_batch(msg)
            reply = json.dumps(
                {"type": "reply", "seq": msg["seq"], "orders": orders},
                separators=(",", ":"),
            )
            out.write(reply + "\n")
            out.flush()
        elif kind == "done":
            return 0
        else:
            raise SystemExit("unknown message type: %r" % (kind,))
    raise SystemExit("input ended before done")


if __name__ == "__main__":
    sys.exit(main())
