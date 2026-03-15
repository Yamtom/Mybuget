const form = document.getElementById("calc-form");
const errorNode = document.getElementById("form-error");
const bodyNode = document.getElementById("projection-body");
const barsNode = document.getElementById("progress-bars");

const metricNodes = {
    finalBalance: document.getElementById("final-balance"),
    totalSavings: document.getElementById("total-savings"),
    totalOperational: document.getElementById("total-operational"),
    stabilityIndex: document.getElementById("stability-index"),
};

function asCurrency(value) {
    return new Intl.NumberFormat("uk-UA", {
        style: "currency",
        currency: "UAH",
        maximumFractionDigits: 2,
    }).format(value);
}

function asNumber(value) {
    return Number.parseFloat(value);
}

function renderSummary(summary) {
    metricNodes.finalBalance.textContent = asCurrency(summary.final_balance);
    metricNodes.totalSavings.textContent = asCurrency(summary.total_savings);
    metricNodes.totalOperational.textContent = asCurrency(summary.total_expenses);
    metricNodes.stabilityIndex.textContent = `${summary.stability_index.toFixed(2)}%`;
}

function renderTable(rows) {
    bodyNode.innerHTML = "";

    rows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.day}</td>
            <td>${asCurrency(row.start_balance)}</td>
            <td>${asCurrency(row.expense)}</td>
            <td>${asCurrency(row.remaining)}</td>
            <td>${asCurrency(row.extra_funds)}</td>
            <td>${asCurrency(row.savings)}</td>
            <td>${asCurrency(row.free_part)}</td>
            <td>${asCurrency(row.savings_progress)}</td>
        `;
        bodyNode.appendChild(tr);
    });
}

function renderBars(rows) {
    barsNode.innerHTML = "";

    const maxValue = Math.max(...rows.map((x) => x.savings_progress), 1);

    rows.forEach((row, index) => {
        const bar = document.createElement("div");
        const pct = Math.max((row.savings_progress / maxValue) * 100, 5);

        bar.className = "bar";
        bar.style.height = `${pct}%`;
        bar.style.animationDelay = `${index * 0.03}s`;
        bar.title = `День ${row.day}: ${asCurrency(row.savings_progress)}`;

        barsNode.appendChild(bar);
    });
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

        renderSummary(data.summary);
        renderTable(data.projection);
        renderBars(data.projection);
    } catch (error) {
        errorNode.textContent = error.message;
    }
}

form.addEventListener("submit", submitForm);
