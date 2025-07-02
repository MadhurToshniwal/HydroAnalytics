# constraints.py (updated for nhpmh_data)

# Example constraints per table (customize as needed)
CONSTRAINTS = {
    "river_data": {"water_level": (1000, 2000)},
    "dam_data": {"capacity": (5000, 10000)},
    "epan_data": {"some_column": (100, 200)},
    "aws_data": {"temperature": (100, 200)},
    "ars_data": {"pressure": (500, 1000)},
    "gate_data": {"status": (2, 3)},
    "nhpmh_data": {
        "batt_volt": (10.5, 15.0),       # Battery voltage range
        "data_count": (22, 24),           # Expected data points per day
        "percentage": (90.0, 100.0)       # Data reception percentage
    }
}

def check_constraints(df, table_name):
    alerts = []
    constraints = CONSTRAINTS.get(table_name, {})
    
    for column, (min_val, max_val) in constraints.items():
        if column in df.columns:
            # Handle percentage column differently (already calculated)
            if column == 'percentage':
                invalid_rows = df[df[column] < min_val]
            else:
                invalid_rows = df[(df[column] < min_val) | (df[column] > max_val)]
            
            if not invalid_rows.empty:
                alert_msg = (
                    f"Constraint violation in {table_name} for column '{column}': "
                    f"Values outside [{min_val}, {max_val}]. "
                    f"Found {len(invalid_rows)} invalid entries."
                )
                alerts.append(alert_msg)
    
    return alerts