from flask import Flask, render_template, jsonify, request
import json
import os

app = Flask(__name__)

def load_data():
    with open('data.json', 'r') as f:
        data = json.load(f)

    # Calculate overall scores
    for zip_code, metrics in data.items():
        metrics['overall'] = (metrics['air'] + metrics['water'] + metrics['edu'] + metrics['nypd']) / 4

    return data

SCORES = load_data()

def get_borough_from_zip(zip_code):
    zip_str = str(zip_code)
    first_three = zip_str[:3]
    if first_three in ['100', '101', '102']:
        return 'Manhattan'
    if first_three == '104':
        return 'Bronx'
    if first_three in ['112', '111']:
        return 'Brooklyn'
    if first_three in ['113', '114', '116']:
        return 'Queens'
    if first_three == '103':
        return 'Staten Island'
    return 'Unknown'

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/map')
def map_page():
    return render_template('map.html')

@app.route('/neighborhood/<zip_code>/')
def neighborhood(zip_code):
    if zip_code not in SCORES:
        return render_template('404.html'), 404
    return render_template('neighborhood.html', zip_code=zip_code)

# API endpoints
@app.route('/api/scores')
def get_scores():
    return jsonify(SCORES)

@app.route('/api/score/<zip_code>')
def get_score(zip_code):
    if zip_code in SCORES:
        return jsonify(SCORES[zip_code])
    return jsonify({'error': 'Zip code not found'}), 404

@app.route('/api/listings/<zip_code>')
def get_listings(zip_code):
    neighborhood = SCORES.get(zip_code, {}).get('neighborhood', '')
    sample_listings = [
        {
            'price': '$2,800',
            'beds': 1,
            'baths': 1,
            'sqft': 650,
            'address': f'123 Main St, {neighborhood}'
        },
        {
            'price': '$3,500',
            'beds': 2,
            'baths': 1,
            'sqft': 900,
            'address': f'456 Park Ave, {neighborhood}'
        },
        {
            'price': '$4,200',
            'beds': 2,
            'baths': 2,
            'sqft': 1100,
            'address': f'789 Broadway, {neighborhood}'
        }
    ]

    return jsonify(sample_listings)

@app.route('/api/borough/<zip_code>')
def get_borough(zip_code):
    """Return borough for a zip code"""
    return jsonify({'borough': get_borough_from_zip(zip_code)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)