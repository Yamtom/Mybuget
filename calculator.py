from datetime import date, timedelta
from models import InputSchema

def _expense_base(history: list[dict]) -> float:
    if len(history) < 2:
        return 0.0
    seq = sorted(history, key=lambda x: x["date"])
    diffs = [abs(seq[i]["balance"] - seq[i - 1]["balance"]) for i in range(1, len(seq))]
    return sum(diffs) / len(diffs) if diffs else 0.0


def compute(inp: InputSchema) -> dict:
    d0, d1 = date.fromisoformat(inp.date_start), date.fromisoformat(inp.date_end)
    days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
    n = len(days)
    wl = inp.available_balance * (inp.waterline_percent / 100.0)
    target = inp.available_balance * (inp.savings_percent / 100.0)
    need_daily_target = target / max(inp.save_days, 1)

    hist = [{"date": date.fromisoformat(h.date), "balance": h.balance} for h in inp.balance_history]
    global_base = _expense_base(hist)

    balance = inp.available_balance
    free_floor = balance * (inp.free_money_percent / 100.0)
    free_bucket = free_floor
    saved_total = 0.0
    warns: list[str] = []
    rows = []
    balance_line = []

    for i, d in enumerate(days, start=1):
        req_by_percent = balance * (inp.required_expense_percent / 100.0)
        required_expense = max(global_base, req_by_percent)
        remaining_days = max(1, n - i + 1)
        reallocated = max(0.0, (balance - max(target - saved_total, 0.0)) / remaining_days)
        required_expense = max(required_expense, reallocated)
        balance_after = max(0.0, balance - required_expense)

        saved_today = max(0.0, min(need_daily_target, balance_after * (inp.savings_percent / 100.0)))
        saved_total += saved_today

        if required_expense > 0:
            free_bucket = free_floor
        else:
            free_bucket += balance * (inp.free_money_percent / 100.0)

        if balance_after < wl:
            warns.append(f"Ватерлінія пробита у день {i} ({d})")

        rows.append({
            "day": i,
            "date": str(d),
            "balance": round(balance_after, 2),
            "required_expense": round(required_expense, 2),
            "free_money": round(free_bucket, 2),
        })
        balance_line.append(round(balance_after, 2))
        balance = balance_after

    return {
        "table": rows,
        "chart_data": {
            "labels": [str(d) for d in days],
            "datasets": {"balance": balance_line},
            "waterline": round(wl, 2),
        },
        "summary": {
            "available_balance": inp.available_balance,
            "target_savings_amount": round(target, 2),
            "saved_total": round(saved_total, 2),
            "global_expense_base": round(global_base, 2),
        },
        "warnings": list(dict.fromkeys(warns)),
    }
