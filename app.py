from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
HISTORY_FILE = STORAGE_DIR / "history.json"
BUDGET_FILE = STORAGE_DIR / "budget.json"
MAX_HISTORY_ITEMS = 24


def _today() -> date:
    return datetime.now().astimezone().date()


DEFAULT_BUDGET = {
    "available_budget": 24000,
    "next_income_amount": 18000,
    "next_income_date": (_today() + timedelta(days=12)).isoformat(),
    "monthly_savings_percent": 18,
    "daily_expense": 850,
    "free_money": 4500,
    "days": 30,
    "events_text": "6;1400;Ліки\n13;3200;Ремонт\n24;1800;Свято",
}


@dataclass(frozen=True)
class BudgetEvent:
    day: int
    amount: float
    label: str


@dataclass(frozen=True)
class CalculationInput:
    available_budget: float
    next_income_amount: float
    next_income_date: date
    monthly_savings_percent: float
    daily_expense: float
    free_money: float
    days: int
    income_day: int | None
    events: tuple[BudgetEvent, ...]
    events_text: str


@dataclass(frozen=True)
class ScenarioConfig:
    key: str
    label: str
    description: str
    daily_expense_multiplier: float
    reserve_multiplier: float
    free_transfer_ratio: float
    shock_day_ratio: float | None = None
    shock_percent: float = 0.0


SCENARIOS: tuple[ScenarioConfig, ...] = (
    ScenarioConfig(
        key="economy",
        label="Економний",
        description="Ріже щоденні витрати і докидає невикористаний ліміт у вільні гроші.",
        daily_expense_multiplier=0.88,
        reserve_multiplier=1.0,
        free_transfer_ratio=1.0,
    ),
    ScenarioConfig(
        key="base",
        label="Базовий",
        description="Працює з вашим темпом витрат і всіма запланованими точковими подіями.",
        daily_expense_multiplier=1.0,
        reserve_multiplier=1.0,
        free_transfer_ratio=0.0,
    ),
    ScenarioConfig(
        key="aggressive",
        label="Агресивний",
        description="Тягне витрати до верхньої межі комфорту і не тримає окремий резерв.",
        daily_expense_multiplier=1.15,
        reserve_multiplier=0.0,
        free_transfer_ratio=0.0,
    ),
    ScenarioConfig(
        key="force_majeure",
        label="Форс-мажор",
        description="Посеред горизонту зрізає 20% ресурсу, щоб перевірити запас міцності.",
        daily_expense_multiplier=1.0,
        reserve_multiplier=1.0,
        free_transfer_ratio=0.0,
        shock_day_ratio=0.55,
        shock_percent=0.2,
    ),
)


def _round_money(value: float) -> float:
    return round(value, 2)


def _ensure_storage() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]", encoding="utf-8")

    if not BUDGET_FILE.exists():
        BUDGET_FILE.write_text(
            json.dumps(DEFAULT_BUDGET, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _read_json_file(path: Path, fallback: Any) -> Any:
    _ensure_storage()

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write_json_file(path: Path, payload: Any) -> Any:
    _ensure_storage()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _read_history() -> list[dict[str, Any]]:
    payload = _read_json_file(HISTORY_FILE, [])
    if not isinstance(payload, list):
        return []

    compatible_entries: list[dict[str, Any]] = []
    required_keys = {
        "available_budget",
        "next_income_amount",
        "next_income_date",
        "monthly_savings_percent",
        "daily_expense",
        "free_money",
        "days",
    }

    for entry in payload:
        if not isinstance(entry, dict):
            continue

        inputs = entry.get("inputs")
        summary = entry.get("summary")
        if not isinstance(inputs, dict) or not isinstance(summary, dict):
            continue

        if not required_keys.issubset(inputs):
            continue

        compatible_entries.append(entry)

    return compatible_entries


def _write_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed = entries[:MAX_HISTORY_ITEMS]
    return _write_json_file(HISTORY_FILE, trimmed)


def _append_history(entry: dict[str, Any]) -> list[dict[str, Any]]:
    history = _read_history()
    history.insert(0, entry)
    return _write_history(history)


def _read_budget() -> dict[str, Any]:
    payload = _read_json_file(BUDGET_FILE, DEFAULT_BUDGET)
    if isinstance(payload, dict):
        return {**DEFAULT_BUDGET, **payload}
    return DEFAULT_BUDGET.copy()


def _write_budget(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {**DEFAULT_BUDGET, **payload}
    return _write_json_file(BUDGET_FILE, normalized)


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


def _to_date(payload: dict[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> date:
    raw_value = _get_value(payload, key, aliases)

    try:
        value = date.fromisoformat(str(raw_value))
    except ValueError as exc:
        raise ValueError(f"Поле '{key}' має бути датою у форматі YYYY-MM-DD") from exc

    if value < _today():
        raise ValueError(f"Поле '{key}' не може бути раніше сьогоднішньої дати")

    return value


def _parse_events(events_text: str, days: int) -> tuple[BudgetEvent, ...]:
    events: list[BudgetEvent] = []

    for line_number, raw_line in enumerate(events_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if ";" in line:
            parts = [part.strip() for part in line.split(";", 2)]
        elif "|" in line:
            parts = [part.strip() for part in line.split("|", 2)]
        else:
            raise ValueError(f"Рядок події {line_number} має формат 'день;сума;назва'.")

        if len(parts) < 2:
            raise ValueError(f"Рядок події {line_number} має містити щонайменше день і суму.")

        try:
            day = int(float(parts[0]))
            amount = float(parts[1])
        except ValueError as exc:
            raise ValueError(f"Рядок події {line_number} містить некоректне число або день.") from exc

        if day < 1 or day > days:
            raise ValueError(f"Подія в рядку {line_number} має день у межах 1..{days}.")

        if amount < 0:
            raise ValueError(f"Сума події в рядку {line_number} не може бути від'ємною.")

        label = parts[2] if len(parts) == 3 and parts[2] else f"Подія {len(events) + 1}"
        events.append(BudgetEvent(day=day, amount=amount, label=label))

    return tuple(sorted(events, key=lambda item: item.day))


def _serialize_budget(data: CalculationInput) -> dict[str, Any]:
    return {
        "available_budget": _round_money(data.available_budget),
        "next_income_amount": _round_money(data.next_income_amount),
        "next_income_date": data.next_income_date.isoformat(),
        "monthly_savings_percent": _round_money(data.monthly_savings_percent),
        "daily_expense": _round_money(data.daily_expense),
        "free_money": _round_money(data.free_money),
        "days": data.days,
        "events_text": data.events_text,
    }


def _income_day(next_income_date: date, days: int) -> int | None:
    delta = (next_income_date - _today()).days + 1
    if delta < 1:
        return 1
    if delta > days:
        return None
    return delta


def _parse_request(payload: dict[str, Any]) -> CalculationInput:
    days = int(_to_float(payload, "days", aliases=("forecast_days",), min_value=7, max_value=180))
    next_income_date = _to_date(payload, "next_income_date", aliases=("income_date", "next_income_eta"))
    events_text = str(payload.get("events_text", payload.get("events", "")) or "").strip()

    data = CalculationInput(
        available_budget=_to_float(
            payload,
            "available_budget",
            aliases=("starting_balance", "current_balance", "available_funds"),
            min_value=0.0,
        ),
        next_income_amount=_to_float(
            payload,
            "next_income_amount",
            aliases=("income_amount", "income", "monthly_income"),
            min_value=0.0,
        ),
        next_income_date=next_income_date,
        monthly_savings_percent=_to_float(
            payload,
            "monthly_savings_percent",
            aliases=("savings_percent", "monthly_savings_pct"),
            min_value=0.0,
            max_value=100.0,
        ),
        daily_expense=_to_float(
            payload,
            "daily_expense",
            aliases=("daily_operating_expense", "expense_amount"),
            min_value=0.0,
        ),
        free_money=_to_float(
            payload,
            "free_money",
            aliases=("free_funds", "extra_funds"),
            min_value=0.0,
        ),
        days=days,
        income_day=_income_day(next_income_date, days),
        events=_parse_events(events_text, days),
        events_text=events_text,
    )

    return data


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False

    return bool(value)


def _risk_level(
    *,
    zero_day: int | None,
    waterline_day: int | None,
    first_stress_day: int | None,
    reserve_draw_day: int | None,
) -> tuple[str, str]:
    if zero_day is not None:
        return "critical", "Критичний"

    if waterline_day is not None or first_stress_day is not None or reserve_draw_day is not None:
        return "warning", "Напружений"

    return "stable", "Стабільний"


def _build_narrative(
    *,
    zero_day: int | None,
    waterline_day: int | None,
    reserve_draw_day: int | None,
    first_stress_day: int | None,
    income_day: int | None,
    free_money_gain: float,
) -> str:
    if zero_day is not None:
        return f"На {zero_day}-й день сумарний ресурс іде в мінус. Такий режим не дотягує до кінця горизонту."

    if waterline_day is not None:
        return f"На {waterline_day}-й день ви доходите до резервної ватерлінії і починаєте ризикувати ціллю збережень."

    if reserve_draw_day is not None:
        return f"На {reserve_draw_day}-й день починається використання вільних грошей як подушки для виживання."

    if first_stress_day is not None:
        return f"З {first_stress_day}-го дня денна пайка стає тісною і будь-яке перевищення вже ріже наступні ліміти."

    if free_money_gain > 0:
        return "Сценарій не лише проходить горизонт, а й поповнює вільні гроші з невикористаної пайки."

    if income_day is not None:
        return f"Сценарій рівно дотягує до доходу на {income_day}-й день і лишається в контрольованій зоні."

    return "Сценарій тримає горизонт без зриву і без заходу в резерв."


def simulate_scenario(data: CalculationInput, config: ScenarioConfig) -> dict[str, Any]:
    budget_balance = data.available_budget
    free_money_balance = data.free_money
    planned_daily_spend = data.daily_expense * config.daily_expense_multiplier
    monthly_base = data.available_budget + data.free_money
    if data.income_day is not None:
        monthly_base += data.next_income_amount
    target_reserve = monthly_base * (data.monthly_savings_percent / 100.0) * config.reserve_multiplier
    events_by_day: dict[int, list[BudgetEvent]] = {}

    for event in data.events:
        events_by_day.setdefault(event.day, []).append(event)

    first_stress_day: int | None = None
    waterline_day: int | None = None
    reserve_draw_day: int | None = None
    zero_day: int | None = None
    min_total_day = 1
    min_total_assets = budget_balance + free_money_balance
    tightest_limit: float | None = None
    total_events_cost = 0.0
    total_shock_cost = 0.0
    projection: list[dict[str, Any]] = []

    shock_day = None
    if config.shock_day_ratio is not None:
        shock_day = max(1, min(data.days, round(data.days * config.shock_day_ratio)))

    for day in range(1, data.days + 1):
        current_date = _today() + timedelta(days=day - 1)
        income_received = 0.0
        if data.income_day == day:
            budget_balance += data.next_income_amount
            income_received = data.next_income_amount

        start_budget = budget_balance
        start_free_money = free_money_balance
        start_total_assets = start_budget + start_free_money
        remaining_days = data.days - day + 1
        future_income = data.next_income_amount if data.income_day is not None and day < data.income_day else 0.0
        adaptive_limit = max((start_total_assets + future_income - target_reserve) / remaining_days, 0.0)

        event_items = events_by_day.get(day, [])
        event_total = sum(item.amount for item in event_items)
        event_labels = ", ".join(item.label for item in event_items)
        shock_loss = start_total_assets * config.shock_percent if day == shock_day else 0.0
        total_spend = planned_daily_spend + event_total + shock_loss
        reserve_draw = max(total_spend - max(start_budget, 0.0), 0.0)

        budget_balance -= total_spend
        if budget_balance < 0 and free_money_balance > 0:
            spill = min(free_money_balance, -budget_balance)
            free_money_balance -= spill
            budget_balance += spill

        unused_headroom = max(adaptive_limit - total_spend, 0.0)
        free_transfer = min(max(budget_balance, 0.0), unused_headroom * config.free_transfer_ratio)
        if free_transfer > 0:
            budget_balance -= free_transfer
            free_money_balance += free_transfer

        end_total_assets = budget_balance + free_money_balance
        next_future_income = data.next_income_amount if data.income_day is not None and day < data.income_day else 0.0
        next_limit = 0.0
        if remaining_days > 1:
            next_limit = max((end_total_assets + next_future_income - target_reserve) / (remaining_days - 1), 0.0)

        is_stress_day = total_spend > adaptive_limit + 1e-9
        is_waterline_day = end_total_assets <= target_reserve + 1e-9
        is_negative_day = end_total_assets < 0
        is_reserve_draw_day = reserve_draw > 1e-9

        if first_stress_day is None and is_stress_day:
            first_stress_day = day

        if reserve_draw_day is None and is_reserve_draw_day:
            reserve_draw_day = day

        if waterline_day is None and is_waterline_day:
            waterline_day = day

        if zero_day is None and is_negative_day:
            zero_day = day

        if end_total_assets < min_total_assets:
            min_total_assets = end_total_assets
            min_total_day = day

        if tightest_limit is None or adaptive_limit < tightest_limit:
            tightest_limit = adaptive_limit

        total_events_cost += event_total
        total_shock_cost += shock_loss

        projection.append(
            {
                "day": day,
                "date": current_date.isoformat(),
                "income_received": _round_money(income_received),
                "start_budget": _round_money(start_budget),
                "start_free_money": _round_money(start_free_money),
                "start_total_assets": _round_money(start_total_assets),
                "adaptive_limit": _round_money(adaptive_limit),
                "planned_daily_spend": _round_money(planned_daily_spend),
                "event_total": _round_money(event_total),
                "event_labels": event_labels,
                "shock_loss": _round_money(shock_loss),
                "reserve_draw": _round_money(reserve_draw),
                "free_transfer": _round_money(free_transfer),
                "end_budget": _round_money(budget_balance),
                "end_free_money": _round_money(free_money_balance),
                "end_total_assets": _round_money(end_total_assets),
                "next_limit": _round_money(next_limit),
                "target_reserve": _round_money(target_reserve),
                "is_stress_day": is_stress_day,
                "is_waterline_day": is_waterline_day,
                "is_negative_day": is_negative_day,
                "is_shock_day": day == shock_day,
                "is_income_day": income_received > 0,
                "is_reserve_draw_day": is_reserve_draw_day,
            }
        )

    free_money_gain = free_money_balance - data.free_money
    risk_level, risk_label = _risk_level(
        zero_day=zero_day,
        waterline_day=waterline_day,
        first_stress_day=first_stress_day,
        reserve_draw_day=reserve_draw_day,
    )
    narrative = _build_narrative(
        zero_day=zero_day,
        waterline_day=waterline_day,
        reserve_draw_day=reserve_draw_day,
        first_stress_day=first_stress_day,
        income_day=data.income_day,
        free_money_gain=free_money_gain,
    )

    critical_points: list[dict[str, Any]] = [
        {
            "type": "low-point",
            "level": "info",
            "day": min_total_day,
            "title": "Найнижчий сумарний ресурс",
            "message": f"Найглибше просідання стається на {min_total_day}-й день: {round(min_total_assets, 2)} грн.",
        }
    ]

    if data.income_day is not None:
        critical_points.append(
            {
                "type": "income",
                "level": "info",
                "day": data.income_day,
                "title": "Ймовірна дата доходу",
                "message": f"На {data.income_day}-й день модель додає {round(data.next_income_amount, 2)} грн до бюджету.",
            }
        )

    if first_stress_day is not None:
        critical_points.append(
            {
                "type": "stress",
                "level": "warning",
                "day": first_stress_day,
                "title": "Пайка стискається",
                "message": f"З {first_stress_day}-го дня фактичні витрати вже вищі за безпечний денний ліміт.",
            }
        )

    if reserve_draw_day is not None:
        critical_points.append(
            {
                "type": "reserve-draw",
                "level": "warning" if zero_day is None else "critical",
                "day": reserve_draw_day,
                "title": "Починається використання вільних грошей",
                "message": f"На {reserve_draw_day}-й день операційний бюджет уже не покриває витрату самостійно.",
            }
        )

    if waterline_day is not None:
        critical_points.append(
            {
                "type": "waterline",
                "level": "warning" if zero_day is None else "critical",
                "day": waterline_day,
                "title": "Досягнута ватерлінія",
                "message": f"На {waterline_day}-й день сумарний ресурс падає до цільового резерву.",
            }
        )

    if shock_day is not None:
        critical_points.append(
            {
                "type": "shock",
                "level": "warning" if zero_day is None else "critical",
                "day": shock_day,
                "title": "Форс-мажорний удар",
                "message": f"На {shock_day}-й день сценарій списує {round(total_shock_cost, 2)} грн як раптову втрату ресурсу.",
            }
        )

    if zero_day is not None:
        critical_points.append(
            {
                "type": "negative",
                "level": "critical",
                "day": zero_day,
                "title": "Ресурс іде в мінус",
                "message": f"На {zero_day}-й день режим перестає дотягувати до кінця горизонту.",
            }
        )

    summary = {
        "label": config.label,
        "description": config.description,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "final_total_assets": _round_money(budget_balance + free_money_balance),
        "final_budget_balance": _round_money(budget_balance),
        "final_free_money": _round_money(free_money_balance),
        "target_reserve": _round_money(target_reserve),
        "monthly_savings_percent": _round_money(data.monthly_savings_percent * config.reserve_multiplier),
        "planned_daily_spend": _round_money(planned_daily_spend),
        "tightest_limit": _round_money(tightest_limit or 0.0),
        "min_total_assets": _round_money(min_total_assets),
        "min_total_day": min_total_day,
        "first_stress_day": first_stress_day,
        "reserve_draw_day": reserve_draw_day,
        "waterline_day": waterline_day,
        "zero_day": zero_day,
        "income_day": data.income_day,
        "income_date": data.next_income_date.isoformat(),
        "income_amount": _round_money(data.next_income_amount),
        "free_money_gain": _round_money(free_money_gain),
        "total_events_cost": _round_money(total_events_cost),
        "total_shock_cost": _round_money(total_shock_cost),
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


def _build_response(data: CalculationInput, history: list[dict[str, Any]]) -> dict[str, Any]:
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
                "final_total_assets": summary["final_total_assets"],
                "final_free_money": summary["final_free_money"],
                "target_reserve": summary["target_reserve"],
                "tightest_limit": summary["tightest_limit"],
                "waterline_day": summary["waterline_day"],
                "reserve_draw_day": summary["reserve_draw_day"],
                "zero_day": summary["zero_day"],
                "income_day": summary["income_day"],
            }
        )

    return {
        "meta": {
            "today": _today().isoformat(),
            "days": data.days,
            "next_income_amount": _round_money(data.next_income_amount),
            "next_income_date": data.next_income_date.isoformat(),
            "income_day": data.income_day,
            "monthly_savings_percent": _round_money(data.monthly_savings_percent),
            "events": [
                {
                    "day": event.day,
                    "amount": _round_money(event.amount),
                    "label": event.label,
                }
                for event in data.events
            ],
        },
        "budget": _serialize_budget(data),
        "default_scenario": "base",
        "comparison": comparison,
        "scenarios": scenarios,
        "history": history,
    }


def build_forecast(data: CalculationInput, *, save_history: bool) -> dict[str, Any]:
    budget_payload = _write_budget(_serialize_budget(data))
    history = _read_history()

    if save_history:
        base_summary = simulate_scenario(data, SCENARIOS[1])["summary"]
        history_entry = {
            "id": uuid4().hex,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "inputs": budget_payload,
            "summary": {
                "final_total_assets": base_summary["final_total_assets"],
                "final_free_money": base_summary["final_free_money"],
                "target_reserve": base_summary["target_reserve"],
                "zero_day": base_summary["zero_day"],
            },
        }
        history = _append_history(history_entry)

    return _build_response(data, history)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/state")
def state() -> Any:
    budget_payload = _read_budget()
    history = _read_history()

    try:
        data = _parse_request(budget_payload)
    except ValueError:
        return jsonify({"budget": DEFAULT_BUDGET, "history": history, "forecast": None})

    return jsonify(
        {
            "budget": budget_payload,
            "history": history,
            "forecast": _build_response(data, history),
        }
    )


@app.delete("/history")
def clear_history() -> Any:
    return jsonify({"history": _write_history([])})


@app.post("/calculate")
def calculate() -> tuple[Any, int] | Any:
    payload = request.get_json(silent=True) or {}

    try:
        data = _parse_request(payload)
        save_history = _to_bool(payload.get("save_history"), default=True)
        return jsonify(build_forecast(data, save_history=save_history))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(debug=True)
