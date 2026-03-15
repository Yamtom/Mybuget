from datetime import datetime
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from calculator import compute
from models import InputSchema

BASE = Path(__file__).parent
BUDGET = BASE / "budget.json"

app = FastAPI(title="Budget Horizon")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.get("/")
def index():
    return FileResponse(str(BASE / "static" / "index.html"))


@app.get("/dashboard")
def dashboard():
    return FileResponse(str(BASE / "static" / "dashboard.html"))


@app.get("/load")
def load():
    if not BUDGET.exists():
        raise HTTPException(404, "Бюджет не знайдено")
    return json.loads(BUDGET.read_text(encoding="utf-8"))


@app.post("/calculate")
def calculate(inp: InputSchema):
    try:
        result = compute(inp)
    except ValueError as e:
        raise HTTPException(400, str(e))
    settings = inp.model_dump()
    doc = {
        "settings": settings,
        "table": result["table"],
        "chart_data": result["chart_data"],
        "summary": result["summary"],
        "meta": {
            "last_calculated": datetime.now().isoformat(timespec="seconds"),
            "warnings": result["warnings"],
        },
    }
    BUDGET.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


@app.post("/save-table")
def save_table(payload: dict):
    if not BUDGET.exists():
        raise HTTPException(404, "Бюджет не знайдено")
    rows = payload.get("table")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "Очікується непорожній масив table")

    normalized = []
    for idx, row in enumerate(rows, start=1):
        try:
            normalized.append({
                "day": int(row.get("day", idx)),
                "date": str(row["date"]),
                "balance": float(row["balance"]),
                "required_expense": float(row["required_expense"]),
                "free_money": float(row["free_money"]),
            })
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"Некоректний рядок table[{idx - 1}]")

    doc = json.loads(BUDGET.read_text(encoding="utf-8"))
    waterline = float(doc.get("chart_data", {}).get("waterline", 0.0))
    doc["table"] = normalized
    doc["chart_data"] = {
        "labels": [r["date"] for r in normalized],
        "datasets": {"balance": [round(r["balance"], 2) for r in normalized]},
        "waterline": round(waterline, 2),
    }
    doc.setdefault("meta", {})["last_calculated"] = datetime.now().isoformat(timespec="seconds")
    BUDGET.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "saved"}


@app.delete("/reset")
def reset():
    BUDGET.unlink(missing_ok=True)
    return {"status": "reset"}
