const districtId = typeof DISTRICT_ID !== "undefined" ? DISTRICT_ID : "101";

function formatDistrictLabel(id) {
    if (id.length < 3) return `CD ${id}`;
    return `CD ${id[0]}-${id.slice(1)}`;
}

function cleanRentalAreaName(name) {
    return (name || "NYC")
        .replace(/\(.*?\)/g, "")
        .replace(/\s+/g, " ")
        .trim();
}

function buildProviderSearchUrl(name, domain) {
    const area = cleanRentalAreaName(name);
    let searchQuery = "";

    switch(domain) {
        case "apartments.com":
            searchQuery = `${area} NYC apartments for rent site:apartments.com`;
            break;
        case "zillow.com":
            searchQuery = `${area} NYC rentals site:zillow.com`;
            break;
        case "streeteasy.com":
            searchQuery = `${area} NYC apartments site:streeteasy.com`;
            break;
        case "trulia.com":
            searchQuery = `${area} NYC rentals site:trulia.com`;
            break;
        default:
            searchQuery = `${area} apartments for rent NYC site:${domain}`;
    }

    return `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}`;
}

function openRentalSearch(name, domain = "apartments.com") {
    window.open(buildProviderSearchUrl(name, domain), "_blank", "noopener,noreferrer");
}

async function loadNeighborhoodData() {
    try {
        const scoresRes = await fetch("/api/scores");
        const scores = await scoresRes.json();
        const data = scores[districtId];

        if (!data) {
            document.body.innerHTML = '<div style="text-align: center; padding: 100px;">Community district not found</div>';
            return;
        }

        // Update hero section
        const neighborhoodBadge = document.getElementById("neighborhoodBadge");
        if (neighborhoodBadge) {
            neighborhoodBadge.textContent = data.borough || "Community District";
        }

        const districtCodeEl = document.getElementById("districtCode");
        if (districtCodeEl) {
            districtCodeEl.textContent = formatDistrictLabel(districtId);
        }

        const neighborhoodNameEl = document.getElementById("neighborhoodName");
        if (neighborhoodNameEl) {
            neighborhoodNameEl.textContent = data.name;
        }

        const overallScoreEl = document.getElementById("overallScore");
        if (overallScoreEl) {
            overallScoreEl.textContent = Math.round(data.overall);
        }

        // Update metrics
        const metrics = ["air", "water", "edu", "nypd"];
        metrics.forEach(m => {
            const value = Math.round(data[m]);
            const valueEl = document.getElementById(`${m}Value`);
            const barEl = document.getElementById(`${m}Bar`);

            if (valueEl) valueEl.textContent = value;
            if (barEl) {
                setTimeout(() => {
                    barEl.style.width = `${value}%`;
                }, 100);
            }
        });

        // Update summary section
        const districtInfoEl = document.getElementById("districtInfo");
        if (districtInfoEl) districtInfoEl.textContent = formatDistrictLabel(districtId);

        const boroughInfoEl = document.getElementById("boroughInfo");
        if (boroughInfoEl) boroughInfoEl.textContent = data.borough || "—";

        const rankInfoEl = document.getElementById("rankInfo");
        if (rankInfoEl) rankInfoEl.textContent = `#${data.details?.overall?.rank ?? "—"}`;

        const waterCoverageEl = document.getElementById("waterCoverageInfo");
        if (waterCoverageEl) waterCoverageEl.textContent = data.details?.water?.sample_sites ?? "—";

        const schoolCoverageEl = document.getElementById("schoolCoverageInfo");
        if (schoolCoverageEl) schoolCoverageEl.textContent = data.details?.edu?.schools ?? "—";

        const incidentCount = data.details?.nypd?.incidents;
        const incidentInfoEl = document.getElementById("incidentInfo");
        if (incidentInfoEl) {
            incidentInfoEl.textContent = typeof incidentCount === "number"
                ? incidentCount.toLocaleString()
                : "—";
        }

    } catch (err) {
        console.error("Error loading data:", err);
        const neighborhoodNameEl = document.getElementById("neighborhoodName");
        if (neighborhoodNameEl) {
            neighborhoodNameEl.textContent = "Error loading data";
        }
    }
}

function viewAllListings(domain = "apartments.com") {
    const nameEl = document.getElementById("neighborhoodName");
    const name = nameEl ? nameEl.textContent : "NYC";
    openRentalSearch(name, domain);
}

function animateProgressBarsOnScroll() {
    const progressBars = document.querySelectorAll('.progress-fill');
    const observerOptions = {
        threshold: 0.3,
        rootMargin: '0px 0px -100px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const bar = entry.target;
                const width = bar.style.width;
                if (width && width !== '0%') {
                    observer.unobserve(bar);
                }
            }
        });
    }, observerOptions);

    progressBars.forEach(bar => observer.observe(bar));
}

function addMetricCardHints() {
    const metricCards = document.querySelectorAll('.metric-card');
    const hints = {
        air: 'Based on EPA air quality data, including particulate matter and ozone levels',
        water: 'Based on DEP water quality testing results from sample sites',
        edu: 'Based on Department of Education school quality reports and ratings',
        safety: 'Based on NYPD crime incident data and response times'
    };

    metricCards.forEach(card => {
        const metricType = card.getAttribute('data-metric');
        if (metricType && hints[metricType]) {
            card.setAttribute('title', hints[metricType]);
        }
    });
}

function setupKeyboardNavigation() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            // Future modal close functionality
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const apartmentsBtn = document.getElementById("apartmentsBtn");
    const zillowBtn = document.getElementById("zillowBtn");
    const streetEasyBtn = document.getElementById("streetEasyBtn");
    const truliaBtn = document.getElementById("truliaBtn");

    if (apartmentsBtn) apartmentsBtn.addEventListener("click", () => viewAllListings("apartments.com"));
    if (zillowBtn) zillowBtn.addEventListener("click", () => viewAllListings("zillow.com"));
    if (streetEasyBtn) streetEasyBtn.addEventListener("click", () => viewAllListings("streeteasy.com"));
    if (truliaBtn) truliaBtn.addEventListener("click", () => viewAllListings("trulia.com"));

    loadNeighborhoodData();

    animateProgressBarsOnScroll();
    addMetricCardHints();
    setupKeyboardNavigation();

    const sections = document.querySelectorAll('.section, .rental-card');
    sections.forEach((section, index) => {
        section.style.opacity = '0';
        section.style.transform = 'translateY(20px)';
        section.style.transition = `opacity 0.5s ease, transform 0.5s ease`;

        setTimeout(() => {
            section.style.opacity = '1';
            section.style.transform = 'translateY(0)';
        }, 100 + (index * 100));
    });
});