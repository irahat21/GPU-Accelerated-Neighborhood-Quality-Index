import os
import pandas as pd

DIR = "raw_data"
TOKEN = "U29jcmF0YS0td2VraWNrYXNz0"

DATASETS = {
    "air_quality": "https://data.cityofnewyork.us/api/v3/views/c3uy-2p5r/export.csv",
    "drinking_water_quality": "https://data.cityofnewyork.us/api/v3/views/bkwf-xfky/export.csv",
    "nypd_complaints_data": "https://data.cityofnewyork.us/api/v3/views/qgea-i56i/export.csv",
    "education_quality": "https://data.cityofnewyork.us/api/v3/views/3wfy-sn5g/export.csv",
    "school_locations": "https://data.cityofnewyork.us/api/v3/views/wg9x-4ke6/export.csv",
    "sampling_sites": "https://data.cityofnewyork.us/api/views/bkwf-xfky/files/e93e4856-95f7-48d4-b4c0-fa54989cdbfc?download=true&filename=OpenData_Distribution_Water_Quality_Sampling_Sites_Updated_2021-0618.xlsx",
}

os.makedirs(DIR, exist_ok=True)

for name, url in DATASETS.items():
    output_file = os.path.join(DIR, f"{name}.csv")
    export_url = url

    if os.path.exists(output_file):
        continue

    os.system(
        f'curl -L -s -H "X-App-Token: {TOKEN}" "{export_url}" -o "{output_file}"'
    )

    if export_url.endswith(".xlsx"):
        df = pd.read_excel(output_file)
        df.to_csv(output_file, index=False)