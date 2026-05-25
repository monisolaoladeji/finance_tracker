function money(cents) {
    const value = Number(cents || 0) / 100;
    return `$${value.toFixed(2)}`;
}

function pickColors(count) {
    const base = [
        "#2563eb",
        "#7c3aed",
        "#0ea5e9",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#64748b",
        "#14b8a6",
        "#a855f7",
        "#22c55e",
    ];
    return Array.from({ length: count }, (_, i) => base[i % base.length]);
}

let cashflowChart = null;
let categoriesChart = null;

const API_URL = window.API_URL || 'https://finance-tracker-1-vz18.onrender.com';

async function loadStats() {
    const res = await fetch(API_URL + "/api/stats?days=30");
    if (!res.ok) throw new Error("stats failed");
    return res.json();
}

async function loadInsights() {
    const res = await fetch(API_URL + "/api/insights");
    if (!res.ok) throw new Error("insights failed");
    return res.json();
}

function renderMetrics(stats) {
    const income = stats.totals.income_cents;
    const expense = stats.totals.expense_cents;
    const net = income - expense;

    document.querySelector("#metric-income").textContent = money(income);
    document.querySelector("#metric-expense").textContent = money(expense);
    const netNode = document.querySelector("#metric-net");
    netNode.textContent = money(net);
    netNode.classList.toggle("negative", net < 0);
}

function renderCharts(stats) {
    const labels = stats.timeseries.labels;
    const income = stats.timeseries.income_cents.map((c) => c / 100);
    const expense = stats.timeseries.expense_cents.map((c) => c / 100);

    const cashCtx = document.getElementById("chart-cashflow");
    if (cashflowChart) cashflowChart.destroy();
    cashflowChart = new Chart(cashCtx, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "Income",
                    data: income,
                    borderColor: "#22c55e",
                    backgroundColor: "rgba(34, 197, 94, 0.15)",
                    tension: 0.35,
                    fill: true,
                },
                {
                    label: "Expense",
                    data: expense,
                    borderColor: "#ef4444",
                    backgroundColor: "rgba(239, 68, 68, 0.12)",
                    tension: 0.35,
                    fill: true,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: "top" },
                tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}` } },
            },
            scales: {
                y: { ticks: { callback: (v) => `$${v}` } },
            },
        },
    });

    const catLabels = stats.categories.labels;
    const catValues = stats.categories.expense_cents.map((c) => c / 100);
    const catCtx = document.getElementById("chart-categories");
    if (categoriesChart) categoriesChart.destroy();
    categoriesChart = new Chart(catCtx, {
        type: "bar",
        data: {
            labels: catLabels.length ? catLabels : ["No expenses yet"],
            datasets: [
                {
                    label: "Expenses",
                    data: catLabels.length ? catValues : [0],
                    backgroundColor: pickColors(Math.max(1, catLabels.length)),
                    borderRadius: 10,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => `$${ctx.parsed.y.toFixed(2)}` } },
            },
            scales: {
                y: { ticks: { callback: (v) => `$${v}` } },
            },
        },
    });
}

function renderInsights(data) {
    const box = document.querySelector("#insights");
    const lines = data.insights || [];

    if (!lines.length) {
        box.innerHTML = `<div class="muted">No suggestions yet.</div>`;
        return;
    }

    box.innerHTML = `
        <ul class="insight-list">
            ${lines.map((t) => `<li>${t}</li>`).join("")}
        </ul>
        <div class="muted fineprint">Week: ${data.period.week_start} → ${data.period.week_end}</div>
    `;
}

async function refreshAll() {
    const [stats, insights] = await Promise.all([loadStats(), loadInsights()]);
    renderMetrics(stats);
    renderCharts(stats);
    renderInsights(insights);
}

document.querySelector("#refresh-insights")?.addEventListener("click", async () => {
    try {
        const insights = await loadInsights();
        renderInsights(insights);
    } catch {
        document.querySelector("#insights").innerHTML = `<div class="muted">Could not load insights.</div>`;
    }
});

refreshAll().catch(() => {
    document.querySelector("#insights").innerHTML = `<div class="muted">Could not load dashboard.</div>`;
});

