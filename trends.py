import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, px, DATA_SOURCES, re, go, io, fetch_data
from css import apply_custom_css

def show_trends_tab():
    st.subheader("Advanced Graphical Analysis")
    
    # Initialize visibility flags for all graphs
    visibility_flags = [
        'show_batt', 'show_epan', 'show_epan_diff', 'show_gate',
        'show_rain', 'show_ars_rain', 'show_aws_params', 'show_river_level', 'show_dam_level'
    ]
    for flag in visibility_flags:
        if flag not in st.session_state:
            st.session_state[flag] = True  # Default to visible

    # --------------------------- COMMON FILTERS ---------------------------
    with st.container():
        st.markdown("""
        <div style='background-color: #fff3e6; padding: 15px; border-radius: 5px; margin: 10px 0;'>
            <h2 style='color: #ff6b35; margin:0;'>🔍 Filter Parameters</h2>
        </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date", 
                value=datetime.now() - timedelta(days=7),
                key="common_start"
            )
        with col2:
            end_date = st.date_input(
                "End Date", 
                value=datetime.now(),
                key="common_end"
            )

        station_type = st.selectbox(
            "Station Type",
            list(DATA_SOURCES.keys()),
            index=0,
            help="Select station type to analyze"
        )

        # Load station data using the new database function
        station_data = load_station_data(station_type)
        
        projects = ["All Projects"] + (station_data['project_name'].unique().tolist() 
                if 'project_name' in station_data.columns and not station_data.empty else [])
        selected_project = st.selectbox(
            "Project Name",
            options=projects,
            index=0,
            help="Select project to analyze"
        )
        
        # Filter locations based on selected project
        if selected_project != "All Projects":
            project_data = station_data[station_data['project_name'] == selected_project]
        else:
            project_data = station_data

        locations = []
        if not project_data.empty and 'location_id' in project_data.columns and 'location_name' in project_data.columns:
            locations = project_data.apply(
                lambda row: f"{row['location_id']} ({row['location_name']})", 
                axis=1
            ).unique().tolist()
            locations.sort()
        
        selected_location_display = st.selectbox(
            "Select Location",
            options=locations,
            help="Select location to analyze"
        )
        
        selected_location_id = None
        if selected_location_display and locations:
            selected_location_id = selected_location_display.split(' ')[0]

        location_details = None
        if selected_location_id and not station_data.empty:
            location_record = station_data[
                station_data['location_id'].astype(str) == selected_location_id
            ].iloc[0] if not station_data.empty else None
            
            if location_record is not None:
                location_details = {
                    "ID": location_record.get('location_id', 'N/A'),
                    "Name": location_record.get('location_name', 'N/A'),
                    "Latitude": location_record.get('latitude', 'N/A'),
                    "Longitude": location_record.get('longitude', 'N/A'),
                    "Project": selected_project
                }

    # Initialize session state for graphs and alerts
    if 'batt_fig' not in st.session_state:
        st.session_state.batt_fig = None
    if 'epan_fig' not in st.session_state:
        st.session_state.epan_fig = None
    if 'epan_diff_fig' not in st.session_state:
        st.session_state.epan_diff_fig = None
    if 'gate_fig' not in st.session_state:
        st.session_state.gate_fig = None
    if 'rain_fig' not in st.session_state:
        st.session_state.rain_fig = None
    if 'ars_rain_fig' not in st.session_state:
        st.session_state.ars_rain_fig = None
    if 'aws_params_fig' not in st.session_state:
        st.session_state.aws_params_fig = None
    if 'river_level_fig' not in st.session_state:
        st.session_state.river_level_fig = None
    if 'dam_level_fig' not in st.session_state:
        st.session_state.dam_level_fig = None
    
    # Initialize alert DataFrames
    if 'batt_alerts' not in st.session_state:
        st.session_state.batt_alerts = pd.DataFrame()
    if 'epan_low_alerts' not in st.session_state:
        st.session_state.epan_low_alerts = pd.DataFrame()
    if 'epan_high_alerts' not in st.session_state:
        st.session_state.epan_high_alerts = pd.DataFrame()
    if 'epan_diff_alerts' not in st.session_state:
        st.session_state.epan_diff_alerts = pd.DataFrame()
    if 'epan_constant_alert' not in st.session_state:
        st.session_state.epan_constant_alert = None
    if 'gate_alerts' not in st.session_state:
        st.session_state.gate_alerts = pd.DataFrame()
    if 'rain_alerts' not in st.session_state:
        st.session_state.rain_alerts = pd.DataFrame()
    if 'ars_rain_alerts' not in st.session_state:
        st.session_state.ars_rain_alerts = pd.DataFrame()
    if 'aws_zero_alerts' not in st.session_state:
        st.session_state.aws_zero_alerts = pd.DataFrame()
    if 'river_alerts' not in st.session_state:
        st.session_state.river_alerts = pd.DataFrame()
    if 'dam_alerts' not in st.session_state:
        st.session_state.dam_alerts = pd.DataFrame()
    
    # --------------------------- ANALYSIS EXECUTION ---------------------------
    if st.button("Generate Analysis", type="primary", key="common_generate"):
        if not locations:
            st.warning("No locations available for selected filters")
        elif not selected_location_id:
            st.warning("Please select a location")
        else:
            try:
                # Clear previous state
                st.session_state.batt_fig = None
                st.session_state.epan_fig = None
                st.session_state.epan_diff_fig = None
                st.session_state.gate_fig = None
                st.session_state.rain_fig = None
                st.session_state.ars_rain_fig = None
                st.session_state.aws_params_fig = None
                st.session_state.river_level_fig = None
                st.session_state.dam_level_fig = None
                st.session_state.batt_alerts = pd.DataFrame()
                st.session_state.epan_low_alerts = pd.DataFrame()
                st.session_state.epan_high_alerts = pd.DataFrame()
                st.session_state.epan_diff_alerts = pd.DataFrame()
                st.session_state.epan_constant_alert = None
                st.session_state.gate_alerts = pd.DataFrame()
                st.session_state.rain_alerts = pd.DataFrame()
                st.session_state.ars_rain_alerts = pd.DataFrame()
                st.session_state.aws_zero_alerts = pd.DataFrame()
                st.session_state.river_alerts = pd.DataFrame()
                st.session_state.dam_alerts = pd.DataFrame()
                
                # Filter data
                df = station_data.copy()
                if selected_project != "All Projects":
                    df = df[df['project_name'] == selected_project]
                
                filtered_df = df[df['location_id'].astype(str) == selected_location_id].copy()
                
                if filtered_df.empty:
                    st.warning("No data found for selected location")
                    st.stop()

                # Process dates
                filtered_df['last_updated_dt'] = pd.to_datetime(
                    filtered_df['last_updated'], 
                    format='%d/%m/%Y %H:%M', 
                    errors='coerce'
                )
                filtered_df = filtered_df[filtered_df['last_updated_dt'].notna()]
                
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                
                filtered_df = filtered_df[
                    (filtered_df['last_updated_dt'] >= start_dt) & 
                    (filtered_df['last_updated_dt'] <= end_dt)
                ]
                
                if filtered_df.empty:
                    st.warning(f"""No data available for {selected_location_display} between
                            {start_date.strftime('%d-%b-%Y')} and {end_date.strftime('%d-%b-%Y')}""")
                    st.stop()

                # Create daily dataset (last record per day)
                daily_df = filtered_df.resample('D', on='last_updated_dt').last().reset_index()
                datetime_col = 'last_updated_dt'

                # --------------------------- BATTERY VOLTAGE GRAPH ---------------------------
                if 'batt_volt' in filtered_df.columns:
                    daily_df['batt_volt'] = pd.to_numeric(
                        daily_df['batt_volt'], 
                        errors='coerce'
                    )
                    batt_df = daily_df[daily_df['batt_volt'].notna()].copy()
                    
                    if not batt_df.empty:
                        batt_fig = px.line(
                            batt_df,
                            x=datetime_col,
                            y='batt_volt',
                            title=(
                                f'🔋 {station_type} Station - {selected_location_display} Battery Voltage\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            labels={'batt_volt': 'Voltage (V)'},
                            template='plotly_white',
                            line_shape='linear'
                        )

                        batt_fig.add_hline(
                            y=10.5,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Alert Threshold (10.5V)",
                            annotation_position="bottom right"
                        )

                        batt_alerts = batt_df[batt_df['batt_volt'] < 10.5]
                        st.session_state.batt_alerts = batt_alerts
                        
                        if not batt_alerts.empty:
                            batt_fig.add_trace(px.scatter(
                                batt_alerts,
                                x=datetime_col,
                                y='batt_volt',
                                color_discrete_sequence=['red'],
                                hover_data={
                                    'batt_volt': ":.2f",
                                    datetime_col: True,
                                    'location_id': True
                                }
                            ).update_traces(
                                name='Alerts',
                                marker=dict(size=8, symbol='x')
                            ).data[0])

                        batt_fig.update_layout(
                            hovermode='x unified',
                            height=400,
                            xaxis=dict(
                                title='Date',
                                tickformat='%d-%b-%Y',
                                rangeslider=dict(visible=True)
                            ),
                            yaxis=dict(
                                title='Battery Voltage (V)',
                                range=[max(batt_df['batt_volt'].min() - 0.5, 0), 14]
                            ),
                            showlegend=False
                        )
                        
                        st.session_state.batt_fig = batt_fig

                # --------------------------- EPAN WATER DEPTH GRAPH ---------------------------
                if station_type == "EPAN" and 'epan_water_depth' in filtered_df.columns:
                    daily_df['epan_water_depth'] = pd.to_numeric(
                        daily_df['epan_water_depth'], 
                        errors='coerce'
                    )
                    epan_df = daily_df[daily_df['epan_water_depth'].notna()].copy()
                    
                    if not epan_df.empty:
                        # Create EPAN Water Depth graph
                        epan_fig = px.line(
                            epan_df,
                            x=datetime_col,
                            y='epan_water_depth',
                            title=(
                                f'💧 EPAN Station - {selected_location_display} Water Depth\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            labels={'epan_water_depth': 'Depth (mm)'},
                            template='plotly_white',
                            line_shape='linear',
                            color_discrete_sequence=['#1a73e8']
                        )

                        # Threshold lines
                        epan_fig.add_hline(
                            y=15,
                            line_dash="dot",
                            line_color="#ff6b35",
                            annotation_text="CRITICAL LEVEL (15mm)",
                            annotation_font_color="#ff6b35"
                        )
                        
                        epan_fig.add_hline(
                            y=200,
                            line_dash="dash",
                            line_color="#ff0000",
                            annotation_text="ALERT LEVEL (200mm)",
                            annotation_position="top right",
                            annotation_font_color="#ff0000"
                        )

                        # Constant value detection (only if date range >= 4 days)
                        time_range_days = (end_dt - start_dt).days
                        if time_range_days >= 4:
                            # Get last 4 days of data (even if not consecutive)
                            last_4_days = epan_df.sort_values('last_updated_dt', ascending=False).head(4)
                            
                            # Check if all values are the same
                            if last_4_days['epan_water_depth'].nunique() == 1:
                                constant_value = last_4_days['epan_water_depth'].iloc[0]
                                
                                st.session_state.epan_constant_alert = {
                                    'value': constant_value,
                                    'start': last_4_days['last_updated_dt'].min(),
                                    'end': last_4_days['last_updated_dt'].max(),
                                    'dates': last_4_days['last_updated_dt'].dt.strftime('%Y-%m-%d').unique()
                                }
                                
                                epan_fig.add_trace(px.line(
                                    last_4_days,
                                    x=datetime_col,
                                    y='epan_water_depth',
                                    color_discrete_sequence=['red']
                                ).update_traces(
                                    line=dict(width=4),
                                    name='Constant Value Alert'
                                ).data[0])

                        # Alerts
                        st.session_state.epan_low_alerts = epan_df[epan_df['epan_water_depth'] < 15]
                        st.session_state.epan_high_alerts = epan_df[epan_df['epan_water_depth'] == 200]
                        
                        # Low alerts
                        if not st.session_state.epan_low_alerts.empty:
                            epan_fig.add_trace(px.scatter(
                                st.session_state.epan_low_alerts,
                                x=datetime_col,
                                y='epan_water_depth',
                                color_discrete_sequence=['#ff6b35'],
                                hover_data={
                                    'epan_water_depth': ":.2f",
                                    datetime_col: True,
                                    'location_id': True
                                }
                            ).update_traces(
                                name='Low Alerts',
                                marker=dict(size=10, symbol='hexagon', line=dict(width=2, color='DarkSlateGrey'))
                            ).data[0])
                        
                        # High alerts
                        if not st.session_state.epan_high_alerts.empty:
                            epan_fig.add_trace(px.scatter(
                                st.session_state.epan_high_alerts,
                                x=datetime_col,
                                y='epan_water_depth',
                                color_discrete_sequence=['red'],
                                hover_data={
                                    'epan_water_depth': ":.2f",
                                    datetime_col: True,
                                    'location_id': True
                                }
                            ).update_traces(
                                name='High Alerts (200mm)',
                                marker=dict(size=10, symbol='diamond', line=dict(width=2, color='black'))
                            ).data[0])

                        epan_fig.update_layout(
                            hovermode='x unified',
                            height=400,
                            xaxis=dict(
                                title='Date',
                                tickformat='%d-%b-%Y',
                                rangeslider=dict(visible=True)
                            ),
                            yaxis=dict(
                                title='Water Depth (mm)',
                                range=[0, max(epan_df['epan_water_depth'].max() + 5, 200)]
                            ),
                            showlegend=True
                        )
                        
                        st.session_state.epan_fig = epan_fig
                        
                        # Create EPAN Daily Difference graph
                        daily_epan = epan_df.copy()
                        
                        # Calculate daily differences
                        daily_epan['prev_depth'] = daily_epan['epan_water_depth'].shift(1)
                        daily_epan['depth_diff'] = daily_epan['epan_water_depth'] - daily_epan['prev_depth']
                        
                        # Fill gaps by propagating last valid observation
                        daily_epan['prev_depth_filled'] = daily_epan['prev_depth'].ffill()
                        daily_epan['depth_diff_filled'] = daily_epan['epan_water_depth'] - daily_epan['prev_depth_filled']
                        
                        # Create alerts for differences > 15mm
                        epan_diff_alerts = daily_epan[daily_epan['depth_diff_filled'].abs() > 15]
                        st.session_state.epan_diff_alerts = epan_diff_alerts
                        
                        # Create plot
                        epan_diff_fig = go.Figure()
                        
                        # Add water depth trace
                        epan_diff_fig.add_trace(go.Scatter(
                            x=daily_epan['last_updated_dt'],
                            y=daily_epan['epan_water_depth'],
                            mode='lines+markers',
                            name='Water Depth',
                            line=dict(color='blue', width=2)
                        ))
                        
                        # Add difference trace
                        epan_diff_fig.add_trace(go.Bar(
                            x=daily_epan['last_updated_dt'],
                            y=daily_epan['depth_diff_filled'],
                            name='Daily Difference',
                            marker_color='orange',
                            opacity=0.7
                        ))
                        
                        # Add alert markers
                        if not epan_diff_alerts.empty:
                            epan_diff_fig.add_trace(go.Scatter(
                                x=epan_diff_alerts['last_updated_dt'],
                                y=epan_diff_alerts['epan_water_depth'],
                                mode='markers',
                                name='Change Alert',
                                marker=dict(color='red', size=10, symbol='triangle-up')
                            ))
                        
                        epan_diff_fig.update_layout(
                            title=(
                                f'📈 EPAN Daily Water Depth Change - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            yaxis_title='Water Depth (mm)',
                            height=400,
                            barmode='overlay',
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        # Add threshold lines
                        epan_diff_fig.add_hline(
                            y=15,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Upper Threshold"
                        )
                        
                        epan_diff_fig.add_hline(
                            y=-15,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Lower Threshold"
                        )
                        
                        st.session_state.epan_diff_fig = epan_diff_fig
                
                # --------------------------- GATE ANALYSIS ---------------------------
                if station_type == "Gate":
                    # Create list of gate columns
                    gate_cols = [col for col in filtered_df.columns if col.startswith('g') and col[1:].isdigit()]
                    
                    if gate_cols:
                        # Convert gate columns to numeric
                        for col in gate_cols:
                            filtered_df[col] = pd.to_numeric(filtered_df[col], errors='coerce').fillna(0)
                        
                        # Create daily aggregates
                        filtered_df['date'] = filtered_df['last_updated_dt'].dt.date
                        daily_gate = filtered_df.groupby('date')[gate_cols].max().reset_index()
                        
                        # Find days with gate activity
                        gate_alerts = daily_gate.copy()
                        gate_alerts['active_gates'] = gate_alerts.apply(
                            lambda row: [col for col in gate_cols if row[col] > 0], 
                            axis=1
                        )
                        gate_alerts = gate_alerts[gate_alerts['active_gates'].apply(len) > 0]
                        st.session_state.gate_alerts = gate_alerts
                        
                        # Create plot with all gates
                        gate_fig = go.Figure()
                        for col in gate_cols:
                            gate_fig.add_trace(go.Bar(
                                x=daily_gate['date'],
                                y=daily_gate[col],
                                name=f'Gate {col[1:]}',
                                hovertemplate='%{y}',
                                visible='legendonly'  # Start with gates hidden
                            ))
                        
                        # Add trace for total open gates
                        daily_gate['total_open'] = daily_gate[gate_cols].gt(0).sum(axis=1)
                        gate_fig.add_trace(go.Bar(
                            x=daily_gate['date'],
                            y=daily_gate['total_open'],
                            name='Total Open Gates',
                            marker_color='#1f77b4',
                            hovertemplate='Total: %{y}'
                        ))
                        
                        gate_fig.update_layout(
                            title=(
                                f'🚪 Gate Activity - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            barmode='stack',
                            yaxis=dict(title='Gate Value / Count'),
                            height=400,
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        st.session_state.gate_fig = gate_fig

                # --------------------------- AWS RAIN ANALYSIS ---------------------------
                if station_type == "AWS":
                    # Use daily dataset
                    if 'daily_rain' in daily_df.columns:
                        daily_df['daily_rain'] = pd.to_numeric(daily_df['daily_rain'], errors='coerce')
                        
                        # Create alert column
                        daily_df['heavy_rain'] = daily_df['daily_rain'] > 100
                        
                        # Create plot
                        rain_fig = go.Figure()
                        
                        # Add rain data
                        rain_fig.add_trace(go.Bar(
                            x=daily_df['last_updated_dt'],
                            y=daily_df['daily_rain'],
                            name='Daily Rainfall',
                            marker_color='#1f77b4'
                        ))
                        
                        # Add alert markers
                        rain_alerts = daily_df[daily_df['heavy_rain'] == True]
                        if not rain_alerts.empty:
                            rain_fig.add_trace(go.Scatter(
                                x=rain_alerts['last_updated_dt'],
                                y=rain_alerts['daily_rain'] + 5,
                                mode='markers',
                                name='Heavy Rain Alert',
                                marker=dict(color='red', size=10, symbol='triangle-up')
                            ))
                        
                        rain_fig.update_layout(
                            title=(
                                f'🌧 AWS Rain Analysis - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            yaxis_title='Rainfall (mm)',
                            height=400,
                            hovermode='x unified',
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        rain_fig.add_hline(
                            y=100,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Alert Threshold (100mm)"
                        )
                        
                        st.session_state.rain_fig = rain_fig
                        st.session_state.rain_alerts = rain_alerts

                # --------------------------- ARS RAIN ANALYSIS ---------------------------
                if station_type == "ARS":
                    # Use daily dataset
                    if 'daily_rain' in daily_df.columns:
                        daily_df['daily_rain'] = pd.to_numeric(daily_df['daily_rain'], errors='coerce')
                        
                        # Create alert column
                        daily_df['heavy_rain'] = daily_df['daily_rain'] > 100
                        
                        # Create plot
                        ars_rain_fig = go.Figure()
                        
                        # Add rain data
                        ars_rain_fig.add_trace(go.Bar(
                            x=daily_df['last_updated_dt'],
                            y=daily_df['daily_rain'],
                            name='Daily Rainfall',
                            marker_color='#1f77b4'
                        ))
                        
                        # Add alert markers
                        ars_rain_alerts = daily_df[daily_df['heavy_rain'] == True]
                        if not ars_rain_alerts.empty:
                            ars_rain_fig.add_trace(go.Scatter(
                                x=ars_rain_alerts['last_updated_dt'],
                                y=ars_rain_alerts['daily_rain'] + 5,
                                mode='markers',
                                name='Heavy Rain Alert',
                                marker=dict(color='red', size=10, symbol='triangle-up')
                            ))
                        
                        ars_rain_fig.update_layout(
                            title=(
                                f'🌧 ARS Rain Analysis - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            yaxis_title='Rainfall (mm)',
                            height=400,
                            hovermode='x unified',
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        ars_rain_fig.add_hline(
                            y=100,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Alert Threshold (100mm)"
                        )
                        
                        st.session_state.ars_rain_fig = ars_rain_fig
                        st.session_state.ars_rain_alerts = ars_rain_alerts

                # --------------------------- AWS PARAMETERS ANALYSIS ---------------------------
                if station_type == "AWS":
                    # Define sensor columns
                    sensor_cols = ['wind_speed', 'wind_direction', 'atm_pressure', 
                                'temperature', 'humidity', 'solar_radiation']
                    
                    # Convert sensor columns to numeric
                    for col in sensor_cols:
                        if col in daily_df.columns:
                            daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce')
                    
                    # Create plot
                    aws_params_fig = go.Figure()
                    colors = px.colors.qualitative.Plotly
                    
                    # Add sensor data
                    for i, col in enumerate(sensor_cols):
                        if col in daily_df.columns:
                            aws_params_fig.add_trace(go.Scatter(
                                x=daily_df['last_updated_dt'],
                                y=daily_df[col],
                                mode='lines+markers',
                                name=col.replace('_', ' ').title(),
                                line=dict(color=colors[i % len(colors)], width=2),
                                yaxis=f'y{i+1}' if i > 0 else 'y'
                            ))
                    
                    # Create zero alerts
                    zero_alerts = []
                    for col in sensor_cols:
                        if col in daily_df.columns:
                            zero_mask = daily_df[col] == 0
                            if zero_mask.any():
                                zero_df = daily_df[zero_mask]
                                for _, row in zero_df.iterrows():
                                    zero_alerts.append({
                                        'Timestamp': row['last_updated_dt'],
                                        'Parameter': col,
                                        'Value': 0
                                    })
                    
                    st.session_state.aws_zero_alerts = pd.DataFrame(zero_alerts)
                    
                    # Add alert markers
                    if zero_alerts:
                        for col in sensor_cols:
                            if col in daily_df.columns:
                                zero_points = daily_df[daily_df[col] == 0]
                                if not zero_points.empty:
                                    aws_params_fig.add_trace(go.Scatter(
                                        x=zero_points['last_updated_dt'],
                                        y=zero_points[col],
                                        mode='markers',
                                        name=f'{col} Zero Alert',
                                        marker=dict(color='red', size=8, symbol='x')
                                    ))
                    
                    # Create axis layout
                    layout = dict(
                        title=(
                            f'🌬 AWS Parameters - {selected_location_display}\n'
                            f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                        ),
                        height=500,
                        hovermode='x unified',
                        xaxis=dict(tickformat='%d-%b-%Y')
                    )
                    
                    # Add multiple y-axes if needed
                    for i, col in enumerate(sensor_cols):
                        if col in daily_df.columns:
                            if i == 0:
                                layout['yaxis'] = dict(title=f'{col}'.title())
                            else:
                                layout[f'yaxis{i+1}'] = dict(
                                    title=f'{col}'.title(),
                                    overlaying='y',
                                    side='right',
                                    position=1 - (0.1 * i)
                                )
                    
                    aws_params_fig.update_layout(layout)
                    st.session_state.aws_params_fig = aws_params_fig

                # --------------------------- RIVER LEVEL ANALYSIS ---------------------------
                if station_type == "River" and 'water_level' in filtered_df.columns:
                    # Use daily dataset
                    daily_df['water_level'] = pd.to_numeric(daily_df['water_level'], errors='coerce')
                    river_df = daily_df[daily_df['water_level'].notna()].copy()
                    
                    if not river_df.empty:
                        # Calculate daily differences using the previous available day
                        river_df['prev_level'] = river_df['water_level'].shift(1)
                        
                        # Forward fill missing previous days
                        river_df['prev_level_filled'] = river_df['prev_level'].ffill()
                        
                        # Calculate differences using filled values
                        river_df['level_diff'] = river_df['water_level'] - river_df['prev_level_filled']
                        
                        # Create alerts for differences > 1m
                        river_alerts = river_df[
                            (river_df['level_diff'].abs() > 1) & 
                            (river_df['prev_level_filled'].notna())  # Ensure we have a valid comparison
                        ]
                        st.session_state.river_alerts = river_alerts
                        
                        # Create plot
                        river_level_fig = go.Figure()
                        
                        # Add water level trace
                        river_level_fig.add_trace(go.Scatter(
                            x=river_df['last_updated_dt'],
                            y=river_df['water_level'],
                            mode='lines+markers',
                            name='Water Level',
                            line=dict(color='blue', width=2)
                        ))
                        
                        # Add difference trace
                        river_level_fig.add_trace(go.Bar(
                            x=river_df['last_updated_dt'],
                            y=river_df['level_diff'],
                            name='Daily Difference',
                            marker_color='orange',
                            opacity=0.7
                        ))
                        
                        # Add alert markers
                        if not river_alerts.empty:
                            river_level_fig.add_trace(go.Scatter(
                                x=river_alerts['last_updated_dt'],
                                y=river_alerts['water_level'],
                                mode='markers',
                                name='Level Change Alert',
                                marker=dict(color='red', size=10, symbol='triangle-up')
                            ))
                        
                        river_level_fig.update_layout(
                            title=(
                                f'🌊 River Level Analysis - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            yaxis_title='Water Level (m)',
                            height=400,
                            barmode='overlay',
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        # Add threshold lines
                        river_level_fig.add_hline(
                            y=1,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Upper Threshold (1m)"
                        )
                        
                        river_level_fig.add_hline(
                            y=-1,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Lower Threshold (-1m)"
                        )
                        
                        st.session_state.river_level_fig = river_level_fig

                # --------------------------- DAM LEVEL ANALYSIS ---------------------------
                if station_type == "Dam" and 'water_level' in filtered_df.columns:
                    # Use daily dataset
                    daily_df['water_level'] = pd.to_numeric(daily_df['water_level'], errors='coerce')
                    dam_df = daily_df[daily_df['water_level'].notna()].copy()
                    
                    if not dam_df.empty:
                        # Calculate daily differences using the previous available day
                        dam_df['prev_level'] = dam_df['water_level'].shift(1)
                        
                        # Forward fill missing previous days
                        dam_df['prev_level_filled'] = dam_df['prev_level'].ffill()
                        
                        # Calculate differences using filled values
                        dam_df['level_diff'] = dam_df['water_level'] - dam_df['prev_level_filled']
                        
                        # Create alerts for differences > 1m
                        dam_alerts = dam_df[
                            (dam_df['level_diff'].abs() > 1) & 
                            (dam_df['prev_level_filled'].notna())  # Ensure we have a valid comparison
                        ]
                        st.session_state.dam_alerts = dam_alerts
                        
                        # Create plot
                        dam_level_fig = go.Figure()
                        
                        # Add water level trace
                        dam_level_fig.add_trace(go.Scatter(
                            x=dam_df['last_updated_dt'],
                            y=dam_df['water_level'],
                            mode='lines+markers',
                            name='Water Level',
                            line=dict(color='green', width=2)
                        ))
                        
                        # Add difference trace
                        dam_level_fig.add_trace(go.Bar(
                            x=dam_df['last_updated_dt'],
                            y=dam_df['level_diff'],
                            name='Daily Difference',
                            marker_color='purple',
                            opacity=0.7
                        ))
                        
                        # Add alert markers
                        if not dam_alerts.empty:
                            dam_level_fig.add_trace(go.Scatter(
                                x=dam_alerts['last_updated_dt'],
                                y=dam_alerts['water_level'],
                                mode='markers',
                                name='Level Change Alert',
                                marker=dict(color='red', size=10, symbol='triangle-up')
                            ))
                        
                        dam_level_fig.update_layout(
                            title=(
                                f'💧 Dam Level Analysis - {selected_location_display}\n'
                                f'({start_date.strftime("%d-%b-%Y")} to {end_date.strftime("%d-%b-%Y")})'
                            ),
                            yaxis_title='Water Level (m)',
                            height=400,
                            barmode='overlay',
                            xaxis=dict(tickformat='%d-%b-%Y')
                        )
                        
                        # Add threshold lines
                        dam_level_fig.add_hline(
                            y=1,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Upper Threshold (1m)"
                        )
                        
                        dam_level_fig.add_hline(
                            y=-1,
                            line_dash="dash",
                            line_color="red",
                            annotation_text="Lower Threshold (-1m)"
                        )
                        
                        st.session_state.dam_level_fig = dam_level_fig

            except Exception as e:
                st.error(f"Processing error: {str(e)}")
                import traceback
                st.error(traceback.format_exc())
                st.stop()

    # --------------------------- DISPLAY LOCATION DETAILS ---------------------------
    if location_details:
        st.subheader("📍 Location Information")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Location ID", location_details["ID"])
            st.metric("Latitude", location_details["Latitude"])
        with col2:
            st.metric("Location Name", location_details["Name"])
            st.metric("Longitude", location_details["Longitude"])
        with col3:
            st.metric("Project", location_details["Project"])
            st.metric("Station Type", station_type)
    
    # --------------------------- GRAPH VISIBILITY CONTROLS ---------------------------
    # Only show if at least one graph is available
    graphs = [
        st.session_state.batt_fig, st.session_state.epan_fig, st.session_state.epan_diff_fig,
        st.session_state.gate_fig, st.session_state.rain_fig, st.session_state.ars_rain_fig,
        st.session_state.aws_params_fig, st.session_state.river_level_fig, st.session_state.dam_level_fig
    ]
    if any(graphs):
        st.subheader("📊 Graph Visibility Options")
        
        # Create columns for checkboxes
        cols = st.columns(4)
        checkbox_counter = 0
        
        # Battery Voltage
        if st.session_state.batt_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_batt = st.checkbox(
                    "Battery Voltage", 
                    value=st.session_state.show_batt,
                    key="vis_batt"
                )
            checkbox_counter += 1
        
        # EPAN Water Depth
        if st.session_state.epan_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_epan = st.checkbox(
                    "EPAN Water Depth", 
                    value=st.session_state.show_epan,
                    key="vis_epan"
                )
            checkbox_counter += 1
        
        # EPAN Daily Difference
        if st.session_state.epan_diff_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_epan_diff = st.checkbox(
                    "EPAN Daily Change", 
                    value=st.session_state.show_epan_diff,
                    key="vis_epan_diff"
                )
            checkbox_counter += 1
        
        # Gate Activity
        if st.session_state.gate_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_gate = st.checkbox(
                    "Gate Activity", 
                    value=st.session_state.show_gate,
                    key="vis_gate"
                )
            checkbox_counter += 1
        
        # AWS Rain Analysis
        if st.session_state.rain_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_rain = st.checkbox(
                    "AWS Rain Analysis", 
                    value=st.session_state.show_rain,
                    key="vis_rain"
                )
            checkbox_counter += 1
        
        # ARS Rain Analysis
        if st.session_state.ars_rain_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_ars_rain = st.checkbox(
                    "ARS Rain Analysis", 
                    value=st.session_state.show_ars_rain,
                    key="vis_ars_rain"
                )
            checkbox_counter += 1
        
        # AWS Parameters
        if st.session_state.aws_params_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_aws_params = st.checkbox(
                    "AWS Parameters", 
                    value=st.session_state.show_aws_params,
                    key="vis_aws_params"
                )
            checkbox_counter += 1
        
        # River Level
        if st.session_state.river_level_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_river_level = st.checkbox(
                    "River Level", 
                    value=st.session_state.show_river_level,
                    key="vis_river_level"
                )
            checkbox_counter += 1
        
        # Dam Level
        if st.session_state.dam_level_fig:
            with cols[checkbox_counter % 4]:
                st.session_state.show_dam_level = st.checkbox(
                    "Dam Level", 
                    value=st.session_state.show_dam_level,
                    key="vis_dam_level"
                )
            checkbox_counter += 1
    
    # --------------------------- DISPLAY GRAPHS ---------------------------
    # Battery Voltage (for all station types)
    if st.session_state.batt_fig and st.session_state.show_batt:
        with st.expander("🔋 Battery Voltage Analysis", expanded=True):
            st.plotly_chart(st.session_state.batt_fig, use_container_width=True)
            
            if not st.session_state.batt_alerts.empty:
                alert_count = len(st.session_state.batt_alerts)
                st.warning(f"🔴 Alerts Detected: {alert_count} instances below 10.5V")
                st.dataframe(st.session_state.batt_alerts[['last_updated_dt', 'batt_volt']].rename(
                    columns={'last_updated_dt': 'Date', 'batt_volt': 'Voltage (V)'}
                ))
            else:
                st.success("✅ No voltage alerts detected in selected period")
    
    # Station-specific graphs
    if station_type == "River" and st.session_state.river_level_fig and st.session_state.show_river_level:
        with st.expander("🌊 River Level Analysis", expanded=True):
            st.plotly_chart(st.session_state.river_level_fig, use_container_width=True)
            
            if not st.session_state.river_alerts.empty:
                alert_count = len(st.session_state.river_alerts)
                st.warning(f"🔴 Level Change Alerts: {alert_count} days with >1m difference")
                display_df = st.session_state.river_alerts.copy()
                display_df['Difference'] = display_df['level_diff'].apply(
                    lambda x: f"{x:.2f} m"
                )
                display_df['Previous Level'] = display_df['prev_level_filled'].apply(
                    lambda x: f"{x:.2f} m"
                )
                st.dataframe(display_df[[
                    'last_updated_dt', 
                    'water_level', 
                    'Previous Level',
                    'Difference'
                ]].rename(
                    columns={
                        'last_updated_dt': 'Date', 
                        'water_level': 'Current Level (m)'
                    }
                ))
            else:
                st.success("✅ No significant river level changes detected")
    
    elif station_type == "Dam" and st.session_state.dam_level_fig and st.session_state.show_dam_level:
        with st.expander("💧 Dam Level Analysis", expanded=True):
            st.plotly_chart(st.session_state.dam_level_fig, use_container_width=True)
            
            if not st.session_state.dam_alerts.empty:
                alert_count = len(st.session_state.dam_alerts)
                st.warning(f"🔴 Level Change Alerts: {alert_count} days with >1m difference")
                display_df = st.session_state.dam_alerts.copy()
                display_df['Difference'] = display_df['level_diff'].apply(
                    lambda x: f"{x:.2f} m"
                )
                display_df['Previous Level'] = display_df['prev_level_filled'].apply(
                    lambda x: f"{x:.2f} m"
                )
                st.dataframe(display_df[[
                    'last_updated_dt', 
                    'water_level', 
                    'Previous Level',
                    'Difference'
                ]].rename(
                    columns={
                        'last_updated_dt': 'Date', 
                        'water_level': 'Current Level (m)'
                    }
                ))
            else:
                st.success("✅ No significant dam level changes detected")
    
    elif station_type == "EPAN":
        if st.session_state.epan_fig and st.session_state.show_epan:
            with st.expander("💧 EPAN Water Depth Analysis", expanded=True):
                st.plotly_chart(st.session_state.epan_fig, use_container_width=True)
                
                # EPAN alerts section
                any_epan_alerts = False
                
                # Low alerts
                if not st.session_state.epan_low_alerts.empty:
                    any_epan_alerts = True
                    alert_count = len(st.session_state.epan_low_alerts)
                    st.warning(f"🔴 Low Depth Alerts: {alert_count} instances below 15mm")
                    st.dataframe(st.session_state.epan_low_alerts[['last_updated_dt', 'epan_water_depth']].rename(
                        columns={'last_updated_dt': 'Date', 'epan_water_depth': 'Depth (mm)'}
                    ))
                
                # High alerts
                if not st.session_state.epan_high_alerts.empty:
                    any_epan_alerts = True
                    alert_count = len(st.session_state.epan_high_alerts)
                    st.warning(f"🔴 High Depth Alerts: {alert_count} instances at exactly 200mm")
                    st.dataframe(st.session_state.epan_high_alerts[['last_updated_dt', 'epan_water_depth']].rename(
                        columns={'last_updated_dt': 'Date', 'epan_water_depth': 'Depth (mm)'}
                    ))
                
                # Constant value alert
                if st.session_state.epan_constant_alert:
                    any_epan_alerts = True
                    st.warning("🔴 Constant Value Alert (Last 4 Days)")
                    st.write(f"Constant value of {st.session_state.epan_constant_alert['value']} mm detected")
                    st.write(f"Period: {st.session_state.epan_constant_alert['start'].strftime('%Y-%m-%d %H:%M')} to "
                            f"{st.session_state.epan_constant_alert['end'].strftime('%Y-%m-%d %H:%M')}")
                    st.write(f"Dates: {', '.join(st.session_state.epan_constant_alert['dates'])}")
                
                if not any_epan_alerts:
                    st.success("✅ No EPAN depth alerts detected in selected period")
        
        if st.session_state.epan_diff_fig and st.session_state.show_epan_diff:
            with st.expander("📈 EPAN Daily Water Depth Change", expanded=False):
                st.plotly_chart(st.session_state.epan_diff_fig, use_container_width=True)
                
                if not st.session_state.epan_diff_alerts.empty:
                    alert_count = len(st.session_state.epan_diff_alerts)
                    st.warning(f"🔴 Change Alerts: {alert_count} days with >15mm difference")
                    # Create display dataframe with all needed columns
                    display_df = st.session_state.epan_diff_alerts.copy()
                    
                    # Add formatted columns for display
                    display_df['Previous Day'] = display_df['prev_depth'].apply(
                        lambda x: f"{x:.2f} mm" if not pd.isna(x) else "N/A"
                    )
                    display_df['Current Day'] = display_df['epan_water_depth'].apply(
                        lambda x: f"{x:.2f} mm"
                    )
                    display_df['Difference'] = display_df['depth_diff_filled'].apply(
                        lambda x: f"{x:.2f} mm"
                    )
                    
                    # Add arrow indicator showing change direction
                    def get_change_direction(row):
                        if pd.isna(row['prev_depth']) or pd.isna(row['depth_diff_filled']):
                            return ""
                        if row['depth_diff_filled'] > 0:
                            return "⬆ Increase"
                        elif row['depth_diff_filled'] < 0:
                            return "⬇ Decrease"
                        return "↔ No Change"
                    
                    display_df['Change'] = display_df.apply(get_change_direction, axis=1)
                    
                    # Create the display dataframe with renamed columns
                    st.dataframe(
                        display_df[[
                            'last_updated_dt', 
                            'Previous Day', 
                            'Current Day',
                            'Difference',
                            'Change'
                        ]].rename(columns={
                            'last_updated_dt': 'Date',
                        }),
                        use_container_width=True
                    )
                    
                    # Add explanation of the change direction
                    st.caption("""
                        Change Direction Indicators  
                        ⬆ Increase: Water depth increased compared to previous day  
                        ⬇ Decrease: Water depth decreased compared to previous day  
                        ↔ No Change: Depth remained the same (difference = 0)
                    """)
                else:
                    st.success("✅ No significant water depth changes detected")
    
    elif station_type == "Gate" and st.session_state.gate_fig and st.session_state.show_gate:
        with st.expander("🚪 Gate Activity Analysis", expanded=True):
            st.plotly_chart(st.session_state.gate_fig, use_container_width=True)
            
            if not st.session_state.gate_alerts.empty:
                alert_count = len(st.session_state.gate_alerts)
                st.warning(f"🔴 Gate Activity Detected: {alert_count} days with open gates")
                # Format gate information for display
                display_df = st.session_state.gate_alerts.copy()
                display_df['Active Gates'] = display_df['active_gates'].apply(
                    lambda gates: ', '.join([g.replace('g', 'Gate ') for g in gates]) if gates else 'None'
                )
                st.dataframe(display_df[['date', 'Active Gates']].rename(columns={'date': 'Date'}))
            else:
                st.success("✅ No gate activity detected in selected period")
    
    elif station_type == "AWS":
        if st.session_state.rain_fig and st.session_state.show_rain:
            with st.expander("🌧 AWS Rain Analysis", expanded=True):
                st.plotly_chart(st.session_state.rain_fig, use_container_width=True)
                
                if not st.session_state.rain_alerts.empty:
                    alert_count = len(st.session_state.rain_alerts)
                    st.warning(f"🔴 Heavy Rain Alerts: {alert_count} instances above 100mm")
                    st.dataframe(st.session_state.rain_alerts[['last_updated_dt', 'daily_rain']].rename(
                        columns={'last_updated_dt': 'Date', 'daily_rain': 'Daily Rain (mm)'}
                    ))
                else:
                    st.success("✅ No heavy rain alerts detected in selected period")
        
        if st.session_state.aws_params_fig and st.session_state.show_aws_params:
            with st.expander("🌬 AWS Parameters Analysis", expanded=False):
                st.plotly_chart(st.session_state.aws_params_fig, use_container_width=True)
                
                if not st.session_state.aws_zero_alerts.empty:
                    alert_count = len(st.session_state.aws_zero_alerts)
                    st.warning(f"🔴 Zero Value Alerts: {alert_count} instances with sensor readings at zero")
                    st.dataframe(st.session_state.aws_zero_alerts)
                else:
                    st.success("✅ All AWS sensors reported non-zero values")
    
    elif station_type == "ARS" and st.session_state.ars_rain_fig and st.session_state.show_ars_rain:
        with st.expander("🌧 ARS Rain Analysis", expanded=True):
            st.plotly_chart(st.session_state.ars_rain_fig, use_container_width=True)
            
            if not st.session_state.ars_rain_alerts.empty:
                alert_count = len(st.session_state.ars_rain_alerts)
                st.warning(f"🔴 Heavy Rain Alerts: {alert_count} instances above 100mm")
                st.dataframe(st.session_state.ars_rain_alerts[['last_updated_dt', 'daily_rain']].rename(
                    columns={'last_updated_dt': 'Date', 'daily_rain': 'Daily Rain (mm)'}
                ))
            else:
                st.success("✅ No heavy rain alerts detected in selected period")