import time


class SessionTracker:
    def __init__(self, leverage):
        self.leverage = leverage
        self.started = False
        self.start_equity = 0.0
        self.session_realized = 0.0
        self.trade = None
        self.history = []

    def start_trade(self, position, equity, realized_total):
        size = position["size"]
        self.trade = {
            "side": position["side"],
            "initial_size": size,
            "last_size": size,
            "margin": size * position["entry"] / self.leverage,
            "start_realized": realized_total or 0.0,
            "realized": 0.0,
            "last_total": position["pnl"],
            "start_equity": equity,
        }

    def finish_trade(self, realized):
        trade = self.trade
        pnl_pct = realized / trade["margin"] * 100 if trade["margin"] else 0.0
        self.session_realized += realized
        self.history.append({
            "time": time.strftime("%H:%M:%S"),
            "side": trade["side"],
            "pnl_pct": pnl_pct,
        })
        self.trade = None

    def update(self, equity, position, realized_total=None):
        if not self.started:
            self.started = True
            self.start_equity = equity

        if position and self.trade is None:
            self.start_trade(position, equity, realized_total)
        elif position and position["side"] != self.trade["side"]:
            realized = realized_total - self.trade["start_realized"] if realized_total is not None else self.trade["last_total"]
            self.finish_trade(realized)
            self.start_trade(position, equity, realized_total)
        elif position:
            trade = self.trade
            size = position["size"]
            if size > trade["last_size"]:
                trade["margin"] += (size - trade["last_size"]) * position["entry"] / self.leverage
                trade["initial_size"] += size - trade["last_size"]
            trade["last_size"] = size
            if realized_total is not None:
                trade["realized"] = realized_total - trade["start_realized"]
            trade["last_total"] = trade["realized"] + position["pnl"]
        elif self.trade is not None:
            realized = realized_total - self.trade["start_realized"] if realized_total is not None else self.trade["last_total"]
            self.finish_trade(realized)

        trade_state = None
        if self.trade and position:
            trade_state = {
                "remaining_pct": position["size"] / self.trade["initial_size"] * 100 if self.trade["initial_size"] else 0.0,
                "realized_pct": self.trade["realized"] / self.trade["margin"] * 100 if self.trade["margin"] else 0.0,
            }
        return {
            "trade": trade_state,
            "session": {
                "total_pct": self.session_realized / self.start_equity * 100 if self.start_equity else 0.0,
                "trades": list(reversed(self.history[-10:])),
            },
        }
