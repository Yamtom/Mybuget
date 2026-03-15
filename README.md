# Budget Horizon

Мінімалістичний застосунок для накопичувального прогнозування особистого бюджету.

## Запуск

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000
```

### Спрощений запуск на Windows (рекомендовано)

```powershell
cd C:\Users\grigo\Desktop\Mybuget\Mybuget
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Відкривати тільки: `http://127.0.0.1:8000`

Якщо бачите `Field required`, найчастіша причина: запущено кілька серверів на різних портах.

Перевірка портів:

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -State Listen | Select-Object LocalPort,OwningProcess
```

Залиште тільки один сервер (8000).

## API

| Метод | URL | Дія |
| --- | --- | --- |
| GET | / | Форма введення |
| GET | /dashboard | Дашборд |
| GET | /load | Повертає поточний budget.json |
| POST | /calculate | Рахує один прогноз, зберігає budget.json |
| POST | /save-table | Зберігає зміни, внесені напряму в таблицю |
| DELETE | /reset | Видаляє budget.json |

## Вхідні поля

- available_balance: наявний баланс на момент вводу
- date_start, date_end: період прогнозу
- save_days: дні, за які треба накопичити ціль
- savings_percent: відсоток заощадження за період
- required_expense_percent: щоденні необхідні витрати у %
- free_money_percent: щоденний % вільних грошей
- waterline_percent: ватерлінія у % від наявного балансу
- balance_history[]: історія балансів для глобальної витратної бази

## UX

- Історія балансів автозаповнюється на стартовій формі з останнього `budget.json`.
- У дашборді можна редагувати значення напряму в таблиці та зберігати кнопкою `Зберегти зміни таблиці`.

## Вихід таблиці

Кожен день містить:

- day
- date
- balance
- required_expense
- free_money

## Структура

```text
main.py            # FastAPI маршрути
models.py          # Pydantic схеми
calculator.py      # Логіка одного прогнозу
budget.json        # Стан (auto-generated)
static/index.html  # Форма введення
static/dashboard.html  # Дашборд + Chart.js
static/style.css   # Стилі (responsive >= 768px)
requirements.txt   # fastapi uvicorn[standard] pydantic
```
