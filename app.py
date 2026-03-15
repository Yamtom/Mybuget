from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

BASE_DIR = Path(__file__).resolve().parent
BUDGET_FILE = BASE_DIR / "budget.json"
LEGACY_BUDGET_FILE = BASE_DIR / "storage" / "budget.json"
LEGACY_HISTORY_FILE = BASE_DIR / "storage" / "history.json"

MAX_FORECAST_DAYS = 365
HISTORY_LIMIT = 12
DEFAULT_WATERLINE_PERCENT = 10.0
MODE_ORDER = ("base", "economy", "aggressive", "force_majeure")
MODE_LABELS = {
    "base": "Базовий",
    "economy": "Економний",
    "aggressive": "Агресивний",
    "force_majeure": "Форс-мажор",
}
MODE_CONFIG = {
    "base": {"expense_multiplier": 1.0, "use_savings": True, "shock": False},
    "economy": {"expense_multiplier": 0.88, "use_savings": True, "shock": False},
    "aggressive": {"expense_multiplier": 1.2, "use_savings": False, "shock": False},
    "force_majeure": {"expense_multiplier": 1.0, "use_savings": True, "shock": True},
}

app = Flask(__name__)


def round_money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def round_percent(value: float) -> float:
    return round(float(value) + 1e-9, 4)


def backup_invalid_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.invalid.{stamp}")


def read_json(path: Path, *, backup_invalid: bool = False) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if backup_invalid:
            try:
                path.replace(backup_invalid_path(path))
            except OSError:
                pass
        return None


def write_json(path: Path, payload: Any) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        raise ValueError(f"Поле '{field_name}' обов'язкове.")
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"Поле '{field_name}' має бути у форматі YYYY-MM-DD.") from error


def as_float(
    value: Any,
    field_name: str,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Поле '{field_name}' має бути числом.") from error
    if not math.isfinite(parsed):
        raise ValueError(f"Поле '{field_name}' має бути скінченним числом.")
    if parsed < minimum:
        raise ValueError(f"Поле '{field_name}' не може бути меншим за {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"Поле '{field_name}' не може бути більшим за {maximum}.")
    return round_money(parsed)


def as_int(
    value: Any,
    field_name: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Поле '{field_name}' має бути цілим числом.") from error
    if parsed < minimum:
        raise ValueError(f"Поле '{field_name}' не може бути меншим за {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"Поле '{field_name}' не може бути більшим за {maximum}.")
    return parsed


def default_visible_modes() -> dict[str, bool]:
    return {mode: True for mode in MODE_ORDER}


def first_visible_mode(visible_modes: dict[str, bool]) -> str:
    for mode in MODE_ORDER:
        if visible_modes.get(mode):
            return mode
    return "base"


def normalize_visible_modes(raw_value: Any) -> dict[str, bool]:
    defaults = default_visible_modes()
    if not isinstance(raw_value, dict):
        return defaults
    normalized = {mode: as_bool(raw_value.get(mode, defaults[mode])) for mode in MODE_ORDER}
    if not any(normalized.values()):
        normalized["base"] = True
    return normalized


def normalize_active_mode(raw_value: Any, visible_modes: dict[str, bool]) -> str:
    candidate = str(raw_value or "").strip()
    if candidate not in MODE_ORDER:
        candidate = "base"
    if not visible_modes.get(candidate):
        candidate = first_visible_mode(visible_modes)
    return candidate


def balance_date_value(value: Any, fallback: date) -> date:
    if value in (None, ""):
        return fallback
    return as_date(value, "balance_date")


def derive_end_date(balance_date: date, forecast_days: int) -> date:
    return balance_date + timedelta(days=forecast_days - 1)


def default_settings(balance_date: date | None = None) -> dict[str, Any]:
    current_date = balance_date or date.today()
    forecast_days = 30
    return {
        "current_balance": 24000.0,
        "balance_date": current_date.isoformat(),
        "forecast_days": forecast_days,
        "end_date": derive_end_date(current_date, forecast_days).isoformat(),
        "next_income_date": (current_date + timedelta(days=14)).isoformat(),
        "next_income_amount": 18000.0,
        "savings_goal_percent": 20.0,
        "required_expense_percent": 3.0,
        "free_money_percent": 5.0,
        "waterline_percent": DEFAULT_WATERLINE_PERCENT,
        "visible_modes": default_visible_modes(),
        "active_mode": "base",
    }


def income_in_horizon(settings: dict[str, Any]) -> float:
    start = as_date(settings["balance_date"], "balance_date")
    end = as_date(settings["end_date"], "end_date")
    income_date = as_date(settings["next_income_date"], "next_income_date")
    if start <= income_date <= end:
        return settings["next_income_amount"]
    return 0.0


def resource_within_horizon(settings: dict[str, Any]) -> float:
    return round_money(settings["current_balance"] + income_in_horizon(settings))


def waterline_amount(settings: dict[str, Any]) -> float:
    return round_money(settings["current_balance"] * settings["waterline_percent"] / 100)


def savings_target_amount(settings: dict[str, Any], *, use_savings: bool) -> float:
    if not use_savings:
        return 0.0
    return round_money(resource_within_horizon(settings) * settings["savings_goal_percent"] / 100)


def required_percent_for_mode(settings: dict[str, Any], mode_key: str) -> float:
    percent = settings["required_expense_percent"] * MODE_CONFIG[mode_key]["expense_multiplier"]
    return round_percent(min(max(percent, 0.0), 100.0))


def percent_from_amount(amount: float, resource: float) -> float:
    if resource <= 0:
        return 0.0
    return round_percent(min(max((amount / resource) * 100, 0.0), 100.0))


def percent_from_daily_amount(amount: float, balance: float) -> float:
    if balance <= 0:
        return 0.0
    return round_percent(min(max((amount / balance) * 100, 0.0), 100.0))


def split_event_line(line: str) -> list[str]:
    for delimiter in (";", "|"):
        if delimiter in line:
            parts = [part.strip() for part in line.split(delimiter, 2)]
            if len(parts) == 3:
                return parts
    raise ValueError("Подія має бути у форматі YYYY-MM-DD;Назва;Сума.")


def parse_event_date_token(token: str, reference_date: date | None = None) -> date:
    cleaned = token.strip()
    try:
        return as_date(cleaned, "event_date")
    except ValueError:
        if reference_date is None:
            raise ValueError(f"Невірна дата події: {token}")
    try:
        day_offset = int(cleaned)
    except ValueError as error:
        raise ValueError(f"Невірна дата події: {token}") from error
    if day_offset < 1:
        raise ValueError("Номер дня події має бути від 1.")
    return reference_date + timedelta(days=day_offset - 1)


def normalize_events(raw_events: Any, reference_date: date | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if raw_events is None:
        return normalized
    if isinstance(raw_events, str):
        for line in [item.strip() for item in raw_events.splitlines() if item.strip()]:
            raw_date, raw_name, raw_amount = split_event_line(line)
            normalized.append(
                {
                    "date": parse_event_date_token(raw_date, reference_date).isoformat(),
                    "name": raw_name or "Подія",
                    "amount": as_float(raw_amount, "event_amount", minimum=0.0),
                }
            )
    elif isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "date": parse_event_date_token(str(item.get("date", "")).strip(), reference_date).isoformat(),
                    "name": str(item.get("name") or item.get("label") or "Подія").strip(),
                    "amount": as_float(item.get("amount", 0), "event_amount", minimum=0.0),
                }
            )
    else:
        raise ValueError("Невірний формат списку подій.")
    normalized.sort(key=lambda item: (item["date"], item["name"]))
    return normalized


def events_to_text(events: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{event['date']};{event['name']};{round_money(event['amount']):.2f}" for event in events
    )


def normalize_settings(
    raw_settings: dict[str, Any] | None,
    *,
    fallback_balance_date: date,
    override_balance_date: date | None = None,
) -> dict[str, Any]:
    source = raw_settings or {}
    balance_date = override_balance_date or balance_date_value(source.get("balance_date"), fallback_balance_date)
    defaults = default_settings(balance_date)
    forecast_days = as_int(
        source.get("forecast_days", defaults["forecast_days"]),
        "forecast_days",
        minimum=1,
        maximum=MAX_FORECAST_DAYS,
    )
    visible_modes = normalize_visible_modes(source.get("visible_modes"))
    active_mode = normalize_active_mode(source.get("active_mode", defaults["active_mode"]), visible_modes)
    return {
        "current_balance": as_float(
            source.get("current_balance", defaults["current_balance"]),
            "current_balance",
            minimum=0.0,
        ),
        "balance_date": balance_date.isoformat(),
        "forecast_days": forecast_days,
        "end_date": derive_end_date(balance_date, forecast_days).isoformat(),
        "next_income_date": as_date(
            source.get("next_income_date", defaults["next_income_date"]),
            "next_income_date",
        ).isoformat(),
        "next_income_amount": as_float(
            source.get("next_income_amount", defaults["next_income_amount"]),
            "next_income_amount",
            minimum=0.0,
        ),
        "savings_goal_percent": as_float(
            source.get("savings_goal_percent", defaults["savings_goal_percent"]),
            "savings_goal_percent",
            minimum=0.0,
            maximum=100.0,
        ),
        "required_expense_percent": as_float(
            source.get("required_expense_percent", defaults["required_expense_percent"]),
            "required_expense_percent",
            minimum=0.0,
            maximum=100.0,
        ),
        "free_money_percent": as_float(
            source.get("free_money_percent", defaults["free_money_percent"]),
            "free_money_percent",
            minimum=0.0,
            maximum=100.0,
        ),
        "waterline_percent": as_float(
            source.get("waterline_percent", defaults["waterline_percent"]),
            "waterline_percent",
            minimum=0.0,
            maximum=100.0,
        ),
        "visible_modes": visible_modes,
        "active_mode": active_mode,
    }


def migrate_previous_settings(raw_settings: dict[str, Any], scenarios: dict[str, Any] | None) -> dict[str, Any]:
    fallback_date = date.today()
    start = balance_date_value(raw_settings.get("start_date"), fallback_date)
    end = balance_date_value(raw_settings.get("end_date"), start)
    forecast_days = max((end - start).days + 1, 1)
    current_balance = round_money(raw_settings.get("initial_balance", raw_settings.get("current_balance", 0)))
    next_income_amount = round_money(raw_settings.get("next_income_amount", 0))
    next_income_date = raw_settings.get("next_income_date", (start + timedelta(days=14)).isoformat())
    target_amount = round_money(raw_settings.get("target_savings_amount", 0))
    resource = current_balance
    try:
        income_date = as_date(next_income_date, "next_income_date")
        if start <= income_date <= end:
            resource = round_money(resource + next_income_amount)
    except ValueError:
        next_income_date = (start + timedelta(days=14)).isoformat()
    base_summary = (scenarios or {}).get("base", {}).get("summary", {}) if isinstance(scenarios, dict) else {}
    base_limit = round_money(base_summary.get("base_daily_limit", raw_settings.get("daily_expense", 0)))
    return {
        "current_balance": current_balance,
        "balance_date": start.isoformat(),
        "forecast_days": forecast_days,
        "next_income_date": next_income_date,
        "next_income_amount": next_income_amount,
        "savings_goal_percent": percent_from_amount(target_amount, resource),
        "required_expense_percent": percent_from_daily_amount(base_limit, current_balance),
        "free_money_percent": 0.0,
        "waterline_percent": raw_settings.get("waterline_percent", DEFAULT_WATERLINE_PERCENT),
        "visible_modes": default_visible_modes(),
        "active_mode": "force_majeure" if as_bool(raw_settings.get("stress_mode", False)) else "base",
    }


def migrate_legacy_budget(raw_budget: dict[str, Any]) -> dict[str, Any]:
    current_balance = round_money(raw_budget.get("available_budget", 0) + raw_budget.get("free_money", 0))
    forecast_days = as_int(raw_budget.get("days", 30), "days", minimum=1, maximum=MAX_FORECAST_DAYS)
    current_date = date.today()
    return {
        "current_balance": current_balance,
        "balance_date": current_date.isoformat(),
        "forecast_days": forecast_days,
        "next_income_date": raw_budget.get("next_income_date", (current_date + timedelta(days=14)).isoformat()),
        "next_income_amount": raw_budget.get("next_income_amount", 0),
        "savings_goal_percent": raw_budget.get("monthly_savings_percent", 0),
        "required_expense_percent": percent_from_daily_amount(raw_budget.get("daily_expense", 0), current_balance),
        "free_money_percent": 0.0,
        "waterline_percent": DEFAULT_WATERLINE_PERCENT,
        "visible_modes": default_visible_modes(),
        "active_mode": "base",
    }


def normalize_history(items: Any) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return history
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_settings = item.get("settings")
        raw_summary = item.get("summary")
        created_at = str(item.get("created_at", "")).strip()
        if not isinstance(raw_settings, dict) or not isinstance(raw_summary, dict) or not created_at:
            continue
        if "current_balance" in raw_settings or "forecast_days" in raw_settings:
            migrated = raw_settings
        elif "initial_balance" in raw_settings or "start_date" in raw_settings:
            migrated = migrate_previous_settings(raw_settings, None)
        else:
            continue
        try:
            balance_date = balance_date_value(migrated.get("balance_date"), date.today())
            settings = normalize_settings(migrated, fallback_balance_date=balance_date, override_balance_date=balance_date)
        except ValueError:
            continue
        settings["events_text"] = str(raw_settings.get("events_text", ""))
        history.append(
            {
                "created_at": created_at,
                "settings": settings,
                "summary": {
                    "active_mode": str(raw_summary.get("active_mode", settings["active_mode"])),
                    "current_final_balance": round_money(raw_summary.get("current_final_balance", 0)),
                    "base_final_balance": round_money(raw_summary.get("base_final_balance", 0)),
                    "shock_day": raw_summary.get("shock_day"),
                },
            }
        )
    return history[:HISTORY_LIMIT]


def build_horizon(settings: dict[str, Any]) -> list[date]:
    start = as_date(settings["balance_date"], "balance_date")
    return [start + timedelta(days=index) for index in range(settings["forecast_days"])]


def run_scenario(settings: dict[str, Any], events: list[dict[str, Any]], mode_key: str, *, shock_day: int | None = None) -> dict[str, Any]:
    horizon = build_horizon(settings)
    config = MODE_CONFIG[mode_key]
    income_date = as_date(settings["next_income_date"], "next_income_date")
    income_amount = settings["next_income_amount"]
    required_percent = required_percent_for_mode(settings, mode_key)
    savings_target = savings_target_amount(settings, use_savings=config["use_savings"])
    waterline = waterline_amount(settings)
    end_date = as_date(settings["end_date"], "end_date")

    event_map: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_map.setdefault(event["date"], []).append(event)
    daily_events: list[list[dict[str, Any]]] = []
    event_totals: list[float] = []
    for current_day in horizon:
        items = event_map.get(current_day.isoformat(), [])
        daily_events.append(items)
        event_totals.append(round_money(sum(item["amount"] for item in items)))
    remaining_event_costs = [0.0] * (len(horizon) + 1)
    for index in range(len(horizon) - 1, -1, -1):
        remaining_event_costs[index] = round_money(remaining_event_costs[index + 1] + event_totals[index])

    income_day_index = None
    if horizon and horizon[0] <= income_date <= end_date:
        income_day_index = (income_date - horizon[0]).days

    current_balance = settings["current_balance"]
    cycle_floor = round_money(max(current_balance, 0.0) * settings["free_money_percent"] / 100)
    free_money_bucket = cycle_floor
    rows: list[dict[str, Any]] = []

    for index, current_day in enumerate(horizon):
        remaining_days = len(horizon) - index
        future_income = income_amount if income_day_index is not None and income_day_index >= index else 0.0
        safe_limit = max((current_balance + future_income - savings_target - remaining_event_costs[index]) / remaining_days, 0.0)
        safe_limit = round_money(safe_limit)
        income_received = income_amount if income_day_index == index else 0.0
        spendable_balance = round_money(current_balance + income_received)
        required_spend = round_money(spendable_balance * required_percent / 100)
        event_total = event_totals[index]
        balance_after_spend = round_money(spendable_balance - required_spend - event_total)
        shock_loss = 0.0
        if config["shock"] and shock_day == index + 1:
            shock_loss = round_money(max(balance_after_spend, 0.0) * 0.2)
        balance_end = round_money(balance_after_spend - shock_loss)
        total_spend = round_money(required_spend + event_total + shock_loss)
        free_money_reset = total_spend > 0.0
        free_money_accrued = 0.0
        if free_money_reset:
            cycle_floor = round_money(max(balance_end, 0.0) * settings["free_money_percent"] / 100)
            free_money_bucket = cycle_floor
        else:
            free_money_accrued = cycle_floor
            free_money_bucket = round_money(free_money_bucket + cycle_floor)
        total_assets = round_money(balance_end + free_money_bucket)
        rows.append(
            {
                "day": index + 1,
                "date": current_day.isoformat(),
                "income": income_received,
                "events": event_total,
                "event_names": [item["name"] for item in daily_events[index]],
                "safe_limit": safe_limit,
                "required_spend": required_spend,
                "total_spend": total_spend,
                "balance_start": round_money(current_balance),
                "balance_end": balance_end,
                "free_money_bucket": free_money_bucket,
                "free_money_floor": cycle_floor,
                "free_money_accrued": free_money_accrued,
                "free_money_reset": free_money_reset,
                "total_assets": total_assets,
                "below_waterline": total_assets <= waterline + 0.009,
                "stress_triggered": shock_loss > 0.0,
                "shock_loss": shock_loss,
            }
        )
        current_balance = balance_end

    waterline_day = next((row["day"] for row in rows if row["below_waterline"]), None)
    negative_day = next((row["day"] for row in rows if row["balance_end"] < 0.0), None)
    income_day = income_day_index + 1 if income_day_index is not None else None
    return {
        "key": mode_key,
        "label": MODE_LABELS[mode_key],
        "days": rows,
        "summary": {
            "final_balance": rows[-1]["balance_end"] if rows else round_money(settings["current_balance"]),
            "final_total_assets": rows[-1]["total_assets"] if rows else round_money(settings["current_balance"]),
            "final_free_money_bucket": rows[-1]["free_money_bucket"] if rows else 0.0,
            "tightest_safe_limit": round_money(min((row["safe_limit"] for row in rows), default=0.0)),
            "highest_required_spend": round_money(max((row["required_spend"] for row in rows), default=0.0)),
            "lowest_total_assets": round_money(min((row["total_assets"] for row in rows), default=settings["current_balance"])),
            "income_day": income_day,
            "waterline_day": waterline_day,
            "negative_day": negative_day,
            "shock_day": shock_day if config["shock"] else None,
            "savings_target_amount": savings_target,
            "required_expense_percent": required_percent,
            "free_money_percent": settings["free_money_percent"],
            "base_safe_limit": rows[0]["safe_limit"] if rows else 0.0,
            "waterline_amount": waterline,
        },
    }


def canonical_active_mode(settings: dict[str, Any]) -> str:
    return normalize_active_mode(settings.get("active_mode"), settings.get("visible_modes", {}))


def build_table(settings: dict[str, Any], scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    active_mode = canonical_active_mode(settings)
    table: list[dict[str, Any]] = []
    for index, base_row in enumerate(scenarios["base"]["days"]):
        mode_values = {mode: scenarios[mode]["days"][index]["total_assets"] for mode in MODE_ORDER}
        below_waterline = {mode: scenarios[mode]["days"][index]["below_waterline"] for mode in MODE_ORDER}
        table.append(
            {
                "day": base_row["day"],
                "date": base_row["date"],
                "income": base_row["income"],
                "events": base_row["events"],
                "event_names": base_row["event_names"],
                "modes": mode_values,
                "below_waterline": below_waterline,
                "current": mode_values[active_mode],
                "current_below_waterline": below_waterline[active_mode],
                "stress_triggered": scenarios[active_mode]["days"][index]["stress_triggered"],
            }
        )
    return table


def build_chart_data(settings: dict[str, Any], scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    active_mode = canonical_active_mode(settings)
    labels = [row["date"] for row in scenarios["base"]["days"]]
    return {
        "labels": labels,
        "modes": {mode: [row["total_assets"] for row in scenarios[mode]["days"]] for mode in MODE_ORDER},
        "current": [row["total_assets"] for row in scenarios[active_mode]["days"]],
        "waterline": [waterline_amount(settings) for _ in labels],
        "active_mode": active_mode,
        "visible_modes": settings["visible_modes"],
    }


def build_response(document: dict[str, Any]) -> dict[str, Any]:
    settings = dict(document["settings"])
    settings["active_mode"] = canonical_active_mode(settings)
    settings["end_date"] = derive_end_date(as_date(settings["balance_date"], "balance_date"), settings["forecast_days"]).isoformat()
    settings["events_text"] = events_to_text(document["events"])
    settings["resource_within_horizon"] = resource_within_horizon(settings)
    settings["waterline_amount"] = waterline_amount(settings)
    settings["savings_target_amount"] = savings_target_amount(settings, use_savings=True)
    settings["base_safe_limit"] = document["scenarios"]["base"]["summary"]["base_safe_limit"]
    return {
        "settings": settings,
        "events": document["events"],
        "history": document["history"],
        "scenarios": document["scenarios"],
        "table": build_table(settings, document["scenarios"]),
        "chart_data": build_chart_data(settings, document["scenarios"]),
        "meta": {
            "mode_order": list(MODE_ORDER),
            "mode_labels": MODE_LABELS,
            "visible_keys": [mode for mode in MODE_ORDER if settings["visible_modes"].get(mode)],
            "active_mode": settings["active_mode"],
        },
    }


def build_document(settings: dict[str, Any], events: list[dict[str, Any]], history: list[dict[str, Any]], *, shock_day: int | None = None) -> dict[str, Any]:
    if shock_day is None or not isinstance(shock_day, int) or not (1 <= shock_day <= settings["forecast_days"]):
        shock_day = random.randint(1, settings["forecast_days"])
    settings = dict(settings)
    settings["active_mode"] = canonical_active_mode(settings)
    scenarios = {
        mode: run_scenario(settings, events, mode, shock_day=shock_day if MODE_CONFIG[mode]["shock"] else None)
        for mode in MODE_ORDER
    }
    return {"settings": settings, "events": events, "history": history[:HISTORY_LIMIT], "scenarios": scenarios}


def snapshot_entry(document: dict[str, Any]) -> dict[str, Any]:
    active_mode = canonical_active_mode(document["settings"])
    snapshot_settings = dict(document["settings"])
    snapshot_settings["events_text"] = events_to_text(document["events"])
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "settings": snapshot_settings,
        "summary": {
            "active_mode": active_mode,
            "current_final_balance": document["scenarios"][active_mode]["summary"]["final_total_assets"],
            "base_final_balance": document["scenarios"]["base"]["summary"]["final_total_assets"],
            "shock_day": document["scenarios"]["force_majeure"]["summary"]["shock_day"],
        },
    }


def normalize_current_document(raw_document: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_document, dict):
        return None
    raw_settings = raw_document.get("settings")
    if not isinstance(raw_settings, dict):
        return None
    if "current_balance" not in raw_settings and "forecast_days" not in raw_settings:
        return None
    balance_date = balance_date_value(raw_settings.get("balance_date"), date.today())
    settings = normalize_settings(raw_settings, fallback_balance_date=balance_date, override_balance_date=balance_date)
    events = normalize_events(raw_document.get("events", []), balance_date)
    history = normalize_history(raw_document.get("history", []))
    saved_shock_day = raw_document.get("scenarios", {}).get("force_majeure", {}).get("summary", {}).get("shock_day")
    return build_document(settings, events, history, shock_day=saved_shock_day)


def migrate_previous_document(raw_document: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_document, dict):
        return None
    raw_settings = raw_document.get("settings")
    if not isinstance(raw_settings, dict):
        return None
    if "initial_balance" not in raw_settings and "start_date" not in raw_settings:
        return None
    migrated = migrate_previous_settings(raw_settings, raw_document.get("scenarios"))
    balance_date = balance_date_value(migrated.get("balance_date"), date.today())
    settings = normalize_settings(migrated, fallback_balance_date=balance_date, override_balance_date=balance_date)
    events = normalize_events(raw_document.get("events", []), balance_date)
    history = normalize_history(raw_document.get("history", []))
    saved_shock_day = raw_document.get("scenarios", {}).get("force_majeure", {}).get("summary", {}).get("shock_day")
    return build_document(settings, events, history, shock_day=saved_shock_day)


def migrate_legacy_document() -> dict[str, Any] | None:
    raw_budget = read_json(LEGACY_BUDGET_FILE)
    if not isinstance(raw_budget, dict):
        return None
    migrated = migrate_legacy_budget(raw_budget)
    balance_date = balance_date_value(migrated.get("balance_date"), date.today())
    settings = normalize_settings(migrated, fallback_balance_date=balance_date, override_balance_date=balance_date)
    events = normalize_events(raw_budget.get("events_text", ""), balance_date)
    history = normalize_history(read_json(LEGACY_HISTORY_FILE))
    return build_document(settings, events, history)


def load_document() -> dict[str, Any]:
    current = read_json(BUDGET_FILE, backup_invalid=True)
    normalized = normalize_current_document(current)
    if normalized is not None:
        write_json(BUDGET_FILE, normalized)
        return normalized
    migrated_previous = migrate_previous_document(current)
    if migrated_previous is not None:
        write_json(BUDGET_FILE, migrated_previous)
        return migrated_previous
    migrated_legacy = migrate_legacy_document()
    if migrated_legacy is not None:
        write_json(BUDGET_FILE, migrated_legacy)
        return migrated_legacy
    today = date.today()
    settings = normalize_settings(default_settings(today), fallback_balance_date=today, override_balance_date=today)
    document = build_document(settings, [], [])
    write_json(BUDGET_FILE, document)
    return document


def calculate_document(payload: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    today = date.today()
    settings = normalize_settings(payload, fallback_balance_date=today, override_balance_date=today)
    events = normalize_events(payload.get("events_text", ""), today)
    normalized_history = normalize_history(history)
    document = build_document(settings, events, normalized_history)
    if as_bool(payload.get("save_history", True)):
        normalized_history.insert(0, snapshot_entry(document))
        document["history"] = normalized_history[:HISTORY_LIMIT]
    return document


def api_error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    if request.path in {"/load", "/calculate", "/reset"}:
        return api_error("Внутрішня помилка сервера.", 500)
    raise error


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/load")
def load_route():
    return jsonify(build_response(load_document()))


@app.post("/calculate")
def calculate_route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("Очікувався JSON з параметрами прогнозу.")
    try:
        current_document = load_document()
        document = calculate_document(payload, current_document.get("history", []))
        write_json(BUDGET_FILE, document)
    except ValueError as error:
        return api_error(str(error))
    return jsonify(build_response(document))


@app.post("/reset")
def reset_route():
    today = date.today()
    settings = normalize_settings(default_settings(today), fallback_balance_date=today, override_balance_date=today)
    document = build_document(settings, [], [])
    write_json(BUDGET_FILE, document)
    return jsonify(build_response(document))


if __name__ == "__main__":
    app.run(debug=True)
