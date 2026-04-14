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
    air: {
        light: [245, 255, 252],
        mid: [0, 200, 150],
        dark: [0, 90, 70]
    },
    water: {
        light: [245, 250, 255],
        mid: [59, 158, 255],
        dark: [15, 70, 160]
    },
    edu: {
        light: [255, 248, 235],
        mid: [245, 166, 35],
        dark: [140, 85, 0]
    },
    nypd: {
        light: [255, 240, 245],
        mid: [255, 94, 122],
        dark: [170, 40, 70]
    },
    overall: {
        light: [250, 245, 255],
        mid: [155, 100, 255],
        dark: [75, 40, 160]
    }
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

function showTooltip(zip, data) {
    const panel = document.getElementById("tooltipPanel");
    document.getElementById("ttZip").textContent = zip;
    document.getElementById("ttBorough").textContent = data.neighborhood.toUpperCase();

    ['overall', 'air', 'water', 'edu', 'nypd'].forEach(m => {
        const val = Math.round(data[m]);
        document.getElementById(`tt${m.charAt(0).toUpperCase() + m.slice(1)}`).textContent = val;
        document.getElementById(`bar${m.charAt(0).toUpperCase() + m.slice(1)}`).style.width = val + "%";
    });

    panel.style.display = "block";
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
                        e.target.setStyle({weight: 2, color: "#fff", fillOpacity: 0.9});
                        if (data) showTooltip(zip, data);
                    },
                    mouseout: (e) => {
                        if (zip !== pinnedZip) {
                            geojsonLayer.resetStyle(e.target);
                            if (!pinnedZip) document.getElementById("tooltipPanel").style.display = "none";
                        }
                    },
                    click: (e) => {
                        pinnedZip = (pinnedZip === zip) ? null : zip;
                        if (data) showTooltip(zip, data);
                    }
                });
            }
        }).addTo(map);

    } catch (err) {
        console.error("Error loading map data:", err);
    }
}

document.querySelectorAll(".metric-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".metric-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentMetric = btn.dataset.metric;
        if (geojsonLayer) geojsonLayer.setStyle(styleFeature);
    });
});

init();