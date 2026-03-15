const form = document.getElementById("calc-form");
const errorNode = document.getElementById("form-error");
const historyNode = document.getElementById("history-list");
const scenarioStrip = document.getElementById("scenario-strip");
const chartCanvas = document.getElementById("forecast-chart");
const projectionHead = document.getElementById("projection-head");
const projectionBody = document.getElementById("projection-body");
const resetButton = document.getElementById("reset-button");

const summaryNodes = {
    caption: document.getElementById("summary-caption"),
    modePill: document.getElementById("mode-pill"),
    balanceDate: document.getElementById("balance-date-display"),
    endDate: document.getElementById("end-date-display"),
    baseSafeLimit: document.getElementById("base-safe-limit"),
    savingsTarget: document.getElementById("savings-target-amount"),
    waterlineAmount: document.getElementById("waterline-amount"),
    resourceAmount: document.getElementById("resource-amount"),
};

const numericFields = [
    "current_balance",
    "forecast_days",
    "next_income_amount",
    "savings_goal_percent",
    "required_expense_percent",
    "free_money_percent",
    "waterline_percent",
];

let forecastChart = null;
let latestResponse = null;

function asCurrency(value) {
    return new Intl.NumberFormat("uk-UA", {
        style: "currency",
        currency: "UAH",
        maximumFractionDigits: 2,
    }).format(Number(value) || 0);
}

function asDate(value) {
    return new Intl.DateTimeFormat("uk-UA", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(new Date(value));
}

function asDateTime(value) {
    return new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
        timeStyle: "short",
    }).format(new Date(value));
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || "Не вдалося виконати запит.");
    }
    return data;
}

function applySettings(settings) {
    const simpleFields = [
        "current_balance",
        "forecast_days",
        "next_income_date",
        "next_income_amount",
        "savings_goal_percent",
        "required_expense_percent",
        "free_money_percent",
        "waterline_percent",
        "events_text",
    ];

    simpleFields.forEach((key) => {
        const field = form.elements.namedItem(key);
        if (field) {
            field.value = settings[key] ?? "";
        }
    });

    summaryNodes.balanceDate.value = asDate(settings.balance_date);
    summaryNodes.endDate.value = asDate(settings.end_date);

    Object.entries(settings.visible_modes || {}).forEach(([mode, isVisible]) => {
        const checkbox = form.elements.namedItem(`visible_${mode}`);
        if (checkbox) {
            checkbox.checked = Boolean(isVisible);
        }
    });

    const activeRadio = form.querySelector(`input[name="active_mode"][value="${settings.active_mode}"]`);
    if (activeRadio) {
        activeRadio.checked = true;
    }
}

function collectVisibleModes() {
    return {
        base: form.elements.namedItem("visible_base").checked,
        economy: form.elements.namedItem("visible_economy").checked,
        aggressive: form.elements.namedItem("visible_aggressive").checked,
        force_majeure: form.elements.namedItem("visible_force_majeure").checked,
    };
}

function buildPayload(settingsOverride = null) {
    const payload = settingsOverride ? { ...settingsOverride } : Object.fromEntries(new FormData(form).entries());

    numericFields.forEach((key) => {
        payload[key] = key === "forecast_days"
            ? Number.parseInt(payload[key] || 0, 10)
            : Number.parseFloat(payload[key] || 0);
    });

    payload.visible_modes = settingsOverride?.visible_modes || collectVisibleModes();
    payload.active_mode = settingsOverride?.active_mode || form.querySelector('input[name="active_mode"]:checked')?.value || "base";
    payload.events_text = String(payload.events_text || "").trim();
    return payload;
}

function activeScenario(response) {
    return response.scenarios[response.meta.active_mode];
}

function visibleKeys(response) {
    return response.meta.visible_keys || response.meta.mode_order;
}

function scenarioFoot(summary) {
    if (summary.negative_day) {
        return `Ламається на ${summary.negative_day}-й день.`;
    }
    if (summary.waterline_day) {
        return `Торкається ватерлінії на ${summary.waterline_day}-й день.`;
    }
    if (summary.shock_day) {
        return `Шок на ${summary.shock_day}-й день.`;
    }
    return "Тримає період без критичного провалу.";
}

function renderSummary(response) {
    const settings = response.settings;
    const currentScenario = activeScenario(response);
    summaryNodes.modePill.textContent = `Current = ${response.meta.mode_labels[response.meta.active_mode]}`;
    summaryNodes.modePill.className = `pill ${response.meta.active_mode === "force_majeure" ? "is-stress" : ""}`;
    summaryNodes.baseSafeLimit.textContent = asCurrency(settings.base_safe_limit);
    summaryNodes.savingsTarget.textContent = asCurrency(settings.savings_target_amount);
    summaryNodes.waterlineAmount.textContent = asCurrency(settings.waterline_amount);
    summaryNodes.resourceAmount.textContent = asCurrency(settings.resource_within_horizon);
    summaryNodes.caption.textContent =
        `${currentScenario.label}: фініш ${asCurrency(currentScenario.summary.final_total_assets)}, ` +
        `вільні гроші ${asCurrency(currentScenario.summary.final_free_money_bucket)}. ${scenarioFoot(currentScenario.summary)}`;
}

function renderScenarioStrip(response) {
    const activeMode = response.meta.active_mode;
    scenarioStrip.innerHTML = visibleKeys(response)
        .map((mode) => {
            const scenario = response.scenarios[mode];
            const isActive = mode === activeMode;
            return `
                <article class="scenario-card${isActive ? " active-card" : ""}">
                    <span class="scenario-name">${escapeHtml(scenario.label)}</span>
                    <strong>${asCurrency(scenario.summary.final_total_assets)}</strong>
                    <p>Safe limit: ${asCurrency(scenario.summary.tightest_safe_limit)}</p>
                    <p>Необхідні: ${scenario.summary.required_expense_percent.toFixed(2)}%</p>
                    <p>${escapeHtml(scenarioFoot(scenario.summary))}</p>
                </article>
            `;
        })
        .join("");
}

function renderTable(response) {
    const keys = visibleKeys(response);
    const headCells = [
        "<th>Day</th>",
        "<th>Date</th>",
        ...keys.map((mode) => `<th>${escapeHtml(response.meta.mode_labels[mode])}</th>`),
        "<th>Current</th>",
    ];
    projectionHead.innerHTML = `<tr>${headCells.join("")}</tr>`;

    projectionBody.innerHTML = response.table
        .map((row) => {
            const notes = [];
            if (row.income > 0) {
                notes.push(`<span class="table-note note-income">+ ${asCurrency(row.income)}</span>`);
            }
            if (row.events > 0) {
                const names = row.event_names.length ? ` · ${escapeHtml(row.event_names.join(", "))}` : "";
                notes.push(`<span class="table-note note-event">- ${asCurrency(row.events)}${names}</span>`);
            }
            if (row.stress_triggered) {
                notes.push('<span class="table-note note-stress">форс-мажор</span>');
            }

            const modeCells = keys.map((mode) => {
                const dangerClass = row.below_waterline[mode] ? "is-danger" : "";
                return `<td class="${dangerClass}">${asCurrency(row.modes[mode])}</td>`;
            });

            return `
                <tr>
                    <td>${row.day}</td>
                    <td>
                        <div class="date-cell">
                            <strong>${escapeHtml(asDate(row.date))}</strong>
                            <div class="table-notes">${notes.join("") || '<span class="table-note note-soft">без подій</span>'}</div>
                        </div>
                    </td>
                    ${modeCells.join("")}
                    <td class="${row.current_below_waterline ? "is-danger" : ""} current-cell">${asCurrency(row.current)}</td>
                </tr>
            `;
        })
        .join("");
}

function buildDatasets(response) {
    const visible = visibleKeys(response);
    const datasets = [];
    const colors = {
        base: "#4b6f84",
        economy: "#2f8a60",
        aggressive: "#d68039",
        force_majeure: "#b34736",
    };

    if (visible.includes("aggressive")) {
        datasets.push({
            label: response.meta.mode_labels.aggressive,
            data: response.chart_data.modes.aggressive,
            borderColor: colors.aggressive,
            backgroundColor: "rgba(214, 128, 57, 0.06)",
            borderWidth: 2,
            tension: 0.26,
            pointRadius: 0,
        });
    }

    if (visible.includes("economy")) {
        datasets.push({
            label: response.meta.mode_labels.economy,
            data: response.chart_data.modes.economy,
            borderColor: colors.economy,
            backgroundColor: visible.includes("aggressive") ? "rgba(47, 138, 96, 0.14)" : "rgba(47, 138, 96, 0.06)",
            fill: visible.includes("aggressive") ? "-1" : false,
            borderWidth: 2,
            tension: 0.26,
            pointRadius: 0,
        });
    }

    visible.forEach((mode) => {
        if (mode === "aggressive" || mode === "economy") {
            return;
        }
        datasets.push({
            label: response.meta.mode_labels[mode],
            data: response.chart_data.modes[mode],
            borderColor: colors[mode],
            borderWidth: 2,
            tension: 0.26,
            pointRadius: 0,
        });
    });

    datasets.push({
        label: "Current",
        data: response.chart_data.current,
        borderColor: response.meta.active_mode === "force_majeure" ? "#d04d35" : "#173d59",
        borderWidth: 3,
        tension: 0.26,
        pointRadius: 0,
    });
    datasets.push({
        label: "Waterline",
        data: response.chart_data.waterline,
        borderColor: "#8a2e1d",
        borderDash: [6, 6],
        borderWidth: 2,
        tension: 0,
        pointRadius: 0,
    });
    return datasets;
}

function renderChart(response) {
    if (forecastChart) {
        forecastChart.destroy();
    }

    forecastChart = new Chart(chartCanvas, {
        type: "line",
        data: {
            labels: response.chart_data.labels.map((item) => asDate(item)),
            datasets: buildDatasets(response),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    position: "bottom",
                },
                tooltip: {
                    callbacks: {
                        label(context) {
                            return `${context.dataset.label}: ${asCurrency(context.parsed.y)}`;
                        },
                    },
                },
            },
            scales: {
                y: {
                    ticks: {
                        callback(value) {
                            return asCurrency(value);
                        },
                    },
                },
            },
        },
    });
}

function renderHistory(response) {
    if (!response.history || response.history.length === 0) {
        historyNode.innerHTML = '<p class="placeholder">Історія ще порожня.</p>';
        return;
    }

    historyNode.innerHTML = "";
    response.history.forEach((entry) => {
        const node = document.createElement("article");
        node.className = "history-card";
        node.innerHTML = `
            <div class="history-meta">
                <strong>${escapeHtml(asDateTime(entry.created_at))}</strong>
                <span>${escapeHtml(response.meta.mode_labels[entry.summary.active_mode] || entry.summary.active_mode)}</span>
            </div>
            <p>Current: ${asCurrency(entry.summary.current_final_balance)}</p>
            <p>Base: ${asCurrency(entry.summary.base_final_balance)}</p>
            <button type="button" class="ghost-button history-button">Відкрити</button>
        `;

        node.querySelector(".history-button").addEventListener("click", async () => {
            errorNode.textContent = "";
            try {
                const data = await fetchJson("/calculate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ ...entry.settings, save_history: false }),
                });
                renderDashboard(data);
            } catch (error) {
                errorNode.textContent = error.message;
            }
        });

        historyNode.appendChild(node);
    });
}

function renderDashboard(response) {
    latestResponse = response;
    applySettings(response.settings);
    renderSummary(response);
    renderScenarioStrip(response);
    renderChart(response);
    renderTable(response);
    renderHistory(response);
}

async function runCalculation(settingsOverride = null) {
    errorNode.textContent = "";
    const payload = buildPayload(settingsOverride);
    const response = await fetchJson("/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    renderDashboard(response);
}

async function loadDashboard() {
    errorNode.textContent = "";
    const response = await fetchJson("/load");
    renderDashboard(response);
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        await runCalculation();
    } catch (error) {
        errorNode.textContent = error.message;
    }
});

resetButton.addEventListener("click", async () => {
    errorNode.textContent = "";
    try {
        const response = await fetchJson("/reset", { method: "POST" });
        renderDashboard(response);
    } catch (error) {
        errorNode.textContent = error.message;
    }
});

window.addEventListener("load", async () => {
    try {
        await loadDashboard();
    } catch (error) {
        errorNode.textContent = error.message;
    }
});
