from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "storage" / "history.json"
MAX_HISTORY_ITEMS = 24


@dataclass(frozen=True)
class CalculationInput:
    available_funds: float
    days: int
    operating_percent: float
    extra_percent: float


@dataclass(frozen=True)
class ScenarioConfig:
    key: str
    label: str
    description: str
    expense_multiplier: float
    extra_multiplier: float
    shock_day_ratio: float | None = None
    shock_multiplier: float = 0.0


SCENARIOS: tuple[ScenarioConfig, ...] = (
    ScenarioConfig(
        key="economy",
        label="Економний",
        description="Стримує денні витрати і швидше відводить залишок у резерв.",
        expense_multiplier=0.78,
        extra_multiplier=1.15,
    ),
    ScenarioConfig(
        key="base",
        label="Базовий",
        description="Працює рівно з тими відсотками, які ви ввели.",
        expense_multiplier=1.0,
        extra_multiplier=1.0,
    ),
    ScenarioConfig(
        key="aggressive",
        label="Агресивний",
        description="Живе з вищим burn-rate і слабшим відведенням надлишку.",
        expense_multiplier=1.22,
        extra_multiplier=0.8,
    ),
    ScenarioConfig(
        key="force_majeure",
        label="Форс-мажор",
        description="Дає дорожчий режим витрат і разовий удар у середині горизонту.",
        expense_multiplier=1.28,
        extra_multiplier=0.68,
        shock_day_ratio=0.56,
        shock_multiplier=1.9,
    ),
)


def _ensure_history_file() -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]", encoding="utf-8")


def _read_history() -> list[dict[str, Any]]:
    _ensure_history_file()

    try:
        payload = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = []

    if isinstance(payload, list):
        return payload

    return []


def _write_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _ensure_history_file()
    trimmed = entries[:MAX_HISTORY_ITEMS]
    HISTORY_FILE.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return trimmed


def _append_history(entry: dict[str, Any]) -> list[dict[str, Any]]:
    history = _read_history()
    history.insert(0, entry)
    return _write_history(history)


def _get_value(payload: dict[str, Any], key: str, aliases: tuple[str, ...] = ()) -> Any:
    for candidate in (key, *aliases):
        if candidate in payload:
            return payload[candidate]
    raise ValueError(f"Поле '{key}' є обов'язковим")


def _to_float(
    payload: dict[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    min_value: float = 0.0,
    max_value: float | None = None,
) -> float:
    raw_value = _get_value(payload, key, aliases)

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле '{key}' має бути числом") from exc

    if value < min_value:
        raise ValueError(f"Поле '{key}' має бути не менше {min_value}")

    if max_value is not None and value > max_value:
        raise ValueError(f"Поле '{key}' має бути не більше {max_value}")

    return value


def _round_money(value: float) -> float:
    return round(value, 2)


def _parse_request(payload: dict[str, Any]) -> CalculationInput:
    days = int(_to_float(payload, "days", min_value=7, max_value=120))

    return CalculationInput(
        available_funds=_to_float(
            payload,
            "available_funds",
            aliases=("starting_balance", "current_balance"),
            min_value=0.0,
        ),
        days=days,
        operating_percent=_to_float(
            payload,
            "operating_percent",
            aliases=("daily_operating_percent",),
            min_value=0.0,
            max_value=100.0,
        ),
        extra_percent=_to_float(
            payload,
            "extra_percent",
            aliases=("surplus_percent",),
            min_value=0.0,
            max_value=100.0,
        ),
    )


def _build_narrative(
    *,
    first_depletion_day: int | None,
    first_stress_day: int | None,
    final_liquid_balance: float,
    accumulated_extra_funds: float,
    total_assets: float,
    starting_balance: float,
) -> str:
    if first_depletion_day is not None:
        return (
            f"Ліквідні кошти виснажуються на {first_depletion_day}-й день. "
            "Поточний процент витрат треба знизити."
        )

    if first_stress_day is not None:
        return (
            f"Безпечний темп ламається з {first_stress_day}-го дня. "
            "Резерв ще росте, але ліквідність стає тісною."
        )

    if total_assets >= starting_balance and accumulated_extra_funds > 0:
        return "Модель тримає баланс: частина грошей лишається ліквідною, а частина стабільно переходить у накопичення."

    if final_liquid_balance > 0:
        return "Ліквідність доживає до фіналу, але запас стає тонким. Варто зменшити процент витрат."

    return "Сценарій безпечним не виглядає: ліквідність занадто швидко згорає."


def _risk_level(
    *,
    first_depletion_day: int | None,
    first_stress_day: int | None,
    final_liquid_balance: float,
    starting_balance: float,
) -> tuple[str, str]:
    if first_depletion_day is not None:
        return "critical", "Критичний"

    if first_stress_day is not None or final_liquid_balance <= starting_balance * 0.15:
        return "warning", "Напружений"

    return "stable", "Стабільний"


def simulate_scenario(data: CalculationInput, config: ScenarioConfig) -> dict[str, Any]:
    liquid_balance = data.available_funds
    extra_pool = 0.0
    effective_operating_percent = min(data.operating_percent * config.expense_multiplier, 100.0)
    effective_extra_percent = min(data.extra_percent * config.extra_multiplier, 100.0)
    total_operating_expense = 0.0
    total_shock_expense = 0.0
    tightest_safe_daily_spend: float | None = None
    tightest_safe_percent: float | None = None
    min_liquid_balance = liquid_balance
    min_liquid_day = 1
    first_stress_day: int | None = None
    first_depletion_day: int | None = None
    projection: list[dict[str, Any]] = []

    shock_day = None
    if config.shock_day_ratio is not None:
        shock_day = max(1, min(data.days, round(data.days * config.shock_day_ratio)))

    for day in range(1, data.days + 1):
        start_liquid = liquid_balance
        remaining_days = data.days - day + 1
        safe_daily_spend = start_liquid / remaining_days if remaining_days else start_liquid
        safe_daily_percent = (safe_daily_spend / start_liquid * 100) if start_liquid > 0 else 0.0

        operating_expense = start_liquid * effective_operating_percent / 100
        shock_expense = 0.0
        if day == shock_day:
            shock_expense = start_liquid * data.operating_percent * config.shock_multiplier / 100

        actual_operating_expense = min(operating_expense, start_liquid)
        remaining_after_operating = max(start_liquid - actual_operating_expense, 0.0)
        actual_shock_expense = min(shock_expense, remaining_after_operating)
        total_expense = actual_operating_expense + actual_shock_expense
        post_expense_liquid = max(start_liquid - total_expense, 0.0)
        extra_transfer = post_expense_liquid * effective_extra_percent / 100
        end_liquid = max(post_expense_liquid - extra_transfer, 0.0)
        extra_pool += extra_transfer
        total_assets = end_liquid + extra_pool

        is_stress_day = total_expense > safe_daily_spend + 1e-9
        is_depletion_day = end_liquid <= 0.01

        if is_stress_day and first_stress_day is None:
            first_stress_day = day

        if is_depletion_day and first_depletion_day is None:
            first_depletion_day = day

        if end_liquid < min_liquid_balance:
            min_liquid_balance = end_liquid
            min_liquid_day = day

        if tightest_safe_daily_spend is None or safe_daily_spend < tightest_safe_daily_spend:
            tightest_safe_daily_spend = safe_daily_spend
            tightest_safe_percent = safe_daily_percent

        total_operating_expense += actual_operating_expense
        total_shock_expense += actual_shock_expense

        projection.append(
            {
                "day": day,
                "start_liquid": _round_money(start_liquid),
                "operating_percent": _round_money(effective_operating_percent),
                "safe_daily_spend": _round_money(safe_daily_spend),
                "safe_daily_percent": _round_money(safe_daily_percent),
                "operating_expense": _round_money(actual_operating_expense),
                "shock_expense": _round_money(actual_shock_expense),
                "total_expense": _round_money(total_expense),
                "extra_transfer": _round_money(extra_transfer),
                "end_liquid": _round_money(end_liquid),
                "extra_pool": _round_money(extra_pool),
                "total_assets": _round_money(total_assets),
                "is_stress_day": is_stress_day,
                "is_shock_day": day == shock_day,
                "is_depletion_day": is_depletion_day,
            }
        )

        liquid_balance = end_liquid

    risk_level, risk_label = _risk_level(
        first_depletion_day=first_depletion_day,
        first_stress_day=first_stress_day,
        final_liquid_balance=liquid_balance,
        starting_balance=data.available_funds,
    )
    total_assets = liquid_balance + extra_pool
    narrative = _build_narrative(
        first_depletion_day=first_depletion_day,
        first_stress_day=first_stress_day,
        final_liquid_balance=liquid_balance,
        accumulated_extra_funds=extra_pool,
        total_assets=total_assets,
        starting_balance=data.available_funds,
    )

    critical_points: list[dict[str, Any]] = [
        {
            "type": "low-point",
            "level": "info",
            "day": min_liquid_day,
            "title": "Найменша ліквідність",
            "message": f"Найнижчий ліквідний залишок на {min_liquid_day}-й день: {round(min_liquid_balance, 2)} грн.",
        }
    ]

    if first_stress_day is not None:
        critical_points.append(
            {
                "type": "stress",
                "level": "warning",
                "day": first_stress_day,
                "title": "Процент витрат зависокий",
                "message": f"З {first_stress_day}-го дня витрати вищі за безпечний денний темп для цього горизонту.",
            }
        )

    if shock_day is not None:
        critical_points.append(
            {
                "type": "shock",
                "level": "warning" if risk_level != "critical" else "critical",
                "day": shock_day,
                "title": "Форс-мажорний удар",
                "message": f"На {shock_day}-й день додається позапланове списання поверх базового процента витрат.",
            }
        )

    if first_depletion_day is not None:
        critical_points.append(
            {
                "type": "depletion",
                "level": "critical",
                "day": first_depletion_day,
                "title": "Ліквідність вичерпана",
                "message": f"На {first_depletion_day}-й день оперативний баланс стає майже нульовим.",
            }
        )

    summary = {
        "label": config.label,
        "description": config.description,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "final_liquid_balance": _round_money(liquid_balance),
        "accumulated_extra_funds": _round_money(extra_pool),
        "final_total_assets": _round_money(total_assets),
        "total_operating_expense": _round_money(total_operating_expense),
        "total_shock_expense": _round_money(total_shock_expense),
        "operating_percent": _round_money(effective_operating_percent),
        "extra_percent": _round_money(effective_extra_percent),
        "tightest_safe_daily_spend": _round_money(tightest_safe_daily_spend or 0.0),
        "tightest_safe_percent": _round_money(tightest_safe_percent or 0.0),
        "min_liquid_balance": _round_money(min_liquid_balance),
        "min_liquid_day": min_liquid_day,
        "first_stress_day": first_stress_day,
        "first_depletion_day": first_depletion_day,
        "narrative": narrative,
    }

    return {
        "key": config.key,
        "label": config.label,
        "description": config.description,
        "summary": summary,
        "critical_points": critical_points,
        "projection": projection,
    }


def build_forecast(data: CalculationInput) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    comparison: list[dict[str, Any]] = []

    for config in SCENARIOS:
        scenario = simulate_scenario(data, config)
        scenarios[config.key] = scenario
        summary = scenario["summary"]
        comparison.append(
            {
                "key": config.key,
                "label": config.label,
                "description": config.description,
                "risk_level": summary["risk_level"],
                "risk_label": summary["risk_label"],
                "final_liquid_balance": summary["final_liquid_balance"],
                "accumulated_extra_funds": summary["accumulated_extra_funds"],
                "final_total_assets": summary["final_total_assets"],
                "tightest_safe_daily_spend": summary["tightest_safe_daily_spend"],
                "first_stress_day": summary["first_stress_day"],
                "first_depletion_day": summary["first_depletion_day"],
            }
        )

    base_summary = scenarios["base"]["summary"]
    history_entry = {
        "id": uuid4().hex,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": asdict(data),
        "summary": {
            "final_liquid_balance": base_summary["final_liquid_balance"],
            "accumulated_extra_funds": base_summary["accumulated_extra_funds"],
            "final_total_assets": base_summary["final_total_assets"],
            "first_depletion_day": base_summary["first_depletion_day"],
        },
    }

    history = _append_history(history_entry)

    return {
        "meta": {
            "days": data.days,
            "available_funds": _round_money(data.available_funds),
            "operating_percent": _round_money(data.operating_percent),
            "extra_percent": _round_money(data.extra_percent),
        },
        "default_scenario": "base",
        "comparison": comparison,
        "scenarios": scenarios,
        "history": history,
    }


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/history")
def history() -> Any:
    return jsonify({"history": _read_history()})


@app.delete("/history")
def clear_history() -> Any:
    return jsonify({"history": _write_history([])})


@app.post("/calculate")
def calculate() -> tuple[Any, int] | Any:
    payload = request.get_json(silent=True) or {}

    try:
        data = _parse_request(payload)
        return jsonify(build_forecast(data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(debug=True)
