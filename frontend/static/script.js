const METRICS = {
    overall: {label: "Overall Quality", color: "#9b64ff", key: "overall"},
    air: {label: "Air Quality", color: "#00c896", key: "air"},
    water: {label: "Drinking Water", color: "#3b9eff", key: "water"},
    edu: {label: "Education", color: "#f5a623", key: "edu"},
    nypd: {label: "Public Safety", color: "#ff5e7a", key: "nypd"}
};

const GEOGRAPHY_LABELS = {
    community_district: "Community District",
    borough: "Borough",
    nta: "Neighborhood Tabulation Area",
    zip: "ZIP Code"
};

let currentMetric = "overall";
let currentGeography = "community_district";
let map = null;
let geojsonLayer = null;
let pinnedArea = null;
let hoveredArea = null;
let scores = {};
let geographyMeta = {};

let compareMode = false;
let compareSelection = [];
let layerByAreaId = {};
let interactionGeneration = 0;

const NYC_BOUNDS = [
    [40.477399, -74.25909],
    [40.917577, -73.700272]
];

function ensureMap() {
    if (map) return map;

    map = L.map("map", {
        center: [40.7128, -74.0060],
        zoom: 10.5,
        minZoom: 10.4,
        maxBounds: NYC_BOUNDS,
        maxBoundsViscosity: 1.0
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png").addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {pane: "shadowPane"}).addTo(map);
    return map;
}

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function interpolateColor(c1, c2, t) {
    return `rgb(${Math.round(lerp(c1[0], c2[0], t))},
            ${Math.round(lerp(c1[1], c2[1], t))},
            ${Math.round(lerp(c1[2], c2[2], t))})`;
}

const COLOR_SCALES = {
    air: {light: [245, 255, 252], mid: [0, 200, 150], dark: [0, 90, 70]},
    water: {light: [245, 250, 255], mid: [59, 158, 255], dark: [15, 70, 160]},
    edu: {light: [255, 248, 235], mid: [245, 166, 35], dark: [140, 85, 0]},
    nypd: {light: [255, 240, 245], mid: [255, 94, 122], dark: [170, 40, 70]},
    overall: {light: [250, 245, 255], mid: [155, 100, 255], dark: [75, 40, 160]}
};

function scoreToColor(score, metric) {
    const t = score / 100;
    const scale = COLOR_SCALES[metric];
    if (t < 0.5) {
        return interpolateColor(scale.light, scale.mid, t * 2);
    }
    return interpolateColor(scale.mid, scale.dark, (t - 0.5) * 2);
}

function getFeatureId(feature) {
    return String(feature?.properties?.geo_id ?? feature?.properties?.BoroCD ?? "");
}

function formatAreaLabel(areaId, data = null) {
    if (currentGeography === "borough") {
        return data?.name || areaId;
    }
    if (currentGeography === "nta") {
        return data?.name || areaId;
    }
    if (currentGeography === "zip") {
        return `ZIP ${areaId}`;
    }

    if (areaId.length < 3) return `CD ${areaId}`;
    return `CD ${areaId[0]}-${areaId.slice(1)}`;
}

function styleFeature(feature) {
    const areaId = getFeatureId(feature);
    const data = scores[areaId];
    if (!data) return {fillColor: "#1a1e25", weight: 0.5, color: "#333", fillOpacity: 0.5};

    const score = data[currentMetric];
    if (score == null) return {fillColor: "#1a1e25", weight: 0.5, color: "#333", fillOpacity: 0.5};

    return {
        fillColor: scoreToColor(score, currentMetric),
        weight: 0.8,
        color: "rgba(0,0,0,0.4)",
        fillOpacity: 0.75
    };
}

function getAreaHighlightStyle(areaId) {
    const isHovered = hoveredArea === areaId;
    const isPinned = pinnedArea === areaId;
    const isCompared = compareSelection.includes(areaId);

    if (isHovered) {
        return {weight: 2.4, color: "#ffffff", fillOpacity: 0.9};
    }
    if (isPinned || isCompared) {
        return {weight: 2, color: "#ffffff", fillOpacity: 0.86};
    }
    return null;
}

function applyInteractionStyles() {
    if (!geojsonLayer) return;

    geojsonLayer.eachLayer(layer => {
        const areaId = getFeatureId(layer.feature);
        layer.setStyle(styleFeature(layer.feature));

        const highlightStyle = getAreaHighlightStyle(areaId);
        if (highlightStyle) {
            layer.setStyle(highlightStyle);
            layer.bringToFront();
        }
    });
}

function getScoreBand(score) {
    if (score >= 90) return "Excellent";
    if (score >= 70) return "Good";
    if (score >= 50) return "Moderate";
    if (score >= 30) return "Below Average";
    return "Needs Attention";
}

function formatDetailValue(value) {
    if (typeof value === "number") {
        return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3).replace(/\.?0+$/, "");
    }
    return value ?? "—";
}

function renderMetricDetails(metric, data) {
    const details = data.details?.[metric] || {};

    if (metric === "overall") {
        const overall = Math.round(data.overall);
        const airVal = Math.round(data.air);
        const waterVal = Math.round(data.water);
        const eduVal = Math.round(data.edu);
        const nypdVal = Math.round(data.nypd);
        const geographyLabel = GEOGRAPHY_LABELS[currentGeography] || "Area";
        const rankText = details.rank ? `Rank #${details.rank}` : geographyLabel;

        return `
            <div class="score-card" style="border-left-color: #9b64ff; margin-bottom: 8px;">
                <div class="score-name">Overall</div>
                <div class="score-value" style="color: #9b64ff">${overall}</div>
                <div class="score-bar-wrap">
                    <div class="score-bar-fill" style="background: #9b64ff; width: ${overall}%"></div>
                </div>
            </div>

            <div class="score-grid">
                <div class="score-card" style="border-left-color: #00c896">
                    <div class="score-name">Air Quality</div>
                    <div class="score-value" style="color: #00c896">${airVal}</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-fill" style="background: #00c896; width: ${airVal}%"></div>
                    </div>
                </div>
                <div class="score-card" style="border-left-color: #3b9eff">
                    <div class="score-name">Drinking Water</div>
                    <div class="score-value" style="color: #3b9eff">${waterVal}</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-fill" style="background: #3b9eff; width: ${waterVal}%"></div>
                    </div>
                </div>
                <div class="score-card" style="border-left-color: #f5a623">
                    <div class="score-name">Education</div>
                    <div class="score-value" style="color: #f5a623">${eduVal}</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-fill" style="background: #f5a623; width: ${eduVal}%"></div>
                    </div>
                </div>
                <div class="score-card" style="border-left-color: #ff5e7a">
                    <div class="score-name">Public Safety</div>
                    <div class="score-value" style="color: #ff5e7a">${nypdVal}</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-fill" style="background: #ff5e7a; width: ${nypdVal}%"></div>
                    </div>
                </div>
            </div>

            <div class="metric-focus-panel">
                <div class="metric-focus-header">
                    <span class="metric-focus-title">Combined NQI</span>
                    <span class="metric-focus-badge">${rankText}</span>
                </div>
                <div class="metric-focus-copy">${details.method || "Equal average across all four project metrics."}</div>
            </div>
        `;
    }

    const score = Math.round(data[metric]);
    const metricMeta = METRICS[metric];
    let detailRows = "";

    if (metric === "air") {
        detailRows = `
            <div class="metric-detail-row"><span>Raw Pollution Burden</span><strong>${formatDetailValue(details.raw_score)}</strong></div>
            <div class="metric-detail-row"><span>PM2.5</span><strong>${formatDetailValue(details.pm25)}</strong></div>
            <div class="metric-detail-row"><span>NO2</span><strong>${formatDetailValue(details.no2)}</strong></div>
            <div class="metric-detail-row"><span>O3</span><strong>${formatDetailValue(details.o3)}</strong></div>
        `;
    } else if (metric === "water") {
        detailRows = `
            <div class="metric-detail-row"><span>Raw Water Score</span><strong>${formatDetailValue(details.raw_score)}</strong></div>
            <div class="metric-detail-row"><span>Sampling Sites Used</span><strong>${formatDetailValue(details.sample_sites)}</strong></div>
            <div class="metric-detail-row"><span>Scale</span><strong>Higher is better</strong></div>
        `;
    } else if (metric === "edu") {
        detailRows = `
            <div class="metric-detail-row"><span>Raw Education Score</span><strong>${formatDetailValue(details.raw_score)}</strong></div>
            <div class="metric-detail-row"><span>Schools Used</span><strong>${formatDetailValue(details.schools)}</strong></div>
            <div class="metric-detail-row"><span>Scale</span><strong>Higher is better</strong></div>
        `;
    } else if (metric === "nypd") {
        detailRows = `
            <div class="metric-detail-row"><span>Raw Safety Score</span><strong>${formatDetailValue(details.raw_score)}</strong></div>
            <div class="metric-detail-row"><span>Incident Count</span><strong>${formatDetailValue(details.incidents)}</strong></div>
            <div class="metric-detail-row"><span>Weighted Severity Sum</span><strong>${formatDetailValue(details.weighted_severity_sum)}</strong></div>
        `;
    }

    return `
        <div class="score-card metric-hero-card" style="border-left-color: ${metricMeta.color}; margin-bottom: 12px;">
            <div class="score-name">${metricMeta.label}</div>
            <div class="score-value" style="color: ${metricMeta.color}">${score}</div>
            <div class="score-bar-wrap">
                <div class="score-bar-fill" style="background: ${metricMeta.color}; width: ${score}%"></div>
            </div>
        </div>

        <div class="metric-focus-panel">
            <div class="metric-focus-header">
                <span class="metric-focus-title">${metricMeta.label}</span>
                <span class="metric-focus-badge">${getScoreBand(score)}</span>
            </div>
            <div class="metric-focus-copy">${GEOGRAPHY_LABELS[currentGeography] || "Area"}-level ${metricMeta.label.toLowerCase()} score shown on a 0-100 normalized scale.</div>
            <div class="metric-detail-list">
                ${detailRows}
            </div>
        </div>
    `;
}

function renderActions(areaId, data) {
    if (currentGeography !== "community_district") {
        return `
            <div class="action-buttons geography-note-actions">
                <div class="geography-note">Detailed profile pages and rentals remain available in community district view.</div>
            </div>
        `;
    }

    return `
        <div class="action-buttons">
            <a href="/neighborhood/${areaId}/" class="btn btn-primary read-more-btn">Read More</a>
            <a href="/neighborhood/${areaId}/#rentalsSection" class="btn btn-secondary rentals-btn">Rentals</a>
        </div>
    `;
}

function renderAreaBlock(areaId, data, showHeader = true) {
    const heading = formatAreaLabel(areaId, data);
    let subheading = data.name ? data.name.toUpperCase() : heading;

    if (currentGeography === "borough") {
        subheading = "BOROUGH ROLLUP";
    } else if (currentGeography === "nta") {
        subheading = `NTA ${areaId}`;
    } else if (currentGeography === "zip") {
        subheading = data.name ? data.name.toUpperCase() : "MODZCTA";
    }

    return `
        <div>
            ${showHeader ? `<div class="tooltip-zip">${heading}</div>
            <div class="tooltip-borough">${subheading}</div>` : ""}
            ${renderMetricDetails(currentMetric, data)}
            ${renderActions(areaId, data)}
        </div>
    `;
}

function showTooltip(primaryArea, primaryData, secondaryArea = null, secondaryData = null) {
    const panel = document.getElementById("tooltipPanel");
    const contentDiv = document.getElementById("tooltipContent");
    const closeBtn = document.getElementById("closeCompareTooltip");

    if (secondaryArea && secondaryData) {
        panel.classList.add("comparison-mode");
        closeBtn.style.display = "flex";
        contentDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #ff5e7a;">COMPARE MODE</div>
            </div>
            <div class="comparison-split">
                <div class="neighborhood-col">
                    ${renderAreaBlock(primaryArea, primaryData, true)}
                </div>
                <div class="neighborhood-col">
                    ${renderAreaBlock(secondaryArea, secondaryData, true)}
                </div>
            </div>
        `;
    } else {
        panel.classList.remove("comparison-mode");
        closeBtn.style.display = "none";
        contentDiv.innerHTML = renderAreaBlock(primaryArea, primaryData, true);
    }

    panel.style.display = "block";
}

function resetSelectionState() {
    pinnedArea = null;
    hoveredArea = null;
    compareSelection = [];
    const panel = document.getElementById("tooltipPanel");
    const contentDiv = document.getElementById("tooltipContent");
    panel.classList.remove("comparison-mode");
    panel.style.display = "none";
    contentDiv.innerHTML = "";
    const instruction = document.getElementById("compareInstruction");
    instruction.style.display = compareMode ? "block" : "none";
    applyInteractionStyles();
}

function updateCompareInstruction() {
    const instruction = document.getElementById("compareInstruction");
    const label = (GEOGRAPHY_LABELS[currentGeography] || "area").toLowerCase();
    instruction.textContent = `Click two ${label}s on the map to compare`;
}

function toggleCompareMode() {
    compareMode = !compareMode;
    const btn = document.getElementById("compareBtn");
    const instruction = document.getElementById("compareInstruction");

    if (compareMode) {
        btn.classList.add("active");
        btn.textContent = "Cancel Compare";
        instruction.style.display = "block";
        pinnedArea = null;
        hoveredArea = null;
        compareSelection = [];
        document.getElementById("tooltipPanel").style.display = "none";
        applyInteractionStyles();
    } else {
        btn.classList.remove("active");
        btn.textContent = "Compare";
        instruction.style.display = "none";
        compareSelection = [];
        const panel = document.getElementById("tooltipPanel");
        panel.classList.remove("comparison-mode");
        if (pinnedArea && scores[pinnedArea]) {
            showTooltip(pinnedArea, scores[pinnedArea]);
        } else {
            panel.style.display = "none";
        }
        applyInteractionStyles();
    }
}

function addToComparison(areaId) {
    if (!compareMode || compareSelection.includes(areaId)) return;

    if (compareSelection.length < 2) {
        compareSelection.push(areaId);

        if (compareSelection.length === 1) {
            showTooltip(compareSelection[0], scores[compareSelection[0]]);
        } else {
            const area1 = compareSelection[0];
            const area2 = compareSelection[1];
            showTooltip(area1, scores[area1], area2, scores[area2]);
            document.getElementById("compareInstruction").style.display = "none";
        }
        applyInteractionStyles();
    }
}

function clearComparison() {
    compareSelection = [];
    const panel = document.getElementById("tooltipPanel");
    panel.classList.remove("comparison-mode");
    if (pinnedArea && scores[pinnedArea]) {
        showTooltip(pinnedArea, scores[pinnedArea]);
    } else {
        panel.style.display = "none";
    }
    if (compareMode) {
        document.getElementById("compareInstruction").style.display = "block";
    }
    applyInteractionStyles();
}

function bindFeatureEvents(feature, layer) {
    const areaId = getFeatureId(feature);
    const data = scores[areaId];
    const generationAtBind = interactionGeneration;

    layer.on({
        mouseover: e => {
            if (generationAtBind !== interactionGeneration) return;
            hoveredArea = areaId;
            applyInteractionStyles();

            if (compareMode) {
                if (compareSelection.length === 0 && data) showTooltip(areaId, data);
                return;
            }

            if (data) showTooltip(areaId, data);
        },
        mouseout: e => {
            if (generationAtBind !== interactionGeneration) return;
            if (hoveredArea === areaId) {
                hoveredArea = null;
            }
            applyInteractionStyles();

            if (compareMode) {
                if (compareSelection.length === 0) {
                    document.getElementById("tooltipPanel").style.display = "none";
                } else if (compareSelection.length === 1) {
                    showTooltip(compareSelection[0], scores[compareSelection[0]]);
                }
                return;
            }

            if (pinnedArea && scores[pinnedArea]) {
                showTooltip(pinnedArea, scores[pinnedArea]);
            } else {
                document.getElementById("tooltipPanel").style.display = "none";
            }
        },
        click: () => {
            if (generationAtBind !== interactionGeneration) return;
            if (compareMode) {
                addToComparison(areaId);
            } else {
                pinnedArea = (pinnedArea === areaId) ? null : areaId;
                if (pinnedArea === null) {
                    document.getElementById("tooltipPanel").style.display = "none";
                } else if (data) {
                    showTooltip(areaId, data);
                }
                applyInteractionStyles();
            }
        }
    });
}

function renderGeoLayer(geoData) {
    ensureMap();

    if (geojsonLayer) {
        map.removeLayer(geojsonLayer);
    }
    layerByAreaId = {};

    const filtered = {
        type: "FeatureCollection",
        features: geoData.features.filter(feature => scores[getFeatureId(feature)])
    };

    geojsonLayer = L.geoJSON(filtered, {
        style: styleFeature,
        onEachFeature: (feature, layer) => {
            const areaId = getFeatureId(feature);
            layerByAreaId[areaId] = layer;
            bindFeatureEvents(feature, layer);
        }
    }).addTo(map);

    applyInteractionStyles();

    const bounds = geojsonLayer.getBounds();
    if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.05));
    }
}

async function loadGeography(geography) {
    interactionGeneration += 1;
    currentGeography = geography;
    scores = {};
    resetSelectionState();

    const response = await fetch(`/api/map-data/${geography}`);
    if (!response.ok) {
        throw new Error(`Failed to load map data for ${geography}`);
    }

    const payload = await response.json();
    scores = payload.scores || {};
    document.getElementById("panelSubtitle").textContent = payload.subtitle || `by ${payload.label.toLowerCase()}`;
    updateCompareInstruction();
    renderGeoLayer(payload.geojson);
}

async function init() {
    try {
        const geoResponse = await fetch("/api/geographies");
        geographyMeta = await geoResponse.json();

        const select = document.getElementById("geographySelect");
        select.innerHTML = Object.entries(geographyMeta).map(([key, meta]) => (
            `<option value="${key}">${meta.label}</option>`
        )).join("");
        select.value = currentGeography;

        await loadGeography(currentGeography);

        select.addEventListener("change", async e => {
            await loadGeography(e.target.value);
        });
    } catch (err) {
        console.error("Error loading map data:", err);
    }
}

document.querySelectorAll(".metric-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".metric-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentMetric = btn.dataset.metric;
        if (geojsonLayer) applyInteractionStyles();

        if (compareMode && compareSelection.length === 2) {
            const area1 = compareSelection[0];
            const area2 = compareSelection[1];
            showTooltip(area1, scores[area1], area2, scores[area2]);
        } else if (pinnedArea && scores[pinnedArea]) {
            showTooltip(pinnedArea, scores[pinnedArea]);
        }
    });
});

document.getElementById("compareBtn").addEventListener("click", toggleCompareMode);
document.getElementById("closeCompareTooltip").addEventListener("click", () => {
    if (compareMode) {
        clearComparison();
    } else {
        document.getElementById("tooltipPanel").style.display = "none";
        pinnedArea = null;
        hoveredArea = null;
        applyInteractionStyles();
    }
});

document.addEventListener("click", e => {
    const panel = document.getElementById("tooltipPanel");
    if (panel.style.display === "block" && !compareMode && pinnedArea === null) {
        if (!panel.contains(e.target) && !e.target.closest(".leaflet-interactive")) {
            panel.style.display = "none";
        }
    }
});

window.addEventListener("load", () => {
    window.setTimeout(init, 0);
});
