"""Position sizing and the risk rules. Plain code, no AI: this is the layer that can say no to anything that comes before it.

Hard rules can be raised by you in the settings but not skipped by an order: filters, stop on the right side, leverage cap,
margin available, notional cap. Soft rules (daily loss, trade count, cooldown, position count) block signals and automation and
can be overridden for a single manual order with override=true."""
from decimal import Decimal

from .binance import D, fmt


def pct(a, b):
    return (a / b * 100) if b else 0.0


def resolve_qty(intent, price, equity, sym, leverage):
    """Quantity from whichever sizing the intent carries: qty > notional > margin (x leverage) > risk_pct of equity at the stop."""
    p = D(price)
    if intent.get("qty"):
        return D(intent["qty"]), "quantity"
    if intent.get("notional"):
        return D(intent["notional"]) / p, "notional"
    if intent.get("margin"):
        return D(intent["margin"]) * D(leverage) / p, "margin"
    rp, stop = intent.get("risk_pct"), intent.get("stop")
    if rp and stop:
        dist = abs(p - D(stop))
        if dist > 0:
            return D(equity) * D(rp) / 100 / dist, "risk"
    return D(0), "none"


def check(cfg, intent, plan, ctx):
    """Returns {"ok", "violations", "warnings"} for a resolved plan. cfg is the futures section; ctx carries the live account state."""
    f = cfg
    v, w = [], []
    src, override = intent.get("source", "manual"), bool(intent.get("override"))
    side, entry, stop, tp = intent["side"], plan["price"], intent.get("stop"), intent.get("tp")
    long = side == "LONG"
    if side not in ("LONG", "SHORT"):
        v.append("side must be LONG or SHORT")
    if src == "signal" and intent["symbol"] not in f["symbols"]:
        v.append(f"{intent['symbol']} is not in the allowed symbols")
    if stop is None:
        if not f["allow_no_stop"]:
            v.append("a stop loss is required (setting allow_no_stop is off)")
    else:
        if (long and stop >= entry) or (not long and stop <= entry):
            v.append("the stop is on the wrong side of the entry")
        else:
            sp = abs(entry - stop) / entry * 100
            plan["stop_pct"] = sp
            if sp < f["min_stop_pct"]:
                (v if src == "signal" else w).append(f"stop is only {sp:.2f}% away: fees would eat a large part of the risk (minimum {f['min_stop_pct']}%)")
    if tp is not None:
        if (long and tp <= entry) or (not long and tp >= entry):
            v.append("the take profit is on the wrong side of the entry")
        elif stop is not None and not v:
            rr = abs(tp - entry) / abs(entry - stop)
            plan["rr"] = rr
            if rr < f["min_rr"]:
                (v if src == "signal" else w).append(f"reward to risk {rr:.2f} is below {f['min_rr']}")
    lev = plan["leverage"]
    if lev > f["max_leverage"]:
        v.append(f"leverage {lev}x is above your cap of {f['max_leverage']}x (raise the cap in settings to allow it)")
    if plan["qty"] <= 0 and not plan.get("filter_errors"):
        v.append("size is zero: give a quantity, a notional, a margin, or a risk % together with a stop")
    v += plan.get("filter_errors", [])
    eq, avail = ctx["equity"], ctx["available"]
    if plan["notional"] > eq * f["max_notional_pct"] / 100:
        v.append(f"position value {plan['notional']:.0f} is above {f['max_notional_pct']}% of the account")
    if plan["margin_needed"] > avail * 0.95:
        v.append(f"needs {plan['margin_needed']:.2f} margin but only {avail:.2f} is available")
    if stop is not None and plan["qty"] > 0:
        plan["risk_amount"] = float(plan["qty"]) * abs(entry - stop)
        plan["risk_pct"] = pct(plan["risk_amount"], eq)
        if plan["risk_pct"] > f["risk_pct"] * 1.5 and src == "manual":
            w.append(f"risk {plan['risk_pct']:.2f}% of the account is above your usual {f['risk_pct']}%")
        if plan["risk_pct"] > 10:
            v.append(f"risk {plan['risk_pct']:.1f}% of the account on one trade is above the 10% hard limit")
    # liquidation proximity (isolated): liquidation should be beyond the stop
    if stop is not None and plan["margin_type"] == "ISOLATED" and lev > 1:
        liq = entry * (1 - 1 / lev + 0.005) if long else entry * (1 + 1 / lev - 0.005)
        plan["liq_est"] = liq
        if (long and stop <= liq) or (not long and stop >= liq):
            v.append(f"liquidation (about {liq:.4g}) would come before the stop: lower the leverage")
    if ctx["halted"]:                                    # the kill switch is never bypassed by an order
        v.append("new entries are stopped (kill switch); resume first")
    soft = []
    open_n = ctx["open_positions"] + ctx["pending_entries"]
    if open_n >= f["max_positions"]:
        soft.append(f"{open_n} positions/entries already open (max {f['max_positions']})")
    if ctx["trades_today"] >= f["max_daily_trades"]:
        soft.append(f"{ctx['trades_today']} trades today (max {f['max_daily_trades']})")
    if ctx["daily_pnl"] <= -ctx["day_start_equity"] * f["daily_loss_limit_pct"] / 100:
        soft.append(f"daily loss limit reached ({ctx['daily_pnl']:.2f} today)")
    last = ctx["last_trade_ts"].get(intent["symbol"])
    if last and ctx["now"] - last < f["cooldown_min"] * 60:
        soft.append(f"cooldown: {intent['symbol']} traded {int((ctx['now'] - last) / 60)} min ago")
    if ctx["same_symbol_open"]:
        soft.append(f"{intent['symbol']} already has a position or entry")
    (w if (override and src != "signal") else v).extend(soft)
    return {"ok": not v, "violations": list(dict.fromkeys(v)), "warnings": list(dict.fromkeys(w))}
