import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, px, DATA_SOURCES, re, go, io, fetch_data
from css import apply_custom_css


def show_custom_tab():
    st.subheader("🔍 Advanced Data Explorer")
    st.markdown("---")

    # --------------------------- FILTERS SECTION ---------------------------
    with st.container(border=True):
        st.markdown("### 🔎 Filter Parameters")
        
        # Date Range Selection Options
        date_range_option = st.radio(
            "Select Date Range",
            options=["Custom Date Range", "Last 7 Days", "Last 15 Days"],
            horizontal=True,
            key="date_range_option"
        )
        
        # Date Range - Show different inputs based on selection
        if date_range_option == "Custom Date Range":
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input(
                    "Start Date", 
                    value=datetime.now() - timedelta(days=30),
                    help="Select start date for data retrieval",
                    key="start_date_filter"
                )
            with col2:
                end_date = st.date_input(
                    "End Date", 
                    value=datetime.now(),
                    help="Select end date for data retrieval",
                    key="end_date_filter"
                )
        else:
            # For "Last X Days" options, calculate the date range
            days = 7 if date_range_option == "Last 7 Days" else 15
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days-1)
            
            # Display the calculated date range
            st.info(f"Showing data for {date_range_option}: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Station Type Selection
        station_options = ["All Stations"] + list(DATA_SOURCES.keys())
        selected_station = st.selectbox(
            "Station Type",
            options=station_options,
            index=0,
            help="Select station type to filter",
            key="station_type_select"
        )

        # Project Selection
        project_options = ["All Projects"]
        filtered_df = pd.DataFrame()
        
        if selected_station != "All Stations":
            filtered_df = load_station_data(selected_station)
            if 'project_name' in filtered_df.columns:
                project_options += filtered_df['project_name'].astype(str).unique().tolist()
        
        selected_project = st.selectbox(
            "Project Name",
            options=project_options,
            index=0,
            help="Select project to filter",
            key=f"project_select_{selected_station}"
        )
        
        # Location Selection - Combined ID and Name
        location_options = []

        if selected_station == "All Stations":
            # Combine locations from all stations (with project filter)
            for station in DATA_SOURCES.keys():
                data = load_station_data(station)
                if selected_project != "All Projects":
                    data = data[data['project_name'] == selected_project]
                
                # Check if both ID and name columns exist
                if 'location_id' in data.columns and 'location_name' in data.columns:
                    # Create combined display and use ID as value
                    for _, row in data.drop_duplicates(['location_id', 'location_name']).iterrows():
                        display_text = f"{row['location_id']} ({row['location_name']})"
                        location_options.append((display_text, row['location_id']))
        else:
            # Get locations from filtered data
            if not filtered_df.empty and 'location_id' in filtered_df.columns and 'location_name' in filtered_df.columns:
                if selected_project != "All Projects":
                    filtered_df = filtered_df[filtered_df['project_name'] == selected_project]
                
                # Create combined display and use ID as value
                for _, row in filtered_df.drop_duplicates(['location_id', 'location_name']).iterrows():
                    display_text = f"{row['location_id']} ({row['location_name']})"
                    location_options.append((display_text, row['location_id']))
        
        # Remove duplicates and sort by location ID
        location_options = sorted(list(set(location_options)), key=lambda x: x[1])
        
        # Create selectbox with display text but store location_id as value
        selected_location = None
        if location_options:
            selected_location_display = st.selectbox(
                "Select Location",
                options=[opt[0] for opt in location_options],
                index=0,
                help="Select location to analyze (shows as ID with Name)",
                key=f"loc_sel_{selected_station[:3]}_{selected_project[:4]}"
            )
            # Get the actual location_id from the selected display text
            selected_location = next((opt[1] for opt in location_options if opt[0] == selected_location_display), None)
        else:
            st.warning("No locations found for selected filters")

    # --------------------------- DATA FETCHING AND ALERTS ---------------------------
    if st.button("🚀 Execute Search", type="primary") and selected_location:
        results = {}
        total_records = 0
        all_alerts = []
        all_alert_data = []  # To store all alert data for CSV download
        
        with st.status("🔍 Scanning data sources...", expanded=True) as status:
            try:
                stations_to_search = []
                if selected_station == "All Stations":
                    stations_to_search = list(DATA_SOURCES.items())
                else:
                    stations_to_search = [(selected_station, DATA_SOURCES[selected_station])]
                
                progress_bar = st.progress(0, text="Initializing search...")
                
                for idx, (display_name, table_name) in enumerate(stations_to_search):
                    try:
                        progress_bar.progress(
                            (idx+1)/len(stations_to_search), 
                            text=f"Searching {display_name} station..."
                        )
                        
                        # Fetch ALL data without date filtering initially
                        full_station_df = fetch_data(
                            table_name=table_name,
                            date_column='data_date'
                        )
                        
                        # Create a copy for the date filtering and display
                        filtered_df = full_station_df.copy()
                        
                        if not filtered_df.empty:
                            # Convert last_updated to datetime
                            if 'last_updated' in filtered_df.columns:
                                filtered_df['last_updated_dt'] = pd.to_datetime(
                                    filtered_df['last_updated'], 
                                    format='%d/%m/%Y %H:%M', 
                                    errors='coerce'
                                )
                                
                                # Drop rows with invalid dates
                                filtered_df = filtered_df[filtered_df['last_updated_dt'].notna()]
                                
                                # Convert filter dates to datetime for comparison
                                start_dt = pd.to_datetime(start_date)
                                end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                                
                                # Filter based on last_updated_dt
                                filtered_df = filtered_df[
                                    (filtered_df['last_updated_dt'] >= start_dt) & 
                                    (filtered_df['last_updated_dt'] < end_dt)
                                ]
                            
                            # Apply project filter
                            if selected_project != "All Projects" and 'project_name' in filtered_df.columns:
                                filtered_df = filtered_df[filtered_df['project_name'] == selected_project]
                                full_station_df = full_station_df[full_station_df['project_name'] == selected_project]
                            
                            # Apply location filter using location_id
                            if 'location_id' in filtered_df.columns:
                                filtered_df = filtered_df[filtered_df['location_id'] == selected_location]
                                full_station_df = full_station_df[full_station_df['location_id'] == selected_location]
                            
                            if not filtered_df.empty:
                                # Remove temporary columns before displaying
                                filtered_df = filtered_df.drop(columns=['last_updated_dt'], errors='ignore')
                                
                                # Initialize alerts list for this station
                                station_alerts = []
                                
                                # Check for alerts in the data
                                for _, row in filtered_df.iterrows():
                                    alert_detected = False
                                    alert_info = {
                                        'station': display_name,
                                        'location': selected_location,
                                        'project': selected_project if selected_project != "All Projects" else "All",
                                        'timestamp': row.get('last_updated', ''),
                                        'alert_type': '',
                                        'alert_details': {}
                                    }
                                    
                                    # Common checks for all stations - battery voltage
                                    if 'batt_volt' in row and pd.notnull(row['batt_volt']):
                                        try:
                                            batt_volt = float(row['batt_volt'])
                                            if batt_volt < 10.5:
                                                # Store battery voltage but don't set alert yet for EPAN
                                                alert_info['alert_details']['battery_voltage'] = batt_volt
                                        except:
                                            pass
                                    
                                    # Station-specific checks
                                    if display_name == 'Gate':
                                        gate_cols = [col for col in filtered_df.columns if re.match(r'^g\d+$', col)]
                                        for col in gate_cols:
                                            if col in row and pd.notnull(row[col]):
                                                try:
                                                    if float(row[col]) > 0.00:
                                                        alert_detected = True
                                                        alert_info['alert_type'] = 'Gate Opening Detected'
                                                        alert_info['alert_details']['gate_column'] = col
                                                        alert_info['alert_details']['gate_value'] = float(row[col])
                                                        break
                                                except:
                                                    continue
                                    
                                    elif display_name == 'EPAN' and 'epan_water_depth' in row:
                                        try:
                                            current_depth = float(row['epan_water_depth'])
                                            location_id = row['location_id'] if 'location_id' in row else None
                                            
                                            # Priority 1: Constant Water Depth (highest priority)
                                            if location_id:
                                                # Get dates to check (previous 3 days + today)
                                                current_date = pd.to_datetime(row['last_updated'], format='%d/%m/%Y %H:%M', errors='coerce')
                                                if pd.isna(current_date):
                                                    continue
                                                    
                                                dates_to_check = []
                                                # We need 4 consecutive days of data
                                                for days_back in range(0, 4):
                                                    check_date = current_date - timedelta(days=days_back)
                                                    check_date_str = check_date.strftime('%d/%m/%Y')
                                                    
                                                    # Filter for this location and date in full_station_df
                                                    prev_day_df = full_station_df[
                                                        (full_station_df['last_updated'].str.startswith(check_date_str)) & 
                                                        (full_station_df['location_id'] == location_id)
                                                    ]
                                                    
                                                    if not prev_day_df.empty and 'epan_water_depth' in prev_day_df.columns:
                                                        # Take the most recent reading from that day
                                                        prev_depth = float(prev_day_df['epan_water_depth'].iloc[0])
                                                        dates_to_check.append((check_date_str, prev_depth))
                                                    else:
                                                        # If any day is missing, break early
                                                        break
                                                
                                                # If we have 4 consecutive days of data, check if all values are equal
                                                if len(dates_to_check) == 4:
                                                    all_equal = all(d[1] == current_depth for d in dates_to_check)
                                                    if all_equal:
                                                        alert_detected = True
                                                        alert_info['alert_type'] = 'Constant Water Depth (4 days)'
                                                        alert_info['alert_details']['constant_value_days'] = [d[0] for d in dates_to_check]
                                                        alert_info['alert_details']['current_depth'] = current_depth
                                            
                                            # Priority 2: Depth Change (if no constant alert)
                                            if not alert_detected and location_id:
                                                prev_depth = None
                                                days_back = 1
                                                comparison_date = None
                                                
                                                # Check up to 10 previous days for data
                                                while days_back <= 10 and prev_depth is None:
                                                    check_date = current_date - timedelta(days=days_back)
                                                    if pd.isna(check_date):
                                                        break
                                                    check_date_str = check_date.strftime('%d/%m/%Y')
                                                    
                                                    # Filter for this location and date in full_station_df
                                                    prev_day_df = full_station_df[
                                                        (full_station_df['last_updated'].str.startswith(check_date_str)) & 
                                                        (full_station_df['location_id'] == location_id)
                                                    ]
                                                    
                                                    if not prev_day_df.empty and 'epan_water_depth' in prev_day_df.columns:
                                                        # Take the most recent reading from that day
                                                        prev_depth = float(prev_day_df['epan_water_depth'].iloc[0])
                                                        comparison_date = check_date_str
                                                    
                                                    days_back += 1
                                                
                                                # If we found previous data, check the difference
                                                if prev_depth is not None:
                                                    if abs(current_depth - prev_depth) > 15:
                                                        alert_detected = True
                                                        alert_info['alert_type'] = f'Depth Change >15 (vs {comparison_date})'
                                                        alert_info['alert_details']['current_depth'] = current_depth
                                                        alert_info['alert_details']['previous_depth'] = prev_depth
                                                        alert_info['alert_details']['depth_difference'] = abs(current_depth - prev_depth)
                                            
                                            # Priority 3: Low Battery (if no water depth alerts)
                                            if not alert_detected and 'battery_voltage' in alert_info['alert_details']:
                                                batt_volt = alert_info['alert_details']['battery_voltage']
                                                if batt_volt < 10.5:
                                                    alert_detected = True
                                                    alert_info['alert_type'] = 'Low Battery (<10.5V)'
                                            
                                            # Priority 4: Water Depth Threshold (lowest priority)
                                            if not alert_detected:
                                                if current_depth <= 50 or current_depth >= 200:
                                                    alert_detected = True
                                                    alert_info['alert_type'] = f'Water Depth {"≤50" if current_depth <=50 else "≥200"}'
                                                    alert_info['alert_details']['current_depth'] = current_depth
                                        
                                        except Exception as e:
                                            st.error(f"Error processing EPAN data: {str(e)}")
                                    
                                    elif display_name == 'AWS':
                                        # Initialize alert type list
                                        alert_types = []
                                        
                                        # 1. Check for zero values in specified columns
                                        zero_value_columns = ['atmospheric_pressure', 'temperature', 'humidity', 'solar_radiation', 'wind_speed']
                                        for col in zero_value_columns:
                                            if col in row and pd.notnull(row[col]):
                                                try:
                                                    if float(row[col]) == 0:
                                                        alert_types.append(f'{col.capitalize().replace("_", " ")} is 0')
                                                        alert_info['alert_details'][col] = 0
                                                except:
                                                    pass
                                        
                                        # 2. Check for rain values > 100 (updated constraint)
                                        rain_columns = ['hourly_rain', 'daily_rain']
                                        rain_alert_cols = []
                                        for col in rain_columns:
                                            if col in row and pd.notnull(row[col]):
                                                try:
                                                    rain_value = float(row[col])
                                                    if rain_value > 100:
                                                        rain_alert_cols.append(col)
                                                        alert_info['alert_details'][col] = rain_value
                                                except:
                                                    pass
                                        
                                        if rain_alert_cols:
                                            alert_types.append('Rainfall > 100mm')
                                        
                                        # 3. Check for wind speed > 30
                                        if 'wind_speed' in row and pd.notnull(row['wind_speed']):
                                            try:
                                                wind_speed = float(row['wind_speed'])
                                                if wind_speed > 30:
                                                    alert_types.append('High Wind Speed (>30)')
                                                    alert_info['alert_details']['wind_speed'] = wind_speed
                                            except:
                                                pass
                                        
                                        # 4. Existing AWS checks
                                        if 'rainfall' in row and pd.notnull(row['rainfall']):
                                            try:
                                                if float(row['rainfall']) > 50:
                                                    alert_types.append('High Rainfall (>50mm)')
                                                    alert_info['alert_details']['rainfall'] = float(row['rainfall'])
                                            except:
                                                pass
                                        
                                        if 'temperature' in row and pd.notnull(row['temperature']):
                                            try:
                                                if float(row['temperature']) > 40:
                                                    alert_types.append('High Temperature (>40)')
                                                    alert_info['alert_details']['temperature'] = float(row['temperature'])
                                            except:
                                                pass
                                        
                                        if alert_types:
                                            alert_detected = True
                                            alert_info['alert_type'] = ', '.join(alert_types)
                                    
                                    # River/Dam station level difference check with 10-day lookback
                                    elif (display_name in ['River', 'Dam'] and 
                                        'level_mtr' in row and 
                                        'location_id' in row):
                                        try:
                                            current_level = float(row['level_mtr'])
                                            location_id = row['location_id']
                                            
                                            # Initialize variables
                                            prev_level = None
                                            days_checked = 0
                                            comparison_date = None
                                            
                                            # Check up to 10 previous days for data
                                            while days_checked < 10 and prev_level is None:
                                                check_date = pd.to_datetime(row['last_updated'], format='%d/%m/%Y %H:%M', errors='coerce') - timedelta(days=days_checked + 1)
                                                if pd.isna(check_date):
                                                    break
                                                check_date_str = check_date.strftime('%d/%m/%Y')
                                                
                                                # Filter for this location and date in full_station_df
                                                prev_day_df = full_station_df[
                                                    (full_station_df['last_updated'].str.startswith(check_date_str)) & 
                                                    (full_station_df['location_id'] == location_id)
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
                                                    alert_detected = True
                                                    alert_info['alert_type'] = f'Level Change >1m (vs {comparison_date})'
                                                    alert_info['alert_details']['current_level'] = current_level
                                                    alert_info['alert_details']['previous_level'] = prev_level
                                                    alert_info['alert_details']['level_difference'] = level_diff
                                        except:
                                            pass
                                    
                                    # For non-EPAN stations, check battery voltage separately
                                    if (display_name != 'EPAN' and 
                                        'battery_voltage' in alert_info['alert_details'] and
                                        not alert_detected):
                                        batt_volt = alert_info['alert_details']['battery_voltage']
                                        if batt_volt < 10.5:
                                            alert_detected = True
                                            alert_info['alert_type'] = 'Low Battery (<10.5V)'
                                    
                                    if alert_detected:
                                        station_alerts.append(alert_info)
                                        all_alert_data.append(alert_info)
                                
                                results[display_name] = {
                                    'data': filtered_df,
                                    'alerts': station_alerts
                                }
                                total_records += len(filtered_df)
                                
                    except Exception as e:
                        st.error(f"Error processing {display_name}: {str(e)}")
                
                status.update(label="Search complete!", state="complete", expanded=False)
                
            finally:
                progress_bar.empty()

        # --------------------------- RESULTS DISPLAY ---------------------------
        if not results:
            st.info(f"🚨 No matching records found for selected filters")
        else:
            # Get the location name for display
            location_name = "Unknown"
            for station_data in results.values():
                if not station_data['data'].empty and 'location_name' in station_data['data'].columns:
                    location_name = station_data['data'].iloc[0]['location_name']
                    break
            
            st.success(f"✅ Found {total_records} records across {len(results)} stations")
            
            # Explanation of filtering logic
            st.info(f"""
                Showing all data where last_updated dates fall between {start_date.strftime('%d/%m/%Y')} 
                and {end_date.strftime('%d/%m/%Y')}.
            """)
            
            # Summary Metrics
            with st.container():
                cols = st.columns(4)
                cols[0].metric("Total Stations", len(results))
                cols[1].metric("Total Records", total_records)
                cols[2].metric("Date Range", f"{start_date} to {end_date}")
                cols[3].metric("Selected Location", f"{selected_location} ({location_name})")
            
            # --------------------------- BATTERY VOLTAGE GRAPHS ---------------------------
            st.markdown("---")
            st.subheader("🔋 Battery Voltage Monitoring")
            
            for display_name, result in results.items():
                if not result['data'].empty and 'batt_volt' in result['data'].columns:
                    try:
                        df = result['data'].copy()
                        
                        # Convert last_updated to datetime for plotting
                        df['plot_datetime'] = pd.to_datetime(
                            df['last_updated'], 
                            format='%d/%m/%Y %H:%M', 
                            errors='coerce'
                        )
                        df = df.dropna(subset=['plot_datetime'])
                        
                        if df.empty:
                            st.warning(f"No valid datetime data for {display_name}")
                            continue
                            
                        # Convert voltage to numeric
                        df['batt_volt'] = pd.to_numeric(df['batt_volt'], errors='coerce')
                        df = df[df['batt_volt'].notna()]
                        
                        if df.empty:
                            st.warning(f"No valid battery voltage data for {display_name}")
                            continue
                        
                        # Sort by datetime for continuous line
                        df = df.sort_values(by='plot_datetime')
                        
                        # Create time-based line graph
                        fig = px.line(
                            df,
                            x='plot_datetime',
                            y='batt_volt',
                            title=(
                                f'{display_name} Station - {selected_location} ({location_name}) Battery Voltage\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})\n'
                                f'Project: {selected_project}\n'
                                f'Total Readings: {len(df)}'
                            ),
                            labels={'batt_volt': 'Voltage (V)', 'plot_datetime': 'Date'},
                            template='plotly_white',
                            line_shape='linear'
                        )

                        # Add alert threshold line
                        fig.add_hline(
                            y=10.5,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Alert Threshold (10.5V)",
                            annotation_position="bottom right"
                        )

                        # Highlight alert points
                        alerts = df[df['batt_volt'] < 10.5]
                        if not alerts.empty:
                            fig.add_trace(px.scatter(
                                alerts,
                                x='plot_datetime',
                                y='batt_volt',
                                color_discrete_sequence=['red'],
                                hover_data={
                                    'batt_volt': ":.2f",
                                    'plot_datetime': True
                                }
                            ).update_traces(
                                name='Alerts',
                                marker=dict(size=8, symbol='x')
                            ).data[0])

                        # Customize layout
                        fig.update_layout(
                            hovermode='x unified',
                            height=500,
                            xaxis=dict(
                                title='Date',
                                tickformat='%d-%b',
                                rangeslider=dict(visible=True),
                                ticklabelmode='period'
                            ),
                            yaxis=dict(
                                title='Battery Voltage (V)',
                                range=[max(df['batt_volt'].min() - 0.5, 0), 14]
                            ),
                            showlegend=False
                        )

                        # Display the plot
                        st.plotly_chart(fig, use_container_width=True)
                            
                    except Exception as e:
                        st.error(f"Error creating voltage graph for {display_name}: {str(e)}")
            
            # --------------------------- EPAN WATER DEPTH GRAPHS ---------------------------
            if 'EPAN' in results and not results['EPAN']['data'].empty and 'epan_water_depth' in results['EPAN']['data'].columns:
                st.markdown("---")
                st.subheader("💧 EPAN Water Depth Monitoring")
                
                try:
                    epan_df = results['EPAN']['data'].copy()
                    
                    # Convert last_updated to datetime for plotting
                    epan_df['plot_datetime'] = pd.to_datetime(
                        epan_df['last_updated'], 
                        format='%d/%m/%Y %H:%M', 
                        errors='coerce'
                    )
                    epan_df = epan_df.dropna(subset=['plot_datetime'])
                    
                    if epan_df.empty:
                        st.warning("No valid datetime data for EPAN")
                    else:
                        # Convert depth to numeric
                        epan_df['epan_water_depth'] = pd.to_numeric(epan_df['epan_water_depth'], errors='coerce')
                        epan_df = epan_df[epan_df['epan_water_depth'].notna()]
                        
                        if not epan_df.empty:
                            # Sort by datetime for continuous line
                            epan_df = epan_df.sort_values(by='plot_datetime')
                            
                            # Create time-based line graph
                            fig = px.line(
                                epan_df,
                                x='plot_datetime',
                                y='epan_water_depth',
                                title=(
                                    f'EPAN Station - {selected_location} ({location_name}) Water Depth\n'
                                    f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})\n'
                                    f'Project: {selected_project}\n'
                                    f'Total Readings: {len(epan_df)}'
                                ),
                                labels={'epan_water_depth': 'Depth (mm)', 'plot_datetime': 'Date'},
                                template='plotly_white',
                                line_shape='linear',
                                color_discrete_sequence=['#1a73e8']
                            )

                            # Add threshold lines
                            fig.add_hline(
                                y=15,
                                line_dash="dot",
                                line_color="#ff6b35",
                                annotation_text="CRITICAL LEVEL (15mm)",
                                annotation_font_color="#ff6b35"
                            )
                            fig.add_hline(
                                y=50,
                                line_dash="dash",
                                line_color="orange",
                                annotation_text="LOW LEVEL (50mm)",
                                annotation_font_color="orange"
                            )
                            fig.add_hline(
                                y=200,
                                line_dash="dash",
                                line_color="orange",
                                annotation_text="HIGH LEVEL (200mm)",
                                annotation_font_color="orange"
                            )

                            # Highlight alert points
                            alerts = epan_df[
                                (epan_df['epan_water_depth'] <= 50) | 
                                (epan_df['epan_water_depth'] >= 200)
                            ]
                            
                            if not alerts.empty:
                                fig.add_trace(px.scatter(
                                    alerts,
                                    x='plot_datetime',
                                    y='epan_water_depth',
                                    color_discrete_sequence=['#ff6b35'],
                                    hover_data={
                                        'epan_water_depth': ":.2f",
                                        'plot_datetime': True
                                    }
                                ).update_traces(
                                    name='Alerts',
                                    marker=dict(size=10, symbol='hexagon', line=dict(width=2, color='DarkSlateGrey'))
                                ).data[0])

                            # Customize layout
                            fig.update_layout(
                                hovermode='x unified',
                                height=500,
                                xaxis=dict(
                                    title='Date',
                                    tickformat='%d-%b',
                                    rangeslider=dict(visible=True),
                                    ticklabelmode='period'
                                ),
                                yaxis=dict(
                                    title='Water Depth (mm)',
                                    range=[0, epan_df['epan_water_depth'].max() + 5]
                                ),
                                showlegend=False
                            )

                            # Display plot
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.warning("No valid EPAN water depth data available")
                
                except Exception as e:
                    st.error(f"Error creating EPAN water depth graph: {str(e)}")

            # --------------------------- DATA TABLE DISPLAY ---------------------------
            st.markdown("---")
            st.subheader("📊 Filtered Data Table")
            
            # Combine all station data into one dataframe for display
            all_data_combined = pd.concat([result['data'] for result in results.values()])
            
            # Display the data table
            st.dataframe(
                all_data_combined,
                use_container_width=True,
                height=400,
                column_config={
                    "location_id": "Location ID",
                    "location_name": "Location Name",
                    "project_name": "Project",
                    "data_date": "Date",
                    "timestamp": "Timestamp",
                    "data_time": "Data Time",
                    "batt_volt": st.column_config.NumberColumn("Battery Voltage", format="%.2f V"),
                    "epan_water_depth": st.column_config.NumberColumn("Water Depth", format="%.1f mm")
                }
            )

            # --------------------------- ALERTS TABLE DISPLAY ---------------------------
            if all_alert_data:
                st.markdown("---")
                st.subheader("⚠ Alerts Detected")
                
                # Create alert DataFrame
                alert_df = pd.DataFrame(all_alert_data)
                
                # Add location_name to alerts
                alert_df['location_name'] = location_name
                
                # Rename columns to match Categories tab
                alert_df.rename(columns={
                    'project': 'project_name',
                    'timestamp': 'last_updated',
                    'location': 'location_id'
                }, inplace=True)
                
                # Extract details from alert_details dictionary
                details_df = pd.json_normalize(alert_df['alert_details'])
                alert_df = pd.concat([alert_df.drop(['alert_details'], axis=1), details_df], axis=1)
                
                # Define desired column order
                base_columns = [
                    'project_name', 'station', 'location_name', 'location_id',
                    'last_updated', 'batt_volt', 'level_mtr', 'previous_level',
                    'level_difference', 'alert_type'
                ]
                
                # Get existing columns from our base list
                existing_columns = [col for col in base_columns if col in alert_df.columns]
                
                # Get remaining columns
                other_columns = [col for col in alert_df.columns if col not in base_columns]
                
                # Create final column order
                final_columns = existing_columns + other_columns
                alert_display_df = alert_df[final_columns]
                
                # Custom highlighting for alert rows
                def highlight_alert_rows(row):
                    styles = ['background-color: #ffebee'] * len(row)
                    alert_type = str(row.get('alert_type', ''))
                    
                    try:
                        # Battery alerts - highlight in light green
                        if 'Low Battery' in alert_type and 'batt_volt' in row.index:
                            batt_index = row.index.get_loc('batt_volt')
                            styles[batt_index] = 'background-color: #90ee90; font-weight: bold'
                        
                        # EPAN alerts - different colors based on alert type
                        if 'EPAN' in str(row.get('station', '')):
                            if 'epan_water_depth' in row.index:
                                depth_index = row.index.get_loc('epan_water_depth')
                                
                                if 'Constant Water Depth' in alert_type:
                                    styles[depth_index] = 'background-color: #add8e6; font-weight: bold'
                                elif 'Water Depth' in alert_type or 'Depth Change' in alert_type:
                                    styles[depth_index] = 'background-color: #ff9999; font-weight: bold'
                        
                        # River/Dam level changes
                        if row.get('station') in ['River', 'Dam'] and 'level_mtr' in row.index:
                            if 'Level Change' in alert_type:
                                level_index = row.index.get_loc('level_mtr')
                                styles[level_index] = 'background-color: #ff9999; font-weight: bold'
                        
                        # AWS rain alerts
                        if row.get('station') == 'AWS' and 'Rainfall > 100mm' in alert_type:
                            for rain_col in ['hourly_rain', 'daily_rain']:
                                if rain_col in row.index and pd.notnull(row[rain_col]):
                                    try:
                                        if float(row[rain_col]) > 100:
                                            col_index = row.index.get_loc(rain_col)
                                            styles[col_index] = 'background-color: #ffc0cb; font-weight: bold'
                                    except:
                                        pass
                        
                        # AWS zero-value alerts
                        if row.get('station') == 'AWS':
                            zero_cols = ['atmospheric_pressure', 'temperature', 'humidity', 
                                        'solar_radiation', 'wind_speed']
                            for col in zero_cols:
                                if col in row.index and str(row[col]) == '0':
                                    col_index = row.index.get_loc(col)
                                    styles[col_index] = 'background-color: #ff9999; font-weight: bold'
                    
                    except Exception as e:
                        print(f"Error in highlighting: {e}")
                    return styles

                # Display metrics and table
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.metric("Total Alerts", len(alert_display_df))
                
                with col2:
                    # Show alert type explanations
                    if 'EPAN' in alert_display_df['station'].values:
                        st.info("""
                            ℹ EPAN alerts: 
                            - 🔴 Red: Water depth ≤50 or ≥200
                            - 🔵 Blue: Constant depth for 4 days
                            - 🟠 Orange: Depth change >15mm
                        """)
                    if 'AWS' in alert_display_df['station'].values:
                        st.info("""
                            ℹ AWS alerts:
                            - 🔴 Red: Zero values or thresholds exceeded
                            - 🎀 Pink: Rainfall >100mm
                        """)
                
                # Display styled alerts table
                st.dataframe(
                    alert_display_df.style.apply(highlight_alert_rows, axis=1),
                    use_container_width=True,
                    height=min(400, len(alert_display_df) * 35 + 50)
                )
                
                # Add download button
                csv = alert_display_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download Alerts Data",
                    data=csv,
                    file_name=f"custom_query_alerts_{start_date.strftime('%Y%m%d')}to{end_date.strftime('%Y%m%d')}.csv",
                    mime='text/csv',
                    key="download_custom_alerts",
                    type="primary"
                )
            else:
                st.success("✅ No alerts detected for the selected filters and date range")