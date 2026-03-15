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

const metricNodes = {
    finalLiquid: document.getElementById("final-liquid"),
    extraPool: document.getElementById("extra-pool"),
    totalAssets: document.getElementById("total-assets"),
    safeLimit: document.getElementById("safe-limit"),
};

let forecastData = null;
let activeScenario = "base";

function asCurrency(value) {
    return new Intl.NumberFormat("uk-UA", {
        style: "currency",
        currency: "UAH",
        maximumFractionDigits: 2,
    }).format(value);
}

function asPercent(value) {
    return `${Number(value).toFixed(2)}%`;
}

function asDateLabel(value) {
    return new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
        timeStyle: "short",
    }).format(new Date(value));
}

function asNumber(value) {
    return Number.parseFloat(value);
}

function scenarioState() {
    if (!forecastData) {
        return null;
    }
    return forecastData.scenarios[activeScenario];
}

function applyInputs(inputs) {
    Object.entries(inputs).forEach(([key, value]) => {
        const field = form.elements.namedItem(key);
        if (field) {
            field.value = value;
        }
    });
}

function renderSummary() {
    const scenario = scenarioState();
    if (!scenario) {
        return;
    }

    const { summary, label } = scenario;
    scenarioNameNode.textContent = `${label} режим`;
    scenarioNoteNode.textContent = summary.narrative;
    scenarioNoteNode.dataset.level = summary.risk_level;

    metricNodes.finalLiquid.textContent = asCurrency(summary.final_liquid_balance);
    metricNodes.extraPool.textContent = asCurrency(summary.accumulated_extra_funds);
    metricNodes.totalAssets.textContent = asCurrency(summary.final_total_assets);
    metricNodes.safeLimit.textContent = `${asCurrency(summary.tightest_safe_daily_spend)} · ${asPercent(summary.tightest_safe_percent)}`;
}

function buildScenarioCaption(item) {
    if (item.first_depletion_day) {
        return `Ліквідність вичерпується на ${item.first_depletion_day}-й день`;
    }
    if (item.first_stress_day) {
        return `Стрес починається з ${item.first_stress_day}-го дня`;
    }
    return "Запас тримається до фіналу";
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
            <span class="scenario-chip">${item.label}</span>
            <h3>${item.risk_label}</h3>
            <p class="scenario-copy">${item.description}</p>
            <dl class="scenario-stats">
                <div>
                    <dt>Ліквідність</dt>
                    <dd>${asCurrency(item.final_liquid_balance)}</dd>
                </div>
                <div>
                    <dt>Накопичено</dt>
                    <dd>${asCurrency(item.accumulated_extra_funds)}</dd>
                </div>
                <div>
                    <dt>Капітал</dt>
                    <dd>${asCurrency(item.final_total_assets)}</dd>
                </div>
            </dl>
            <p class="scenario-foot">${buildScenarioCaption(item)}</p>
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

    pointsNode.innerHTML = "";
    scenario.critical_points.forEach((point) => {
        const article = document.createElement("article");
        article.className = `point-card point-${point.level}`;
        article.innerHTML = `
            <div class="point-head">
                <span class="point-badge">${point.day}-й день</span>
                <h3>${point.title}</h3>
            </div>
            <p>${point.message}</p>
        `;
        pointsNode.appendChild(article);
    });
}

function renderChart() {
    const scenario = scenarioState();
    if (!scenario) {
        return;
    }

    const rows = scenario.projection;
    const width = 920;
    const height = 300;
    const padding = 24;
    const values = rows.map((row) => row.end_liquid);
    const minValue = Math.min(...values, 0);
    const maxValue = Math.max(...values, 0);
    const range = maxValue - minValue || 1;
    const innerWidth = width - padding * 2;
    const innerHeight = height - padding * 2;
    const xStep = rows.length > 1 ? innerWidth / (rows.length - 1) : 0;
    const xAt = (index) => padding + index * xStep;
    const yAt = (value) => padding + ((maxValue - value) / range) * innerHeight;
    const zeroY = yAt(0);

    const linePoints = rows
        .map((row, index) => `${xAt(index).toFixed(2)},${yAt(row.end_liquid).toFixed(2)}`)
        .join(" ");

    const areaPoints = [
        `${padding},${zeroY.toFixed(2)}`,
        linePoints,
        `${padding + innerWidth},${zeroY.toFixed(2)}`,
    ].join(" ");

    const markers = rows
        .filter((row) => row.is_shock_day || row.is_depletion_day || row.is_stress_day)
        .map((row) => {
            const index = row.day - 1;
            const className = row.is_depletion_day
                ? "marker marker-negative"
                : row.is_shock_day
                    ? "marker marker-shock"
                    : "marker marker-stress";
            return `
                <circle class="${className}" cx="${xAt(index).toFixed(2)}" cy="${yAt(row.end_liquid).toFixed(2)}" r="5">
                    <title>День ${row.day}: ${asCurrency(row.end_liquid)}</title>
                </circle>
            `;
        })
        .join("");

    const yLabels = [maxValue, 0, minValue]
        .filter((value, index, list) => list.indexOf(value) === index)
        .map((value) => `
            <g class="axis-label">
                <line x1="${padding}" y1="${yAt(value).toFixed(2)}" x2="${padding + innerWidth}" y2="${yAt(value).toFixed(2)}" />
                <text x="${padding + 8}" y="${(yAt(value) - 8).toFixed(2)}">${asCurrency(value)}</text>
            </g>
        `)
        .join("");

    chartNode.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Графік ліквідності по днях">
            ${yLabels}
            <polygon class="area-shape" points="${areaPoints}" />
            <line class="zero-line" x1="${padding}" y1="${zeroY.toFixed(2)}" x2="${padding + innerWidth}" y2="${zeroY.toFixed(2)}"></line>
            <polyline class="balance-line" points="${linePoints}"></polyline>
            ${markers}
        </svg>
    `;

    chartCaptionNode.textContent = `${scenario.label}: витрати ${asPercent(scenario.summary.operating_percent)} на день, у накопичення ${asPercent(scenario.summary.extra_percent)} після кожної витрати.`;
}

function renderTable() {
    const scenario = scenarioState();
    if (!scenario) {
        return;
    }

    bodyNode.innerHTML = scenario.projection
        .map((row) => {
            const classes = [
                row.is_stress_day ? "is-stress" : "",
                row.is_shock_day ? "is-shock" : "",
                row.is_depletion_day ? "is-negative" : "",
            ]
                .filter(Boolean)
                .join(" ");

            return `
                <tr class="${classes}">
                    <td>${row.day}</td>
                    <td>${asCurrency(row.start_liquid)}</td>
                    <td>${asPercent(row.operating_percent)}</td>
                    <td>${asCurrency(row.operating_expense)}</td>
                    <td>${asCurrency(row.shock_expense)}</td>
                    <td>${asCurrency(row.extra_transfer)}</td>
                    <td>${asCurrency(row.end_liquid)}</td>
                    <td>${asCurrency(row.extra_pool)}</td>
                    <td>${asCurrency(row.safe_daily_spend)}</td>
                </tr>
            `;
        })
        .join("");
}

function renderHistory(history) {
    if (!history || history.length === 0) {
        historyNode.innerHTML = `<p class="placeholder">Історія поки порожня.</p>`;
        return;
    }

    historyNode.innerHTML = "";

    history.forEach((entry) => {
        const article = document.createElement("article");
        article.className = "history-card";
        article.innerHTML = `
            <div class="history-meta">
                <strong>${asDateLabel(entry.created_at)}</strong>
                <span>${asCurrency(entry.inputs.available_funds)} · ${asPercent(entry.inputs.operating_percent)} витрат</span>
            </div>
            <dl class="history-stats">
                <div>
                    <dt>Накопичено</dt>
                    <dd>${asCurrency(entry.summary.accumulated_extra_funds)}</dd>
                </div>
                <div>
                    <dt>Капітал</dt>
                    <dd>${asCurrency(entry.summary.final_total_assets)}</dd>
                </div>
            </dl>
            <button type="button" class="history-load">Підставити</button>
        `;

        article.querySelector(".history-load").addEventListener("click", () => {
            applyInputs(entry.inputs);
            form.requestSubmit();
        });

        historyNode.appendChild(article);
    });
}

function renderActiveScenario() {
    renderScenarioCards();
    renderSummary();
    renderCriticalPoints();
    renderChart();
    renderTable();
}

async function loadHistory() {
    const response = await fetch("/history");
    const data = await response.json();
    renderHistory(data.history || []);

    if (data.history && data.history[0]) {
        applyInputs(data.history[0].inputs);
    }
}

async function submitForm(event) {
    event.preventDefault();
    errorNode.textContent = "";

    const payload = Object.fromEntries(new FormData(form).entries());
    Object.keys(payload).forEach((key) => {
        payload[key] = asNumber(payload[key]);
    });

    try {
        const response = await fetch("/calculate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Помилка при розрахунку");
        }

        forecastData = data;
        activeScenario = data.default_scenario || "base";
        renderActiveScenario();
        renderHistory(data.history || []);
    } catch (error) {
        errorNode.textContent = error.message;
    }
}

async function clearHistory() {
    const response = await fetch("/history", { method: "DELETE" });
    const data = await response.json();
    renderHistory(data.history || []);
}

form.addEventListener("submit", submitForm);
clearHistoryButton.addEventListener("click", clearHistory);
window.addEventListener("load", loadHistory);
