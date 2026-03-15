from datetime import date as dt
from pydantic import BaseModel, Field, model_validator


class BalancePoint(BaseModel):
    date: str
    balance: float = Field(gt=0)


class InputSchema(BaseModel):
    available_balance: float = Field(gt=0)
    date_start: str
    date_end: str
    save_days: int = Field(ge=1, le=365)
    savings_percent: float = Field(ge=0, le=100)
    required_expense_percent: float = Field(ge=0, le=100)
    free_money_percent: float = Field(ge=0, le=100)
    waterline_percent: float = Field(default=10.0, ge=0, le=100)
    balance_history: list[BalancePoint] = []

    @model_validator(mode="after")
    def check_dates(self):
        d0, d1 = dt.fromisoformat(self.date_start), dt.fromisoformat(self.date_end)
        if d1 < d0:
            raise ValueError("Дата кінця повинна бути не раніше дати старту")
        if self.save_days > (d1 - d0).days + 1:
            raise ValueError("Кількість днів заощадження не може перевищувати довжину періоду")
        return self
