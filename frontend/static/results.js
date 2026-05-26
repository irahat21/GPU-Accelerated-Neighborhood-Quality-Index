const resultsData = window.RESULTS_DATA || {};
const districts = resultsData.districts || [];
const metricConfigs = [
    { label: "Air Quality", key: "air", color: "#00c896" },
    { label: "Drinking Water", key: "water", color: "#3b9eff" },
    { label: "Education", key: "education", color: "#f5a623" },
    { label: "Public Safety", key: "safety", color: "#ff5e7a" },
];

const chartDefaults = {
    color: "#e8eaf0",
    borderColor: "rgba(255, 255, 255, 0.08)",
    gridColor: "rgba(255, 255, 255, 0.08)",
    muted: "#7a8190",
    overall: "#9b64ff",
};

Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;
Chart.defaults.font.family = "'DM Sans', sans-serif";

function wrapLabel(label, maxLineLength = 24) {
    const words = String(label).split(" ");
    const lines = [];
    let current = "";
    words.forEach((word) => {
        const next = current ? `${current} ${word}` : word;
        if (next.length <= maxLineLength) {
            current = next;
        } else {
            if (current) lines.push(current);
            current = word;
        }
    });
    if (current) lines.push(current);
    return lines.length ? lines : [label];
}

function buildHistogram(values, binSize = 10) {
    const bins = [];
    for (let start = 0; start < 100; start += binSize) {
        bins.push({ label: `${start}-${start + binSize}`, count: 0 });
    }
    values.forEach((value) => {
        const index = Math.min(Math.floor(value / binSize), bins.length - 1);
        bins[index].count += 1;
    });
    return bins;
}

function getDistrictById(id) {
    return districts.find((district) => district.id === id) || districts[0];
}

function chartTitleWithFullName(items, fullLabels) {
    const index = items?.[0]?.dataIndex ?? items?.[0]?.index ?? 0;
    return fullLabels?.[index] || "";
}

function createBarChart(canvasId, rows, color, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const fullLabels = rows.map((row) => row.name);
    const labels = fullLabels.map((label) => wrapLabel(label, options.labelWrapLength || 24));
    const data = rows.map((row) => row.score);

    return new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: color,
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: options.indexAxis || "y",
            layout: {
                padding: options.padding || { left: 0, right: 8, top: 4, bottom: 0 },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => chartTitleWithFullName(items, fullLabels),
                        label: (context) => `Score: ${(context.parsed.x ?? context.parsed.y).toFixed(2)}`,
                    },
                },
            },
            scales: {
                x: {
                    min: options.min ?? 0,
                    max: options.max ?? 100,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
                y: {
                    grid: { display: false },
                    ticks: {
                        color: chartDefaults.color,
                        autoSkip: false,
                        font: { size: options.tickFontSize || 11 },
                    },
                },
            },
        },
    });
}

function initializeOverallCharts() {
    const top10 = resultsData.top10 || [];
    const bottom10 = resultsData.bottom10 || [];

    createBarChart("topOverallChart", top10, "rgba(0, 200, 150, 0.75)", {
        labelWrapLength: 26,
        tickFontSize: 10,
    });

    createBarChart("bottomOverallChart", bottom10, "rgba(255, 94, 122, 0.75)", {
        labelWrapLength: 26,
        tickFontSize: 10,
    });

    const histogram = buildHistogram(districts.map((district) => district.overall));
    new Chart(document.getElementById("overallDistributionChart"), {
        type: "bar",
        data: {
            labels: histogram.map((bin) => bin.label),
            datasets: [{
                label: "Districts",
                data: histogram.map((bin) => bin.count),
                backgroundColor: "rgba(155, 100, 255, 0.72)",
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: chartDefaults.muted } },
                y: {
                    beginAtZero: true,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted, precision: 0 },
                },
            },
        },
    });

    createBarChart(
        "boroughAverageChart",
        (resultsData.boroughs || []).map((row) => ({ name: row.name, score: row.score })),
        "rgba(59, 158, 255, 0.72)",
        { labelWrapLength: 18 }
    );

    const rankCurve = resultsData.rankCurve || [];
    new Chart(document.getElementById("rankCurveChart"), {
        type: "line",
        data: {
            labels: rankCurve.map((row) => row.rank),
            datasets: [{
                label: "Overall Score",
                data: rankCurve.map((row) => row.score),
                borderColor: "#9b64ff",
                backgroundColor: "rgba(155, 100, 255, 0.16)",
                pointBackgroundColor: "#9b64ff",
                pointRadius: 2,
                pointHoverRadius: 4,
                fill: true,
                tension: 0.28,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            const idx = items?.[0]?.dataIndex ?? 0;
                            return rankCurve[idx]?.name || "";
                        },
                        label: (context) => `Overall score: ${context.parsed.y.toFixed(2)}`,
                    },
                },
            },
            scales: {
                x: {
                    title: { display: true, text: "Overall Rank", color: chartDefaults.muted },
                    grid: { display: false },
                    ticks: { color: chartDefaults.muted, maxTicksLimit: 10 },
                },
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
            },
        },
    });

    const scatterRows = resultsData.overallVsBalance || [];
    new Chart(document.getElementById("overallBalanceScatterChart"), {
        type: "scatter",
        data: {
            datasets: [{
                label: "Districts",
                data: scatterRows.map((row) => ({ x: row.x, y: row.y, name: row.name, borough: row.borough })),
                backgroundColor: "rgba(245, 166, 35, 0.75)",
                pointRadius: 5,
                pointHoverRadius: 7,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => items?.[0]?.raw?.name || "",
                        label: (context) => [
                            `Overall score: ${context.raw.x.toFixed(2)}`,
                            `Metric range: ${context.raw.y.toFixed(2)}`,
                            `${context.raw.borough}`,
                        ],
                    },
                },
            },
            scales: {
                x: {
                    title: { display: true, text: "Overall Score", color: chartDefaults.muted },
                    min: 0,
                    max: 100,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
                y: {
                    title: { display: true, text: "Metric Range", color: chartDefaults.muted },
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
            },
        },
    });
}

function initializeMetricCharts() {
    const leaderboards = resultsData.metricLeaderboards || [];
    leaderboards.forEach((metric, index) => {
        const config = metricConfigs[index];
        createBarChart(
            `metricChart${index + 1}`,
            metric.top.map((row) => ({ name: row.name, score: row.score })),
            `${config.color}cc`,
            {
                labelWrapLength: 28,
                tickFontSize: 10,
                padding: { left: 0, right: 8, top: 0, bottom: 0 },
            }
        );
    });
}

function initializeVariabilityChart() {
    const variability = resultsData.metricVariability || [];
    new Chart(document.getElementById("metricVariabilityChart"), {
        type: "bar",
        data: {
            labels: variability.map((row) => row.label),
            datasets: [{
                data: variability.map((row) => row.std),
                backgroundColor: metricConfigs.map((metric) => `${metric.color}bb`),
                borderRadius: 6,
                borderSkipped: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: chartDefaults.color } },
                y: {
                    beginAtZero: true,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
            },
        },
    });
}

function renderCompareCard(elementId, district, accentColor) {
    const el = document.getElementById(elementId);
    if (!el || !district) return;

    el.innerHTML = `
        <div class="results-compare-label" style="color: ${accentColor}">District Snapshot</div>
        <div class="results-compare-name">${district.name}</div>
        <div class="results-compare-meta">${district.borough} · Overall rank #${district.rank}</div>
        <div class="results-compare-stats">
            <div><span>Overall</span><strong>${district.overall.toFixed(2)}</strong></div>
            <div><span>Metric range</span><strong>${district.metric_range.toFixed(2)}</strong></div>
            <div><span>Air</span><strong>${district.air.toFixed(2)}</strong></div>
            <div><span>Water</span><strong>${district.water.toFixed(2)}</strong></div>
            <div><span>Education</span><strong>${district.education.toFixed(2)}</strong></div>
            <div><span>Safety</span><strong>${district.safety.toFixed(2)}</strong></div>
        </div>
    `;
}

function initializeComparisonCharts() {
    const selectA = document.getElementById("districtSelectA");
    const selectB = document.getElementById("districtSelectB");
    if (!selectA || !selectB || !districts.length) return;

    districts.forEach((district) => {
        const optionA = document.createElement("option");
        optionA.value = district.id;
        optionA.textContent = district.name;
        selectA.appendChild(optionA);

        const optionB = document.createElement("option");
        optionB.value = district.id;
        optionB.textContent = district.name;
        selectB.appendChild(optionB);
    });

    selectA.value = districts[0].id;
    selectB.value = districts[Math.min(1, districts.length - 1)].id;

    const radarChart = new Chart(document.getElementById("districtRadarChart"), {
        type: "radar",
        data: {
            labels: metricConfigs.map((metric) => metric.label),
            datasets: [],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: chartDefaults.color } } },
            scales: {
                r: {
                    min: 0,
                    max: 100,
                    grid: { color: chartDefaults.gridColor },
                    pointLabels: { color: chartDefaults.color },
                    angleLines: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted, backdropColor: "transparent" },
                },
            },
        },
    });

    const groupedChart = new Chart(document.getElementById("districtGroupedChart"), {
        type: "bar",
        data: {
            labels: metricConfigs.map((metric) => metric.label),
            datasets: [],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: chartDefaults.color } } },
            scales: {
                x: { grid: { display: false }, ticks: { color: chartDefaults.color } },
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: chartDefaults.gridColor },
                    ticks: { color: chartDefaults.muted },
                },
            },
        },
    });

    function refreshComparison() {
        const districtA = getDistrictById(selectA.value);
        const districtB = getDistrictById(selectB.value);

        radarChart.data.datasets = [
            {
                label: districtA.name,
                data: metricConfigs.map((metric) => districtA[metric.key]),
                borderColor: "#9b64ff",
                backgroundColor: "rgba(155, 100, 255, 0.18)",
                pointBackgroundColor: "#9b64ff",
            },
            {
                label: districtB.name,
                data: metricConfigs.map((metric) => districtB[metric.key]),
                borderColor: "#3b9eff",
                backgroundColor: "rgba(59, 158, 255, 0.16)",
                pointBackgroundColor: "#3b9eff",
            },
        ];
        radarChart.update();

        groupedChart.data.datasets = [
            {
                label: districtA.name,
                data: metricConfigs.map((metric) => districtA[metric.key]),
                backgroundColor: "rgba(155, 100, 255, 0.75)",
                borderRadius: 6,
            },
            {
                label: districtB.name,
                data: metricConfigs.map((metric) => districtB[metric.key]),
                backgroundColor: "rgba(59, 158, 255, 0.75)",
                borderRadius: 6,
            },
        ];
        groupedChart.update();

        renderCompareCard("compareCardA", districtA, "#9b64ff");
        renderCompareCard("compareCardB", districtB, "#3b9eff");
    }

    selectA.addEventListener("change", refreshComparison);
    selectB.addEventListener("change", refreshComparison);
    refreshComparison();
}

initializeOverallCharts();
initializeMetricCharts();
initializeVariabilityChart();
initializeComparisonCharts();
