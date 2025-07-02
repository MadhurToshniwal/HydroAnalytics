import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, get_data_table_name, create_db_connection, text, detect_alerts, io, re, DATA_SOURCES
from css import apply_custom_css

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, get_data_table_name, create_db_connection, text, detect_alerts, io, re, DATA_SOURCES
from css import apply_custom_css



def show_categories_tab():
    selected_date = st.date_input(
        "Select Date", 
        value=datetime.now().date(),
        key="station_date_selector"
    )
    selected_date_str = selected_date.strftime("%d/%m/%Y")
    
    button_container = st.container()
    station_tabs = st.tabs(list(DATA_SOURCES.keys()))
    
    # Add a button to load data
    with button_container:
        if st.button("🔍 Load Data", type="primary", key="load_data_button"):
            load_data = True
        else:
            load_data = False
    
    all_station_alerts = {}

    # Define highlight_alerts function at the beginning
    def highlight_alerts(row, daily_df, station_name, selected_date, df):
        # Get the original row using the current row's position
        row_position = row.name
        if row_position >= len(daily_df):
            return [''] * len(row)
            
        original_row = daily_df.iloc[row_position]
        styles = [''] * len(row)
        alert_detected = False
        constant_value_detected = False
        
        # Common checks for all stations - battery voltage
        if 'batt_volt' in original_row and pd.notnull(original_row['batt_volt']):
            try:
                batt_volt = float(original_row['batt_volt'])
                if batt_volt < 10.5:
                    # Highlight the entire row for main display
                    styles = ['background-color: #ffcccc'] * len(row)
                    alert_detected = True
                    original_row['alert_type'] = 'Low Battery (<10.5V)'
            except:
                pass
        
        # Station-specific checks
        if station_name == 'Gate':
            gate_cols = [col for col in daily_df.columns if re.match(r'^g\d+$', col)]
            for col in gate_cols:
                if col in original_row and pd.notnull(original_row[col]):
                    try:
                        if float(original_row[col]) > 0.00:
                            styles = ['background-color: #ffcccc'] * len(row)
                            alert_detected = True
                            break
                    except:
                        continue
        
        elif station_name == 'EPAN' and 'epan_water_depth' in original_row:
            try:
                current_depth = float(original_row['epan_water_depth'])
                location_id = original_row['location_id'] if 'location_id' in original_row else None
                
                # First check for constant value (highest priority)
                if location_id:
                    # Get dates to check (previous 3 days + today)
                    dates_to_check = []
                    days_back = 0
                    while len(dates_to_check) < 4:  # We need 4 days total (today + 3 previous)
                        check_date = selected_date - timedelta(days=days_back)
                        check_date_str = check_date.strftime('%d/%m/%Y')
                        
                        # Filter for this location and date
                        prev_day_df = df[
                            (df['majority_date'] == check_date_str) & 
                            (df['location_id'] == location_id)
                        ]
                        
                        if not prev_day_df.empty and 'epan_water_depth' in prev_day_df.columns:
                            # Take the most recent reading from that day
                            prev_depth = float(prev_day_df['epan_water_depth'].iloc[0])
                            dates_to_check.append((check_date_str, prev_depth))
                        
                        days_back += 1
                        if days_back > 10:  # Safety limit
                            break
                    
                    # If we have 4 days of data, check if all values are equal
                    if len(dates_to_check) == 4:
                        all_equal = all(d[1] == current_depth for d in dates_to_check)
                        if all_equal:
                            constant_value_detected = True
                            original_row['alert_type'] = 'Constant Water Depth (4 days)'
                            original_row['constant_value_days'] = [d[0] for d in dates_to_check]
                            if 'epan_water_depth' in row.index:
                                depth_index = row.index.get_loc('epan_water_depth')
                                styles[depth_index] = 'background-color: #add8e6; font-weight: bold'  # Light blue
                        
                # Only check other constraints if not a constant value
                if not constant_value_detected:
                    # Check for water depth ≤50 or ≥200
                    if current_depth <= 50 or current_depth >= 200:
                        styles = ['background-color: #ffcccc'] * len(row)
                        alert_detected = True
                        original_row['alert_type'] = f'Water Depth {"≤50" if current_depth <=50 else "≥200"}'
                    
                    # Previous day difference check (go back up to 10 days if needed)
                    if location_id:
                        prev_depth = None
                        days_back = 1
                        comparison_date = None
                        
                        # Check up to 10 previous days for data
                        while days_back <= 10 and prev_depth is None:
                            check_date = selected_date - timedelta(days=days_back)
                            check_date_str = check_date.strftime('%d/%m/%Y')
                            
                            # Filter for this location and date
                            prev_day_df = df[
                                (df['majority_date'] == check_date_str) & 
                                (df['location_id'] == location_id)
                            ]
                            
                            if not prev_day_df.empty and 'epan_water_depth' in prev_day_df.columns:
                                # Take the most recent reading from that day
                                prev_depth = float(prev_day_df['epan_water_depth'].iloc[0])
                                comparison_date = check_date_str
                            
                            days_back += 1
                        
                        # If we found previous data, check the difference
                        if prev_depth is not None:
                            if abs(current_depth - prev_depth) > 15:
                                styles = ['background-color: #ffcccc'] * len(row)
                                if 'epan_water_depth' in row.index:
                                    depth_index = row.index.get_loc('epan_water_depth')
                                    styles[depth_index] = 'background-color: #ff9999; font-weight: bold'
                                alert_detected = True
                                original_row['alert_type'] = f'Depth Change >15 (vs {comparison_date})'
                                original_row['previous_depth'] = prev_depth
                                original_row['depth_difference'] = abs(current_depth - prev_depth)
            except Exception as e:
                st.error(f"Error processing EPAN data: {str(e)}")
        
        elif station_name == 'AWS':
            # Initialize alert type list if it doesn't exist
            if 'alert_type' not in original_row:
                original_row['alert_type'] = []
            elif isinstance(original_row['alert_type'], str):
                original_row['alert_type'] = [original_row['alert_type']]
            
            # 1. Check for zero values in specified columns
            zero_value_columns = ['atmospheric_pressure', 'temperature', 'humidity', 'solar_radiation', 'wind_speed']
            for col in zero_value_columns:
                if col in original_row and pd.notnull(original_row[col]):
                    try:
                        if float(original_row[col]) == 0:
                            styles = ['background-color: #ffcccc'] * len(row)
                            alert_detected = True
                            original_row['alert_type'].append(f'{col.capitalize().replace("_", " ")} is 0')
                            # Highlight the specific zero value column
                            if col in row.index:
                                col_index = row.index.get_loc(col)
                                styles[col_index] = 'background-color: #ff9999; font-weight: bold'
                    except:
                        pass
            
            # 2. Check for rain values > 100 (updated constraint)
            rain_columns = ['hourly_rain', 'daily_rain']
            rain_alert = False
            rain_alert_cols = []
            for col in rain_columns:
                if col in original_row and pd.notnull(original_row[col]):
                    try:
                        rain_value = float(original_row[col])
                        if rain_value > 100:
                            styles = ['background-color: #ffcccc'] * len(row)
                            alert_detected = True
                            rain_alert = True
                            rain_alert_cols.append(col)
                            # Highlight the specific rain column
                            if col in row.index:
                                col_index = row.index.get_loc(col)
                                styles[col_index] = 'background-color: #ff9999; font-weight: bold'
                    except:
                        pass
            
            if rain_alert:
                original_row['alert_type'].append('Rainfall > 100mm')
                original_row['rain_alert_columns'] = rain_alert_cols
            
            # 3. Check for wind speed > 30
            if 'wind_speed' in original_row and pd.notnull(original_row['wind_speed']):
                try:
                    wind_speed = float(original_row['wind_speed'])
                    if wind_speed > 30:
                        styles = ['background-color: #ffcccc'] * len(row)
                        alert_detected = True
                        original_row['alert_type'].append('High Wind Speed (>30)')
                        # Highlight the wind speed column
                        if 'wind_speed' in row.index:
                            ws_index = row.index.get_loc('wind_speed')
                            styles[ws_index] = 'background-color: #ff9999; font-weight: bold'
                except:
                    pass
            
            # 4. Existing AWS checks
            if 'rainfall' in original_row and pd.notnull(original_row['rainfall']):
                try:
                    if float(original_row['rainfall']) > 50:
                        styles = ['background-color: #ffcccc'] * len(row)
                        alert_detected = True
                        original_row['alert_type'].append('High Rainfall (>50mm)')
                except:
                    pass
            
            if 'temperature' in original_row and pd.notnull(original_row['temperature']):
                try:
                    if float(original_row['temperature']) > 40:
                        styles = ['background-color: #ffcccc'] * len(row)
                        alert_detected = True
                        original_row['alert_type'].append('High Temperature (>40)')
                except:
                    pass
            
            # Convert alert_type back to string if it was modified
            if isinstance(original_row['alert_type'], list):
                original_row['alert_type'] = ', '.join(original_row['alert_type'])
        
        # River/Dam station level difference check with 10-day lookback
        elif (station_name in ['River', 'Dam'] and 
            'level_mtr' in original_row and 
            'location_id' in original_row):
            try:
                current_level = float(original_row['level_mtr'])
                location_id = original_row['location_id']
                
                # Initialize variables
                prev_level = None
                days_checked = 0
                comparison_date = None
                
                # Check up to 10 previous days for data
                while days_checked < 10 and prev_level is None:
                    check_date = selected_date - timedelta(days=days_checked + 1)
                    check_date_str = check_date.strftime('%d/%m/%Y')
                    
                    # Filter for this location and date
                    prev_day_df = df[
                        (df['majority_date'] == check_date_str) & 
                        (df['location_id'] == location_id)
                    ]
                    
                    if not prev_day_df.empty and 'level_mtr' in prev_day_df.columns:
                        # Take the most recent reading from that day
                        prev_level = float(prev_day_df['level_mtr'].iloc[0])
                        comparison_date = check_date_str
                        break
                        
                    days_checked += 1
                
                # If we found previous data, check the difference
                if prev_level is not None:
                    level_diff = abs(current_level - prev_level)
                    if level_diff > 1:
                        styles = ['background-color: #ffcccc'] * len(row)
                        if 'level_mtr' in row.index:
                            level_mtr_index = row.index.get_loc('level_mtr')
                            styles[level_mtr_index] = 'background-color: #ff9999; font-weight: bold'
                        alert_detected = True
                        original_row['alert_type'] = f'Level Change >1m (vs {comparison_date})'
                        original_row['previous_level'] = prev_level
                        original_row['level_difference'] = level_diff
            except:
                pass
        
        if alert_detected or constant_value_detected:
            alert_rows.append(original_row)
        
        return styles
    
    # Only load and display data if the button was clicked
    if load_data:
        # First load AWS data to get daily_rain values for EPAN alerts
        aws_df = pd.DataFrame()
        if 'AWS' in DATA_SOURCES:
            with st.spinner("Loading AWS data for rain information..."):
                aws_df = load_station_data('AWS')
                if not aws_df.empty:
                    # Process AWS data to get daily_rain values
                    aws_df['last_updated_dt'] = pd.to_datetime(aws_df['last_updated'], format='%d/%m/%Y %H:%M', errors='coerce')
                    aws_df = aws_df[aws_df['last_updated_dt'].notna()]
                    aws_df['last_updated_date'] = aws_df['last_updated_dt'].dt.strftime('%d/%m/%Y')
                    aws_df['data_date_str'] = pd.to_datetime(aws_df['data_date']).dt.strftime('%d/%m/%Y')
                    
                    # Group by both data_date and data_time to find majority last_updated_date
                    aws_time_groups = aws_df.groupby(['data_date_str', 'data_time'])['last_updated_date'].agg(
                        lambda x: x.mode()[0] if not x.mode().empty else None
                    ).reset_index()
                    aws_time_groups.rename(columns={'last_updated_date': 'majority_date'}, inplace=True)
                    
                    # Merge back with original dataframe
                    aws_df = aws_df.merge(aws_time_groups, on=['data_date_str', 'data_time'])
                    
                    # Filter to selected date
                    aws_daily_df = aws_df[aws_df['majority_date'] == selected_date_str]
        
        for idx, (station_name, table_name) in enumerate(DATA_SOURCES.items()):
            with station_tabs[idx]:
                with st.spinner(f"Loading {station_name} data..."):
                    df = load_station_data(station_name)
                    
                    if not df.empty:
                        st.subheader(f"{station_name} Station")
                        
                        if 'project_name' in df.columns:
                            projects = df['project_name'].unique()
                            selected_project = st.selectbox(
                                "Select Project",
                                options=["All Projects"] + list(projects),
                                key=f"proj_{station_name}_{idx}"
                            )
                        
                        if 'data_time' in df.columns and 'last_updated' in df.columns and 'data_date' in df.columns:
                            # Convert last_updated to datetime and extract date
                            df['last_updated_dt'] = pd.to_datetime(df['last_updated'], format='%d/%m/%Y %H:%M', errors='coerce')
                            df = df[df['last_updated_dt'].notna()]
                            df['last_updated_date'] = df['last_updated_dt'].dt.strftime('%d/%m/%Y')
                            
                            # Convert data_date to string format for comparison
                            df['data_date_str'] = pd.to_datetime(df['data_date']).dt.strftime('%d/%m/%Y')
                            
                            # Group by both data_date and data_time to find majority last_updated_date
                            time_groups = df.groupby(['data_date_str', 'data_time'])['last_updated_date'].agg(
                                lambda x: x.mode()[0] if not x.mode().empty else None
                            ).reset_index()
                            time_groups.rename(columns={'last_updated_date': 'majority_date'}, inplace=True)
                            
                            # Merge back with original dataframe
                            df = df.merge(time_groups, on=['data_date_str', 'data_time'])
                            
                            # Filter to show all rows where the majority_date matches selected date
                            daily_df = df[df['majority_date'] == selected_date_str]
                            
                            if selected_project != "All Projects":
                                daily_df = daily_df[daily_df['project_name'] == selected_project]
                            
                            st.info(f"Showing {len(daily_df)} rows from {selected_date_str}")
                            
                            if not daily_df.empty:
                                # Data Display
                                st.markdown("### 📋 Current Readings")
                                
                                # Initialize alerts for this station and date
                                alert_rows = []
                                constant_value_rows = []  # For EPAN constant value detection
                                
                                # Create a copy of the dataframe for display (excluding specific columns)
                                columns_to_exclude = ['data_date', 'data_time', 'last_updated_date', 'majority_date', 
                                                   'last_updated_dt', 'data_date_str']
                                display_df = daily_df.drop(columns=[col for col in columns_to_exclude if col in daily_df.columns])
                                
                                # Reset index to ensure proper alignment
                                display_df = display_df.reset_index(drop=True)
                                daily_df = daily_df.reset_index(drop=True)
                                
                                # Apply highlighting with the properly defined function
                                styled_df = display_df.style.apply(
                                    lambda x: highlight_alerts(x, daily_df, station_name, selected_date, df), 
                                    axis=1
                                )
                                st.dataframe(
                                    styled_df,
                                    use_container_width=True,
                                    height=min(400, len(display_df) * 35 + 50))
                                
                                # Add download button for current readings
                                csv = display_df.to_csv(index=False).encode('utf-8')
                                st.download_button(
                                    label="Download Current Readings",
                                    data=csv,
                                    file_name=f"{station_name}current_readings{selected_date_str.replace('/', '-')}.csv",
                                    mime='text/csv',
                                    key=f"download_current_{station_name}_{idx}",
                                    type="primary",
                                    help=f"Download current readings for {station_name} on {selected_date_str}"
                                )
                                
                                # Show alerts for this specific date and station
                                if alert_rows:
                                    st.markdown("---")
                                    st.subheader(f"⚠ Alerts for {selected_date_str}")
                                    
                                    # Create columns for alert count and details
                                    col1, col2 = st.columns([1, 3])
                                    
                                    with col1:
                                        st.metric(
                                            label="Total Alerts",
                                            value=len(alert_rows),
                                            help=f"Number of alert records found for {station_name} on {selected_date_str}"
                                        )
                                    
                                    with col2:
                                        # For River/Dam stations, add level difference explanation
                                        if station_name in ['River', 'Dam'] and any('level_mtr' in row for row in alert_rows):
                                            st.info("""
                                                ℹ Level alerts are triggered when current level_mtr differs by 
                                                more than ±1 meter from the same location's value on any of the 
                                                previous 10 days (checks each day until data is found).
                                            """)
                                        # For EPAN stations, add water depth difference explanation
                                        elif station_name == 'EPAN' and any('epan_water_depth' in row for row in alert_rows):
                                            st.info("""
                                                ℹ EPAN alerts are triggered when:
                                                - Low Battery (<10.5V)
                                                - Water depth ≤50 or ≥200
                                                - Depth differs by more than ±15 from previous available day
                                                - Constant water depth for 4 consecutive days (highest priority)
                                                System checks up to 10 previous days if needed
                                            """)
                                        # For AWS stations
                                        elif station_name == 'AWS':
                                            st.info("""
                                                ℹ AWS alerts are triggered when:
                                                - Atmospheric pressure, temperature, humidity, solar radiation or wind speed is 0
                                                - Hourly or daily rain > 100mm
                                                - Rainfall > 50mm
                                                - Wind speed > 30
                                                - Temperature > 40
                                            """)
                                        # For battery voltage alerts
                                        elif any('Low Battery' in str(row.get('alert_type', '')) for row in alert_rows):
                                            st.info("""
                                                ℹ Battery alerts are triggered when voltage <10.5V
                                            """)
                                    
                                    alert_df = pd.DataFrame(alert_rows)
                                    
                                    # For EPAN alerts, add daily_rain column from AWS data if available
                                    if station_name == 'EPAN' and not aws_daily_df.empty:
                                        # Get unique project names from EPAN alerts
                                        epan_projects = alert_df['project_name'].unique()
                                        
                                        # Create a mapping of project to daily_rain
                                        project_rain_map = {}
                                        for project in epan_projects:
                                            # Find matching AWS records for this project
                                            project_aws = aws_daily_df[aws_daily_df['project_name'] == project]
                                            if not project_aws.empty:
                                                # Take the most recent daily_rain value
                                                latest_aws = project_aws.sort_values('last_updated_dt', ascending=False).iloc[0]
                                                rain_value = latest_aws.get('daily_rain', 0)
                                                project_rain_map[project] = rain_value
                                            else:
                                                project_rain_map[project] = 0
                                        
                                        # Add daily_rain column to alert_df
                                        alert_df['daily_rain'] = alert_df['project_name'].map(project_rain_map)
                                        
                                        # Replace 0 values with '-' for display
                                        alert_df['daily_rain_display'] = alert_df['daily_rain'].apply(
                                            lambda x: '-' if x == 0 else x
                                        )
                                    
                                    # Define the desired column order for alerts based on station type
                                    if station_name == 'EPAN':
                                        # Specific column order for EPAN station with daily_rain after depth_difference
                                        epan_base_columns = [
                                            'project_name', 'sr_no', 'location_name', 'location_id',
                                            'last_updated', 'batt_volt', 'epan_water_depth', 
                                            'previous_depth', 'depth_difference', 'daily_rain_display',
                                            'constant_value_days', 'alert_type'
                                        ]
                                        
                                        # Get all columns that exist in the dataframe
                                        existing_columns = [col for col in epan_base_columns if col in alert_df.columns]
                                        
                                        # Get remaining columns not in our base list
                                        other_columns = [col for col in alert_df.columns if col not in epan_base_columns and col not in columns_to_exclude]
                                        
                                        # Create the final column order
                                        final_columns = existing_columns + other_columns
                                    else:
                                        # Default column order for other stations
                                        base_columns = [
                                            'project_name', 'sr_no', 'location_name', 'location_id',
                                            'last_updated', 'batt_volt', 'level_mtr', 'previous_level',
                                            'level_difference', 'alert_type'
                                        ]
                                        
                                        # Get all columns that exist in the dataframe
                                        existing_columns = [col for col in base_columns if col in alert_df.columns]
                                        
                                        # Get remaining columns not in our base list
                                        other_columns = [col for col in alert_df.columns if col not in base_columns and col not in columns_to_exclude]
                                        
                                        # Create the final column order
                                        final_columns = existing_columns + other_columns
                                    
                                    # Reorder the alert dataframe
                                    alert_display_df = alert_df[final_columns]
                                    
                                    # Rename daily_rain_display to daily_rain for better column name
                                    if 'daily_rain_display' in alert_display_df.columns:
                                        alert_display_df = alert_display_df.rename(columns={'daily_rain_display': 'daily_rain (mm)'})
                                    
                                    # Remove the last_updated_dt column if it exists
                                    if 'last_updated_dt' in alert_display_df.columns:
                                        alert_display_df = alert_display_df.drop(columns=['last_updated_dt'])
                                    
                                    # Store alerts data for this station
                                    all_station_alerts[station_name] = alert_display_df
                                    
                                    # Custom highlighting for alert dataframe
                                    def highlight_alert_rows(row):
                                        styles = ['background-color: #ffebee'] * len(row)
                                        try:
                                            # Safely check alert_type
                                            alert_type = str(row.get('alert_type', ''))
                                            
                                            # Highlight battery voltage in light green for low battery alerts
                                            if 'Low Battery' in alert_type and 'batt_volt' in row.index:
                                                batt_index = row.index.get_loc('batt_volt')
                                                styles[batt_index] = 'background-color: #90ee90; font-weight: bold'
                                            
                                            # Highlight EPAN water depth
                                            if station_name == 'EPAN' and 'epan_water_depth' in row:
                                                depth_index = row.index.get_loc('epan_water_depth')
                                                if 'Constant Water Depth' in alert_type:
                                                    styles[depth_index] = 'background-color: #add8e6; font-weight: bold'
                                                elif 'Depth Change' in alert_type:
                                                    styles[depth_index] = 'background-color: #ff9999; font-weight: bold'
                                                elif 'Water Depth' in alert_type:
                                                    styles[depth_index] = 'background-color: #ff9999; font-weight: bold'
                                            
                                            # River/Dam level changes
                                            if (station_name in ['River', 'Dam'] and 
                                                'level_mtr' in row and 
                                                'Level Change' in alert_type):
                                                level_mtr_index = row.index.get_loc('level_mtr')
                                                styles[level_mtr_index] = 'background-color: #ff9999; font-weight: bold'
                                            
                                            # Highlight AWS rain columns in pink when >100mm
                                            if station_name == 'AWS' and 'Rainfall > 100mm' in alert_type:
                                                rain_cols = ['hourly_rain', 'daily_rain']
                                                for rain_col in rain_cols:
                                                    if rain_col in row.index and pd.notnull(row[rain_col]):
                                                        try:
                                                            if float(row[rain_col]) > 100:
                                                                col_index = row.index.get_loc(rain_col)
                                                                styles[col_index] = 'background-color: #ffc0cb; font-weight: bold'
                                                        except:
                                                            pass
                                            
                                            # Highlight zero value columns in AWS
                                            if station_name == 'AWS':
                                                zero_cols = ['atmospheric_pressure', 'temperature', 'humidity', 
                                                            'solar_radiation', 'wind_speed']
                                                for col in zero_cols:
                                                    if col in row.index and str(row[col]) == '0':
                                                        col_index = row.index.get_loc(col)
                                                        styles[col_index] = 'background-color: #ff9999; font-weight: bold'
                                                
                                            # Highlight daily_rain in EPAN alerts if > 0
                                            if station_name == 'EPAN' and 'daily_rain (mm)' in row.index and row['daily_rain (mm)'] != '-':
                                                rain_index = row.index.get_loc('daily_rain (mm)')
                                                styles[rain_index] = 'background-color: #90ee90; font-weight: bold'
                                                
                                        except:
                                            pass
                                        return styles
                                    
                                    st.dataframe(
                                        alert_display_df.style.apply(highlight_alert_rows, axis=1),
                                        use_container_width=True,
                                        height=min(400, len(alert_rows) * 35 + 50))
                                    
                                    # Add download button for alerts
                                    alert_csv = alert_display_df.to_csv(index=False).encode('utf-8')
                                    st.download_button(
                                        label="Download Alerts Data",
                                        data=alert_csv,
                                        file_name=f"{station_name}alerts{selected_date_str.replace('/', '-')}.csv",
                                        mime='text/csv',
                                        key=f"download_alerts_{station_name}_{idx}",
                                        type="primary",
                                        help=f"Download alert data for {station_name} on {selected_date_str}"
                                    )
                                else:
                                    st.success(f"✅ No alerts detected for {selected_date_str}")
                            
                            else:
                                st.warning(f"No data available where majority last_updated date is {selected_date_str}")
                        else:
                            st.warning("Required columns (data_date, data_time or last_updated) not found in data")
                    else:
                        st.warning(f"No data available for {station_name} station")
            
        # Add "Download All Alerts" button at the top right
        if all_station_alerts:
            with button_container:
                # Create a function to generate the combined CSV
                def generate_combined_alerts_csv():
                    output = io.StringIO()
                    
                    for station_name, alert_df in all_station_alerts.items():
                        # Write station name as header
                        output.write(f"{station_name} Station Alerts\n")
                        
                        # Write the dataframe
                        alert_df.to_csv(output, index=False)
                        
                        # Add two empty rows between stations
                        output.write("\n\n")
                    
                    return output.getvalue().encode('utf-8')
                
                # Place the button at the top right
                st.download_button(
                    label="📥 Download All Alerts",
                    data=generate_combined_alerts_csv(),
                    file_name=f"all_stations_alerts_{selected_date_str.replace('/', '-')}.csv",
                    mime='text/csv',
                    key="download_all_alerts",
                    type="primary",
                    help="Download alerts data for all stations in a single CSV file"
                )
    else:
        st.info("Please click the 'Load Data' button to view station data and alerts")