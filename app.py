from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


@dataclass
class CalculationInput:
    current_balance: float
    days: int
    expense_amount: float
    expense_interval_days: int
    extra_percent: float
    savings_percent: float


def _to_float(payload: dict[str, Any], key: str, *, min_value: float = 0.0) -> float:
    if key not in payload:
        raise ValueError(f"Поле '{key}' є обов'язковим")

    try:
        value = float(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле '{key}' має бути числом") from exc

    if value < min_value:
        raise ValueError(f"Поле '{key}' має бути не менше {min_value}")

    return value


def _parse_request(payload: dict[str, Any]) -> CalculationInput:
    days = int(_to_float(payload, "days", min_value=1))
    expense_interval_days = int(_to_float(payload, "expense_interval_days", min_value=1))

    data = CalculationInput(
        current_balance=_to_float(payload, "current_balance", min_value=0.0),
        days=days,
        expense_amount=_to_float(payload, "expense_amount", min_value=0.0),
        expense_interval_days=expense_interval_days,
        extra_percent=_to_float(payload, "extra_percent", min_value=0.0),
        savings_percent=_to_float(payload, "savings_percent", min_value=0.0),
    )

    if data.extra_percent + data.savings_percent > 100:
        raise ValueError("Сума відсотків 'зайві кошти + збереження' не може бути більшою за 100%")

    if data.days > 3660:
        raise ValueError("Період розрахунку не може перевищувати 3660 днів")

    return data


def build_projection(data: CalculationInput) -> dict[str, Any]:
    daily_rows: list[dict[str, float | int]] = []

    balance = data.current_balance
    cumulative_savings = 0.0
    cumulative_extra = 0.0
    total_expenses = 0.0

    extra_ratio = data.extra_percent / 100
    savings_ratio = data.savings_percent / 100

    for day in range(1, data.days + 1):
        start_balance = balance
        expense = 0.0
        extra_funds = 0.0
        savings = 0.0
        free_part = balance
        is_expense_day = day % data.expense_interval_days == 0

        if is_expense_day:
            expense = min(balance, data.expense_amount)
            total_expenses += expense
            balance -= expense

            split_base = max(balance, 0.0)
            extra_funds = split_base * extra_ratio
            savings = split_base * savings_ratio
            free_part = split_base - extra_funds - savings

            cumulative_extra += extra_funds
            cumulative_savings += savings

        daily_rows.append(
            {
                "day": day,
                "start_balance": round(start_balance, 2),
                "expense": round(expense, 2),
                "expense_day": is_expense_day,
                "remaining": round(balance, 2),
                "extra_funds": round(extra_funds, 2),
                "savings": round(savings, 2),
                "free_part": round(free_part, 2),
                "cumulative_extra": round(cumulative_extra, 2),
                "savings_progress": round(cumulative_savings, 2),
            }
        )

    stability_index = 0.0
    if data.current_balance > 0:
        stability_index = (cumulative_savings / data.current_balance) * 100

    return {
        "summary": {
            "final_balance": round(balance, 2),
            "total_savings": round(cumulative_savings, 2),
            "total_extra": round(cumulative_extra, 2),
            "total_expenses": round(total_expenses, 2),
            "stability_index": round(stability_index, 2),
        },
        "projection": daily_rows,
    }


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.post("/calculate")
def calculate() -> tuple[Any, int] | Any:
    payload = request.get_json(silent=True) or {}

    try:
        data = _parse_request(payload)
        result = build_projection(data)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(debug=True)
