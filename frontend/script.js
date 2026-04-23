const METRICS = {
    overall: {label: "Overall Quality", color: "#9b64ff", key: "overall"},
    air: {label: "Air Quality", color: "#00c896", key: "air"},
    water: {label: "Drinking Water", color: "#3b9eff", key: "water"},
    edu: {label: "Education", color: "#f5a623", key: "edu"},
    nypd: {label: "NYPD Complaints", color: "#ff5e7a", key: "nypd"}
};

let currentMetric = "overall";
let geojsonLayer = null;
let pinnedZip = null;
let SCORES = {};

// Comparison mode state
let compareMode = false;
let compareSelection = [];

const NYC_BOUNDS = [
    [40.477399, -74.25909],
    [40.917577, -73.700272]
];

const map = L.map("map", {
    center: [40.7128, -74.0060],
    zoom: 10.5,
    minZoom: 10.4,
    maxBounds: NYC_BOUNDS,
    maxBoundsViscosity: 1.0
});

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png").addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {pane: 'shadowPane'}).addTo(map);

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function interpolateColor(c1, c2, t) {
    return `rgb(${Math.round(lerp(c1[0], c2[0], t))},
            ${Math.round(lerp(c1[1], c2[1], t))},
            ${Math.round(lerp(c1[2], c2[2], t))})`;
}

const COLOR_SCALES = {
    air: { light: [245, 255, 252], mid: [0, 200, 150], dark: [0, 90, 70] },
    water: { light: [245, 250, 255], mid: [59, 158, 255], dark: [15, 70, 160] },
    edu: { light: [255, 248, 235], mid: [245, 166, 35], dark: [140, 85, 0] },
    nypd: { light: [255, 240, 245], mid: [255, 94, 122], dark: [170, 40, 70] },
    overall: { light: [250, 245, 255], mid: [155, 100, 255], dark: [75, 40, 160] }
};

function scoreToColor(score, metric) {
    const t = score / 100;
    const scale = COLOR_SCALES[metric];
    if (t < 0.5) {
        return interpolateColor(scale.light, scale.mid, t * 2);
    } else {
        return interpolateColor(scale.mid, scale.dark, (t - 0.5) * 2);
    }
}

function styleFeature(feature) {
    const zip = feature.properties.ZIPCODE;
    const data = SCORES[zip];
    if (!data) return {fillColor: "#1a1e25", weight: 0.5, color: "#333", fillOpacity: 0.5};
    const score = data[currentMetric];
    return {
        fillColor: scoreToColor(score, currentMetric),
        weight: 0.8,
        color: "rgba(0,0,0,0.4)",
        fillOpacity: 0.75
    };
}

// Render a neighborhood block (no descriptions, just scores + buttons)
function renderNeighborhoodBlock(zip, data, showHeader = true) {
    const overall = Math.round(data.overall);
    const airVal = Math.round(data.air);
    const waterVal = Math.round(data.water);
    const eduVal = Math.round(data.edu);
    const nypdVal = Math.round(data.nypd);
    const neighborhoodName = data.neighborhood ? data.neighborhood.toUpperCase() : zip;

    return `
        <div>
            ${showHeader ? `<div class="tooltip-zip">${zip}</div>
            <div class="tooltip-borough">${neighborhoodName}</div>` : ''}
            
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
                    <div class="score-name">NYPD Complaints</div>
                    <div class="score-value" style="color: #ff5e7a">${nypdVal}</div>
                    <div class="score-bar-wrap">
                        <div class="score-bar-fill" style="background: #ff5e7a; width: ${nypdVal}%"></div>
                    </div>
                </div>
            </div>
            
            <div class="action-buttons">
                <a href="#" class="btn btn-primary read-more-btn" data-zip="${zip}" data-neighborhood="${data.neighborhood}">Read More</a>
                <a href="#" class="btn btn-secondary rentals-btn" data-zip="${zip}" data-neighborhood="${data.neighborhood}" target="_blank">Rentals</a>
            </div>
        </div>
    `;
}

// Show tooltip: single or dual comparison
function showTooltip(primaryZip, primaryData, secondaryZip = null, secondaryData = null) {
    const panel = document.getElementById("tooltipPanel");
    const contentDiv = document.getElementById("tooltipContent");
    const closeBtn = document.getElementById("closeCompareTooltip");

    if (secondaryZip && secondaryData) {
        panel.classList.add("comparison-mode");
        closeBtn.style.display = "flex";
        contentDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #ff5e7a;">COMPARE MODE</div>
            </div>
            <div class="comparison-split">
                <div class="neighborhood-col">
                    ${renderNeighborhoodBlock(primaryZip, primaryData, true)}
                </div>
                <div class="neighborhood-col">
                    ${renderNeighborhoodBlock(secondaryZip, secondaryData, true)}
                </div>
            </div>
        `;
    } else {
        panel.classList.remove("comparison-mode");
        closeBtn.style.display = "none";
        contentDiv.innerHTML = renderNeighborhoodBlock(primaryZip, primaryData, true);
    }

    // Attach event listeners to buttons
    document.querySelectorAll('.read-more-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const zip = btn.dataset.zip;
            window.location.href = `neighborhood.html?zip=${zip}`;
        });
    });

    document.querySelectorAll('.rentals-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const neighborhood = btn.dataset.neighborhood;
            const zip = btn.dataset.zip;
            const url = `https://streeteasy.com/for-rent/${neighborhood.toLowerCase().replace(/\s+/g, '-')}/zip:${zip}`;
            window.open(url, '_blank');
        });
    });

    panel.style.display = "block";
}

function hideTooltip() {
    if (!compareMode && pinnedZip === null) {
        document.getElementById("tooltipPanel").style.display = "none";
    }
}

// Toggle compare mode
function toggleCompareMode() {
    compareMode = !compareMode;
    const btn = document.getElementById("compareBtn");
    const instruction = document.getElementById("compareInstruction");

    if (compareMode) {
        btn.classList.add("active");
        btn.textContent = "Cancel Compare";
        instruction.style.display = "block";
        compareSelection = [];
        if (pinnedZip) pinnedZip = null;
        document.getElementById("tooltipPanel").style.display = "none";
    } else {
        btn.classList.remove("active");
        btn.textContent = "Compare";
        instruction.style.display = "none";
        compareSelection = [];
        const panel = document.getElementById("tooltipPanel");
        panel.classList.remove("comparison-mode");
        if (pinnedZip && SCORES[pinnedZip]) {
            showTooltip(pinnedZip, SCORES[pinnedZip]);
        } else {
            panel.style.display = "none";
        }
    }
}

// Add zip to comparison
function addToComparison(zip, data) {
    if (!compareMode) return;
    if (compareSelection.includes(zip)) return;

    if (compareSelection.length < 2) {
        compareSelection.push(zip);

        if (compareSelection.length === 1) {
            showTooltip(compareSelection[0], SCORES[compareSelection[0]]);
        } else if (compareSelection.length === 2) {
            const zip1 = compareSelection[0];
            const zip2 = compareSelection[1];
            showTooltip(zip1, SCORES[zip1], zip2, SCORES[zip2]);
            document.getElementById("compareInstruction").style.display = "none";
        }
    }
}

// Clear comparison
function clearComparison() {
    compareSelection = [];
    const panel = document.getElementById("tooltipPanel");
    panel.classList.remove("comparison-mode");
    if (pinnedZip && SCORES[pinnedZip]) {
        showTooltip(pinnedZip, SCORES[pinnedZip]);
    } else {
        panel.style.display = "none";
    }
    if (compareMode) {
        document.getElementById("compareInstruction").style.display = "block";
    }
}

async function init() {
    try {
        const res = await fetch('data.json');
        SCORES = await res.json();

        Object.keys(SCORES).forEach(zip => {
            const d = SCORES[zip];
            SCORES[zip].overall = (d.air + d.water + d.edu + d.nypd) / 4;
        });

        const geoRes = await fetch("https://raw.githubusercontent.com/fedhere/PUI2015_EC/master/mam1612_EC/nyc-zip-code-tabulation-areas-polygons.geojson");
        const geoData = await geoRes.json();

        const filtered = {
            type: "FeatureCollection",
            features: geoData.features.filter(f => {
                const zip = f.properties.postalCode || f.properties.ZIPCODE;
                f.properties.ZIPCODE = zip;
                return SCORES[zip];
            })
        };

        geojsonLayer = L.geoJSON(filtered, {
            style: styleFeature,
            onEachFeature: (feature, layer) => {
                const zip = feature.properties.ZIPCODE;
                const data = SCORES[zip];
                layer.on({
                    mouseover: (e) => {
                        if (!compareMode && pinnedZip === null) {
                            e.target.setStyle({weight: 2, color: "#fff", fillOpacity: 0.9});
                            if (data) showTooltip(zip, data);
                        } else if (compareMode && compareSelection.length < 2 && pinnedZip === null) {
                            e.target.setStyle({weight: 2, color: "#fff", fillOpacity: 0.9});
                            if (data) showTooltip(zip, data);
                        }
                    },
                    mouseout: (e) => {
                        if (!compareMode && pinnedZip === null) {
                            geojsonLayer.resetStyle(e.target);
                            if (!pinnedZip) {
                                document.getElementById("tooltipPanel").style.display = "none";
                            }
                        } else if (compareMode && compareSelection.length < 2 && pinnedZip === null) {
                            geojsonLayer.resetStyle(e.target);
                            if (!pinnedZip && compareSelection.length === 0) {
                                document.getElementById("tooltipPanel").style.display = "none";
                            }
                        }
                    },
                    click: (e) => {
                        if (compareMode) {
                            addToComparison(zip, data);
                        } else {
                            pinnedZip = (pinnedZip === zip) ? null : zip;
                            if (data) showTooltip(zip, data);
                        }
                    }
                });
            }
        }).addTo(map);

    } catch (err) {
        console.error("Error loading map data:", err);
    }
}

// Event listeners
document.querySelectorAll(".metric-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".metric-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentMetric = btn.dataset.metric;
        if (geojsonLayer) geojsonLayer.setStyle(styleFeature);
    });
});

document.getElementById("compareBtn").addEventListener("click", toggleCompareMode);
document.getElementById("closeCompareTooltip").addEventListener("click", () => {
    if (compareMode) {
        clearComparison();
    } else {
        document.getElementById("tooltipPanel").style.display = "none";
        pinnedZip = null;
    }
});

// Close tooltip when clicking outside
document.addEventListener('click', function(e) {
    const panel = document.getElementById("tooltipPanel");
    const compareBtn = document.getElementById("compareBtn");
    if (panel.style.display === 'block' && !compareMode && pinnedZip === null) {
        if (!panel.contains(e.target) && !e.target.closest('.leaflet-interactive')) {
            panel.style.display = 'none';
        }
    }
});

init();