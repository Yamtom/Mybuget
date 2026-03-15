const form = document.getElementById("calc-form");
const errorNode = document.getElementById("form-error");
const bodyNode = document.getElementById("projection-body");
const cardsNode = document.getElementById("scenario-cards");
const pointsNode = document.getElementById("critical-points");
const chartNode = document.getElementById("balance-chart");
const chartCaptionNode = document.getElementById("chart-caption");
const scenarioNameNode = document.getElementById("scenario-name");
const scenarioNoteNode = document.getElementById("selected-scenario-note");
const historyNode = document.getElementById("history-list");
const clearHistoryButton = document.getElementById("clear-history");
const corridorStateNode = document.getElementById("corridor-state");
const corridorCaptionNode = document.getElementById("corridor-caption");
const incomeCaptionNode = document.getElementById("income-caption");
const eventPreviewNode = document.getElementById("event-preview");

const metricNodes = {
    finalTotalAssets: document.getElementById("final-total-assets"),
    finalFreeMoney: document.getElementById("final-free-money"),
    targetReserve: document.getElementById("target-reserve"),
    tightestLimit: document.getElementById("tightest-limit"),
};

const numericFields = [
    "available_budget",
    "free_money",
    "next_income_amount",
    "monthly_savings_percent",
    "daily_expense",
    "days",
];

let forecastData = null;
let activeScenario = "base";

function asCurrency(value) {
    return new Intl.NumberFormat("uk-UA", {
        style: "currency",
        currency: "UAH",
        maximumFractionDigits: 2,
    }).format(Number(value) || 0);
}

function asDateLabel(value) {
    return new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
    }).format(new Date(value));
}

function asDateTimeLabel(value) {
    return new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
        timeStyle: "short",
    }).format(new Date(value));
}

function asPercent(value) {
    return `${Number(value || 0).toFixed(1)}%`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function scenarioState() {
    if (!forecastData) {
        return null;
    }

    return forecastData.scenarios[activeScenario] || forecastData.scenarios.base || null;
}

function applyInputs(inputs) {
    Object.entries(inputs).forEach(([key, value]) => {
        const field = form.elements.namedItem(key);
        if (field) {
            field.value = value;
        }
    });
}

function formPayload() {
    const payload = Object.fromEntries(new FormData(form).entries());

    numericFields.forEach((key) => {
        payload[key] = key === "days" ? Number.parseInt(payload[key], 10) : Number.parseFloat(payload[key]);
    });

    payload.events_text = String(payload.events_text || "").trim();
    return payload;
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || "Не вдалося виконати запит.");
    }

    return data;
}

async function requestForecast(payload, saveHistory = true) {
    return fetchJson("/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, save_history: saveHistory }),
    });
}

function scenarioFootnote(item) {
    if (item.zero_day) {
        return `Ламається на ${item.zero_day}-й день.`;
    }

    if (item.waterline_day) {
        return `Доходить до ватерлінії на ${item.waterline_day}-й день.`;
    }

    if (item.reserve_draw_day) {
        return `Їсть вільні гроші з ${item.reserve_draw_day}-го дня.`;
    }

    if (item.income_day) {
        return `Дохід заходить на ${item.income_day}-й день.`;
    }

    return "Тримає горизонт без критичних провалів.";
}

function corridorStatus() {
    if (!forecastData) {
        return {
            level: "idle",
            title: "Чекає на розрахунок",
            message: "Коридор з’явиться після першого прогнозу.",
        };
    }

    const scenario = scenarioState();
    const economy = forecastData.scenarios.economy?.projection || [];
    const aggressive = forecastData.scenarios.aggressive?.projection || [];

    let firstOutsideDay = null;
    for (let index = 0; index < scenario.projection.length; index += 1) {
        const activeRow = scenario.projection[index];
        const economyRow = economy[index];
        const aggressiveRow = aggressive[index];

        if (!economyRow || !aggressiveRow) {
            continue;
        }

        const lower = Math.min(economyRow.end_total_assets, aggressiveRow.end_total_assets);
        const upper = Math.max(economyRow.end_total_assets, aggressiveRow.end_total_assets);

        if (activeRow.end_total_assets < lower - 0.01 || activeRow.end_total_assets > upper + 0.01) {
            firstOutsideDay = activeRow.day;
            break;
        }
    }

    if (firstOutsideDay) {
        return {
            level: "critical",
            title: `Поза коридором з ${firstOutsideDay}-го дня`,
            message: "Поточний режим вибивається з контрольованої зони між економним та агресивним сценаріями.",
        };
    }

    if (scenario.summary.waterline_day) {
        return {
            level: "warning",
            title: "Всередині коридору, але на ватерлінії",
            message: `Режим ще в межах коридору, проте вже торкається резерву на ${scenario.summary.waterline_day}-й день.`,
        };
    }

    if (scenario.summary.reserve_draw_day) {
        return {
            level: "warning",
            title: "Всередині коридору, але їсть подушку",
            message: `З ${scenario.summary.reserve_draw_day}-го дня починається використання вільних грошей як подушки.`,
        };
    }

    return {
        level: "stable",
        title: "Всередині коридору",
        message: "Темп витрат лишається у безпечній зоні між економним та агресивним режимами.",
    };
}

function renderSummary() {
    const scenario = scenarioState();
    if (!scenario) {
        return;
    }

    const { summary, label, description } = scenario;
    const corridor = corridorStatus();
    const incomeDay = forecastData.meta?.income_day;
    const incomeDate = forecastData.meta?.next_income_date;

    scenarioNameNode.textContent = `${label} режим`;
    scenarioNoteNode.textContent = `${description} ${summary.narrative}`;
    scenarioNoteNode.dataset.level = summary.risk_level;

    corridorStateNode.textContent = corridor.title;
    corridorStateNode.className = `status-pill level-${corridor.level}`;
    corridorCaptionNode.textContent = corridor.message;

    if (incomeDay) {
        incomeCaptionNode.textContent =
            `Ймовірний дохід ${asCurrency(forecastData.meta.next_income_amount)} заходить ${asDateLabel(incomeDate)} ` +
            `на ${incomeDay}-й день прогнозу.`;
    } else {
        incomeCaptionNode.textContent =
            `Ймовірний дохід ${asCurrency(forecastData.meta.next_income_amount)} запланований на ${asDateLabel(incomeDate)}, ` +
            "але він не входить у поточний горизонт прогнозу.";
    }

    metricNodes.finalTotalAssets.textContent = asCurrency(summary.final_total_assets);
    metricNodes.finalFreeMoney.textContent = asCurrency(summary.final_free_money);
    metricNodes.targetReserve.textContent = `${asCurrency(summary.target_reserve)} · ${asPercent(summary.monthly_savings_percent)}`;
    metricNodes.tightestLimit.textContent = asCurrency(summary.tightest_limit);
}

function renderEventPreview() {
    if (!forecastData) {
        eventPreviewNode.innerHTML = `<p class="placeholder compact">Немає даних для подій.</p>`;
        return;
    }

    const cards = [];
    const incomeDay = forecastData.meta?.income_day;
    const incomeDate = forecastData.meta?.next_income_date;

    cards.push(`
        <article class="event-card event-card-income">
            <span class="event-day">${incomeDay ? `${incomeDay}-й день` : "Поза горизонтом"}</span>
            <strong>Наступний дохід</strong>
            <p>${asCurrency(forecastData.meta.next_income_amount)}</p>
            <small>${escapeHtml(asDateLabel(incomeDate))}</small>
        </article>
    `);

    const events = forecastData.meta?.events || [];
    events.forEach((event) => {
        cards.push(`
            <article class="event-card">
                <span class="event-day">${event.day}-й день</span>
                <strong>${escapeHtml(event.label)}</strong>
                <p>${asCurrency(event.amount)}</p>
            </article>
        `);
    });

    eventPreviewNode.innerHTML = cards.join("");
}

function renderScenarioCards() {
    if (!forecastData) {
        return;
    }

    cardsNode.innerHTML = "";

    forecastData.comparison.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `scenario-card risk-${item.risk_level} ${item.key === activeScenario ? "active" : ""}`;
        button.innerHTML = `
            <span class="scenario-chip">${escapeHtml(item.label)}</span>
            <h3>${escapeHtml(item.risk_label)}</h3>
            <p class="scenario-copy">${escapeHtml(item.description)}</p>
            <dl class="scenario-stats">
                <div>
                    <dt>Фініш</dt>
                    <dd>${asCurrency(item.final_total_assets)}</dd>
                </div>
                <div>
                    <dt>Вільні</dt>
                    <dd>${asCurrency(item.final_free_money)}</dd>
                </div>
                <div>
                    <dt>Резерв</dt>
                    <dd>${asCurrency(item.target_reserve)}</dd>
                </div>
                <div>
                    <dt>Пайка</dt>
                    <dd>${asCurrency(item.tightest_limit)}</dd>
                </div>
            </dl>
            <p class="scenario-foot">${escapeHtml(scenarioFootnote(item))}</p>
        `;

        button.addEventListener("click", () => {
            activeScenario = item.key;
            renderActiveScenario();
        });

        cardsNode.appendChild(button);
    });
}

function renderCriticalPoints() {
    const scenario = scenarioState();
    if (!scenario) {
        return;
    }

    pointsNode.innerHTML = scenario.critical_points
        .map(
            (point) => `
                <article class="point-card point-${point.level}">
                    <div class="point-head">
                        <span class="point-badge">${point.day}-й день</span>
                        <h3>${escapeHtml(point.title)}</h3>
                    </div>
                    <p>${escapeHtml(point.message)}</p>
                </article>
            `
        )
        .join("");
}

function markerClass(row) {
    if (row.is_negative_day) {
        return "marker marker-negative";
    }

    if (row.is_waterline_day) {
        return "marker marker-waterline";
    }

    if (row.is_shock_day) {
        return "marker marker-shock";
    }

    if (row.is_income_day) {
        return "marker marker-income";
    }

    if (row.is_reserve_draw_day) {
        return "marker marker-reserve";
    }

    if (row.event_total > 0) {
        return "marker marker-event";
    }

    return "marker marker-stress";
}

function renderChart() {
    const scenario = scenarioState();
    const economy = forecastData?.scenarios?.economy;
    const aggressive = forecastData?.scenarios?.aggressive;

    if (!scenario || !economy || !aggressive) {
        chartNode.innerHTML = `<p class="placeholder">Недостатньо даних для графіка.</p>`;
        return;
    }

    const width = 980;
    const height = 360;
    const paddingX = 52;
    const paddingTop = 28;
    const paddingBottom = 38;
    const innerWidth = width - paddingX * 2;
    const innerHeight = height - paddingTop - paddingBottom;
    const activeRows = scenario.projection;
    const economyRows = economy.projection;
    const aggressiveRows = aggressive.projection;
    const xStep = activeRows.length > 1 ? innerWidth / (activeRows.length - 1) : 0;
    const xAt = (index) => paddingX + index * xStep;

    const upperBand = activeRows.map((_, index) => Math.max(economyRows[index].end_total_assets, aggressiveRows[index].end_total_assets));
    const lowerBand = activeRows.map((_, index) => Math.min(economyRows[index].end_total_assets, aggressiveRows[index].end_total_assets));
    const allValues = [
        ...upperBand,
        ...lowerBand,
        ...activeRows.map((row) => row.end_total_assets),
        scenario.summary.target_reserve,
    ];
    const minValue = Math.min(...allValues, 0);
    const maxValue = Math.max(...allValues, 0);
    const range = maxValue - minValue || 1;
    const yAt = (value) => paddingTop + ((maxValue - value) / range) * innerHeight;

    const upperPoints = upperBand.map((value, index) => `${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`);
    const lowerPoints = lowerBand
        .map((value, index) => `${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`)
        .reverse();
    const corridorShape = [...upperPoints, ...lowerPoints].join(" ");
    const activePoints = activeRows.map((row, index) => `${xAt(index).toFixed(2)},${yAt(row.end_total_assets).toFixed(2)}`).join(" ");
    const waterlineY = yAt(scenario.summary.target_reserve).toFixed(2);

    const axisValues = [maxValue, scenario.summary.target_reserve, 0, minValue]
        .filter((value, index, list) => list.findIndex((item) => Math.abs(item - value) < 0.01) === index)
        .sort((left, right) => right - left);

    const axisLines = axisValues
        .map((value) => {
            const y = yAt(value).toFixed(2);
            const labelClass =
                Math.abs(value - scenario.summary.target_reserve) < 0.01
                    ? "axis-label axis-waterline"
                    : Math.abs(value) < 0.01
                        ? "axis-label axis-zero"
                        : "axis-label";

            return `
                <g class="${labelClass}">
                    <line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}"></line>
                    <text x="${paddingX + 8}" y="${Number(y) - 8}">${escapeHtml(asCurrency(value))}</text>
                </g>
            `;
        })
        .join("");

    const dayTicks = activeRows
        .filter((row, index) => index === 0 || index === activeRows.length - 1 || row.day % Math.max(1, Math.round(activeRows.length / 6)) === 0)
        .map((row) => {
            const x = xAt(row.day - 1).toFixed(2);
            return `
                <g class="day-tick">
                    <line x1="${x}" y1="${height - paddingBottom + 4}" x2="${x}" y2="${height - paddingBottom + 10}"></line>
                    <text x="${x}" y="${height - 10}">${row.day}</text>
                </g>
            `;
        })
        .join("");

    const markers = activeRows
        .filter((row) => row.is_income_day || row.is_shock_day || row.is_waterline_day || row.is_negative_day || row.is_reserve_draw_day || row.event_total > 0)
        .map((row) => {
            const x = xAt(row.day - 1).toFixed(2);
            const y = yAt(row.end_total_assets).toFixed(2);
            const details = [
                `День ${row.day}`,
                `Ресурс ${asCurrency(row.end_total_assets)}`,
                row.is_income_day ? `Дохід ${asCurrency(row.income_received)}` : "",
                row.event_total > 0 ? `Івенти ${asCurrency(row.event_total)} ${row.event_labels}` : "",
                row.is_shock_day ? `Форс-мажор ${asCurrency(row.shock_loss)}` : "",
                row.is_reserve_draw_day ? `З резерву ${asCurrency(row.reserve_draw)}` : "",
            ]
                .filter(Boolean)
                .join(" • ");

            return `
                <circle class="${markerClass(row)}" cx="${x}" cy="${y}" r="5">
                    <title>${escapeHtml(details)}</title>
                </circle>
            `;
        })
        .join("");

    chartNode.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Коридор ресурсу та динаміка бюджету">
            ${axisLines}
            <polygon class="corridor-shape" points="${corridorShape}"></polygon>
            <line class="waterline-line" x1="${paddingX}" y1="${waterlineY}" x2="${width - paddingX}" y2="${waterlineY}"></line>
            <polyline class="balance-line" points="${activePoints}"></polyline>
            ${markers}
            ${dayTicks}
        </svg>
    `;

    const lastLower = lowerBand[lowerBand.length - 1];
    const lastUpper = upperBand[upperBand.length - 1];
    chartCaptionNode.textContent =
        `${scenario.label} режим. Коридор фінішує між ${asCurrency(lastLower)} і ${asCurrency(lastUpper)}. ` +
        `Ватерлінія тримається на ${asCurrency(scenario.summary.target_reserve)}.`;
}

function tableEventCell(row) {
    if (row.event_total <= 0) {
        return `<span class="muted-cell">-</span>`;
    }

    const label = row.event_labels ? `<span class="event-cell-label">${escapeHtml(row.event_labels)}</span>` : "";
    return `${asCurrency(row.event_total)}${label}`;
}

function renderTable() {
    const scenario = scenarioState();
    if (!scenario) {
        bodyNode.innerHTML = "";
        return;
    }

    bodyNode.innerHTML = scenario.projection
        .map((row) => {
            const classes = [
                row.is_income_day ? "is-income" : "",
                row.is_shock_day ? "is-shock" : "",
                row.is_waterline_day ? "is-waterline" : "",
                row.is_negative_day ? "is-negative" : "",
                row.is_reserve_draw_day ? "is-reserve" : "",
                row.event_total > 0 ? "has-event" : "",
            ]
                .filter(Boolean)
                .join(" ");

            return `
                <tr class="${classes}">
                    <td>${row.day}</td>
                    <td>${escapeHtml(asDateLabel(row.date))}</td>
                    <td>${asCurrency(row.start_total_assets)}</td>
                    <td>${asCurrency(row.adaptive_limit)}</td>
                    <td>${asCurrency(row.planned_daily_spend)}</td>
                    <td>${tableEventCell(row)}</td>
                    <td>${row.income_received > 0 ? asCurrency(row.income_received) : `<span class="muted-cell">-</span>`}</td>
                    <td>${row.shock_loss > 0 ? asCurrency(row.shock_loss) : `<span class="muted-cell">-</span>`}</td>
                    <td>${row.reserve_draw > 0 ? asCurrency(row.reserve_draw) : `<span class="muted-cell">-</span>`}</td>
                    <td>${row.free_transfer > 0 ? asCurrency(row.free_transfer) : `<span class="muted-cell">-</span>`}</td>
                    <td>${asCurrency(row.end_total_assets)}</td>
                </tr>
            `;
        })
        .join("");
}

function renderHistory(history) {
    if (!history || history.length === 0) {
        historyNode.innerHTML = `<p class="placeholder compact">Історія поки порожня.</p>`;
        return;
    }

    historyNode.innerHTML = "";

    history.forEach((entry) => {
        const article = document.createElement("article");
        article.className = "history-card";
        article.innerHTML = `
            <div class="history-meta">
                <strong>${escapeHtml(asDateTimeLabel(entry.created_at))}</strong>
                <span>${asCurrency(entry.inputs.available_budget)} бюджету · ${asCurrency(entry.inputs.free_money)} вільних грошей</span>
            </div>
            <dl class="history-stats">
                <div>
                    <dt>Дохід</dt>
                    <dd>${asCurrency(entry.inputs.next_income_amount)}</dd>
                </div>
                <div>
                    <dt>Дата</dt>
                    <dd>${escapeHtml(asDateLabel(entry.inputs.next_income_date))}</dd>
                </div>
                <div>
                    <dt>Резерв</dt>
                    <dd>${asPercent(entry.inputs.monthly_savings_percent)}</dd>
                </div>
                <div>
                    <dt>Фініш</dt>
                    <dd>${asCurrency(entry.summary.final_total_assets)}</dd>
                </div>
            </dl>
            <button type="button" class="history-load">Відкрити</button>
        `;

        article.querySelector(".history-load").addEventListener("click", async () => {
            errorNode.textContent = "";
            applyInputs(entry.inputs);

            try {
                const data = await requestForecast(entry.inputs, false);
                forecastData = data;
                activeScenario = data.default_scenario || "base";
                renderActiveScenario();
                renderHistory(data.history || []);
            } catch (error) {
                errorNode.textContent = error.message;
            }
        });

        historyNode.appendChild(article);
    });
}

function renderActiveScenario() {
    renderSummary();
    renderEventPreview();
    renderScenarioCards();
    renderCriticalPoints();
    renderChart();
    renderTable();
}

async function loadState() {
    errorNode.textContent = "";

    try {
        const state = await fetchJson("/state");
        applyInputs(state.budget || {});
        renderHistory(state.history || []);

        if (state.forecast) {
            forecastData = state.forecast;
            activeScenario = state.forecast.default_scenario || "base";
            renderActiveScenario();
        }
    } catch (error) {
        errorNode.textContent = error.message;
    }
}

async function submitForm(event) {
    event.preventDefault();
    errorNode.textContent = "";

    try {
        const data = await requestForecast(formPayload(), true);
        forecastData = data;
        activeScenario = data.default_scenario || "base";
        renderActiveScenario();
        renderHistory(data.history || []);
    } catch (error) {
        errorNode.textContent = error.message;
    }
}

async function clearHistory() {
    errorNode.textContent = "";

    try {
        const data = await fetchJson("/history", { method: "DELETE" });
        renderHistory(data.history || []);
    } catch (error) {
        errorNode.textContent = error.message;
    }
}

form.addEventListener("submit", submitForm);
clearHistoryButton.addEventListener("click", clearHistory);
window.addEventListener("load", loadState);
