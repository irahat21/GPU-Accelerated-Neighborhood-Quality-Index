# Data Notes

This folder contains smaller source datasets used in the Neighborhood Quality Index pipeline, along with NYC geography boundary files in [geographies](/Users/darienramdass/Documents/GitHub/Senior-Project/data/geographies).

Included in the repository:

- `2005_-_2020_Quality_Review_Ratings_20260218.csv`
- `Air_Quality_20260217.csv`
- `Drinking_Water_Quality_Distribution_Monitoring_Data_20260218.csv`
- `water_sampling_sites.csv`

Not included in the repository:

- `NYPD_Complaint_Data_Historic.csv`

The NYPD complaints file is very large and is excluded from version control to keep the repository manageable.

## Coverage Note

The project integrates datasets with different reporting periods and update cadences. For example, the education quality source used here covers `2005-2020` rather than the most recent possible school years. Because of that, the current application should be understood as a prototype and research-style neighborhood comparison tool rather than a live real-time city conditions product.
