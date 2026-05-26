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
    const query = `site:${domain} ${area} apartments for rent NYC`;
    return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
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

        document.getElementById("districtCode").textContent = formatDistrictLabel(districtId);
        document.getElementById("neighborhoodName").textContent = data.name;
        document.getElementById("breadcrumbNeighborhood").textContent = data.name;
        document.getElementById("overallScore").textContent = Math.round(data.overall);

        const metrics = ["air", "water", "edu", "nypd"];
        metrics.forEach(m => {
            const value = Math.round(data[m]);
            document.getElementById(`${m}Value`).textContent = value;
            document.getElementById(`${m}Bar`).style.width = `${value}%`;
        });

        document.getElementById("districtInfo").textContent = formatDistrictLabel(districtId);
        document.getElementById("boroughInfo").textContent = data.borough;
        document.getElementById("rankInfo").textContent = `#${data.details?.overall?.rank ?? "—"}`;
        document.getElementById("waterCoverageInfo").textContent = data.details?.water?.sample_sites ?? "—";
        document.getElementById("schoolCoverageInfo").textContent = data.details?.edu?.schools ?? "—";
        const incidentCount = data.details?.nypd?.incidents;
        document.getElementById("incidentInfo").textContent = typeof incidentCount === "number"
            ? incidentCount.toLocaleString()
            : "—";

        await loadRentalListings(districtId, data.name);

    } catch (err) {
        console.error("Error loading data:", err);
        document.getElementById("neighborhoodName").textContent = "Error loading data";
    }
}

async function loadRentalListings(id, name) {
    try {
        const response = await fetch(`/api/listings/${id}`);
        const sampleListings = await response.json();

        const container = document.getElementById("listingsContainer");
        if (!container) return;

        container.innerHTML = sampleListings.map(listing => `
            <div class="listing rentals-search-card" data-rental-area="${name}">
                <div class="listing-price">${listing.price}/mo</div>
                <div class="listing-details">${listing.beds} bed • ${listing.baths} bath • ${listing.sqft} sqft</div>
                <div class="listing-address">${listing.address}</div>
                <div class="listing-link-hint">Search similar rentals in ${cleanRentalAreaName(name)} on Apartments.com</div>
            </div>
        `).join("");

        container.querySelectorAll(".rentals-search-card").forEach(card => {
            card.addEventListener("click", () => openRentalSearch(card.dataset.rentalArea, "apartments.com"));
        });
    } catch (err) {
        console.error("Error loading listings:", err);
        const container = document.getElementById("listingsContainer");
        if (container) {
            container.innerHTML = '<div style="padding: 20px; text-align: center;">Unable to load listings</div>';
        }
    }
}

function viewAllListings(domain = "apartments.com") {
    const name = document.getElementById("neighborhoodName").textContent;
    openRentalSearch(name, domain);
}

document.addEventListener("DOMContentLoaded", () => {
    const apartmentsBtn = document.getElementById("apartmentsBtn");
    const zillowBtn = document.getElementById("zillowBtn");
    const streetEasyBtn = document.getElementById("streetEasyBtn");
    if (apartmentsBtn) apartmentsBtn.addEventListener("click", () => viewAllListings("apartments.com"));
    if (zillowBtn) zillowBtn.addEventListener("click", () => viewAllListings("zillow.com"));
    if (streetEasyBtn) streetEasyBtn.addEventListener("click", () => viewAllListings("streeteasy.com"));

    loadNeighborhoodData();
});
