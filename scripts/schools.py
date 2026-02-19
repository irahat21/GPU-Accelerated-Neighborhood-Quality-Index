import pandas as pd
import numpy as np
import os

# Load the data files and format data
raw_data = pd.read_csv('../raw_data/education_quality.csv')
lookup_data = pd.read_csv('../raw_data/school_locations.csv')

raw_data = raw_data[~raw_data['BN'].astype(str).str.contains('All Quality Review', case=False, na=False)]
raw_data['School_Year_numeric'] = raw_data['School_Year'].astype(str).str.split('-').str[0].astype(int)
raw_data['School_Year'] = raw_data['School_Year_numeric']


# Define rating scale
rating_scale = {
    'U/UD': 1,      # Underdeveloped
    'UPF': 2,       # Underdeveloped with Proficient Features
    'D': 3,         # Developing
    'P': 4,         # Proficient
    'WD': 5,        # Well Developed
    'O': 6,         # Outstanding
}

# List of all indicator columns
indicator_cols = ['IndicatorOverall_1', 'IndicatorOverall_2', 'IndicatorOverall_3', 'IndicatorOverall_4', 'IndicatorOverall_5']

# Also convert Overall_Rating if you want to validate later
all_rating_cols = indicator_cols + ['Overall_Rating']

# Convert all rating columns from text to numeric
for col in all_rating_cols:
    if col in raw_data.columns:
        raw_data[col] = raw_data[col].astype(str).str.strip().str.upper()
        raw_data[col] = raw_data[col].replace({
            'U': 'U/UD',
            'UD': 'U/UD',
            'NAN': np.nan,
            'NONE': np.nan,
            'No Data': np.nan,
            'NO DATA': np.nan,
            '': np.nan
        })
        raw_data[col + '_numeric'] = raw_data[col].map(rating_scale)

print("Rating conversion complete.")

# Check for any unmapped values
numeric_indicator_cols = [col + '_numeric' for col in indicator_cols]
for original_col, numeric_col in zip(indicator_cols, numeric_indicator_cols):
    unmapped = raw_data[raw_data[numeric_col].isna() & raw_data[original_col].notna()][original_col].unique()
    if len(unmapped) > 0:
        print(f"\nWARNING: Unmapped values in {original_col}: {unmapped}")

# Step 4: Calculate Synthetic Rating for each row
print("\nCalculating synthetic ratings...")

# Calculate synthetic rating (mean of non-null numeric indicators)
raw_data['Synthetic_Rating'] = raw_data[numeric_indicator_cols].mean(axis=1, skipna=True)

# Calculate completeness score
raw_data['Completeness_Score'] = raw_data[numeric_indicator_cols].notna().sum(axis=1) / len(numeric_indicator_cols)

# Validate synthetic rating against Overall_Rating for pre-2014 data
if 'Overall_Rating_numeric' in raw_data.columns:
    pre_2014 = raw_data[raw_data['School_Year'] <= 2014].copy()
    pre_2014_with_both = pre_2014[pre_2014['Overall_Rating_numeric'].notna() &
                                  pre_2014['Synthetic_Rating'].notna()]
    if len(pre_2014_with_both) > 0:
        correlation = pre_2014_with_both['Overall_Rating_numeric'].corr(pre_2014_with_both['Synthetic_Rating'])
        print(f"\nValidation: Correlation between Overall_Rating and Synthetic_Rating (pre-2014): {correlation:.3f}")

# Calculate Time Weights
print("\nCalculating time weights...")

max_year = raw_data['School_Year'].max()
decay_factor = 0.9

raw_data['Weight'] = decay_factor ** (max_year - raw_data['School_Year'])

# Calculate Weighted Grade Per School
print("\nCalculating weighted grades per school...")

# Group by BN and calculate weighted average
def calculate_weighted_grade(group):
    valid_rows = group[group['Synthetic_Rating'].notna()]

    if len(valid_rows) == 0:
        return pd.Series({
            'Final_Weighted_Grade': np.nan,
            'Average_Completeness_Score': np.nan,
            'Number_of_Years': 0,
            'Earliest_Year': np.nan,
            'Latest_Year': np.nan
        })

    # Weighted average: sum(rating * weight) / sum(weight)
    weighted_sum = (valid_rows['Synthetic_Rating'] * valid_rows['Weight']).sum()
    weight_sum = valid_rows['Weight'].sum()

    return pd.Series({
        'Final_Weighted_Grade': weighted_sum / weight_sum if weight_sum > 0 else np.nan,
        'Average_Completeness_Score': group['Completeness_Score'].mean(),
        'Number_of_Years': len(group),
        'Earliest_Year': group['School_Year'].min(),
        'Latest_Year': group['School_Year'].max()
    })

graded_schools = raw_data.groupby('BN').apply(calculate_weighted_grade).reset_index()

# Merge with Lookup Data
print("\nMerging with lookup data...")

lookup_subset = lookup_data[['location_code', 'location_name', 'X_COORDINATE', 'Y_COORDINATE', 'Location_Category_Description']].copy()

lookup_subset = lookup_subset.rename(columns={'location_code': 'BN'})
lookup_subset = lookup_subset.drop_duplicates(subset='BN', keep='first')
final_results = graded_schools.merge(lookup_subset, on='BN', how='left')

column_order = ['BN', 'location_name', 'Final_Weighted_Grade', 'Average_Completeness_Score',
                'Number_of_Years', 'Earliest_Year', 'Latest_Year',
                'X_COORDINATE', 'Y_COORDINATE', 'Location_Category_Description']
final_results = final_results[column_order]

os.makedirs("../output", exist_ok=True)
output_file = os.path.join("../output", "school_grades_final.csv")
final_results.to_csv(output_file, index=False)
print(f"\nResults exported to '{output_file}'")