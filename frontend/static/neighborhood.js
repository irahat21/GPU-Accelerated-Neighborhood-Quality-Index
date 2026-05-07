const zipCode = typeof ZIP_CODE !== 'undefined' ? ZIP_CODE : '10001';

async function loadNeighborhoodData() {
    try {
        const scoresRes = await fetch('/api/scores');
        const SCORES = await scoresRes.json();
        const data = SCORES[zipCode];

        if (!data) {
            document.body.innerHTML = '<div style="text-align: center; padding: 100px;">Zip code not found</div>';
            return;
        }

        // Calculate overall score
        const overall = Math.round((data.air + data.water + data.edu + data.nypd) / 4);

        // Update page content
        document.getElementById('zipCode').textContent = zipCode;
        document.getElementById('neighborhoodName').textContent = data.neighborhood;
        document.getElementById('breadcrumbNeighborhood').textContent = data.neighborhood;
        document.getElementById('overallScore').textContent = overall;

        // Update metrics
        const metrics = ['air', 'water', 'edu', 'nypd'];
        metrics.forEach(m => {
            const value = Math.round(data[m]);
            document.getElementById(`${m}Value`).textContent = value;
            document.getElementById(`${m}Bar`).style.width = value + '%';
        });

        // Determine borough from zip code
        const boroughRes = await fetch(`/api/borough/${zipCode}`);
        const boroughData = await boroughRes.json();
        document.getElementById('boroughInfo').textContent = boroughData.borough;

        // Load sample listings
        await loadRentalListings(zipCode, data.neighborhood);

    } catch (err) {
        console.error('Error loading data:', err);
        document.getElementById('neighborhoodName').textContent = 'Error loading data';
    }
}

async function loadRentalListings(zip, neighborhood) {
    try {
        const response = await fetch(`/api/listings/${zip}`);
        const sampleListings = await response.json();

        const container = document.getElementById('listingsContainer');
        if (!container) return;

        container.innerHTML = sampleListings.map(listing => `
            <div class="listing" onclick="window.open('https://streeteasy.com/for-rent/${neighborhood.toLowerCase().replace(/\s+/g, '-')}/zip:${zip}', '_blank')">
                <div class="listing-price">${listing.price}/mo</div>
                <div class="listing-details">${listing.beds} bed • ${listing.baths} bath • ${listing.sqft} sqft</div>
                <div class="listing-address">${listing.address}</div>
            </div>
        `).join('');
    } catch (err) {
        console.error('Error loading listings:', err);
        const container = document.getElementById('listingsContainer');
        if (container) {
            container.innerHTML = '<div style="padding: 20px; text-align: center;">Unable to load listings</div>';
        }
    }
}

function viewAllListings() {
    const neighborhood = document.getElementById('neighborhoodName').textContent;
    const url = `https://streeteasy.com/for-rent/${neighborhood.toLowerCase().replace(/\s+/g, '-')}/zip:${zipCode}`;
    window.open(url, '_blank');
}

// Set up event listeners when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const viewAllBtn = document.getElementById('viewAllListingsBtn');
    if (viewAllBtn) {
        viewAllBtn.addEventListener('click', viewAllListings);
    }

    // Load data
    loadNeighborhoodData();
});