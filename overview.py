import streamlit as st
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, DATA_SOURCES, px, go, create_db_connection, detect_alerts
import geopandas as gpd

# --------------------------- TAB CONTENT ---------------------------

def show_overview_tab():
    st.markdown("""
        <div style='padding: 16px 0 24px 0'>
            <h2 style='color: #2d3436; margin:0; font-size:2.1em'>
                📊 Station Distribution by Project
            </h2>
            <p style='color: #636e72; margin:0; font-size:1.1em'>
                Distribution of monitoring stations across projects
            </p>
        </div>
    """, unsafe_allow_html=True)

    # Hardcoded data for each station type - moved outside function if possible
    stations_data = [
        {
            "name": "River",
            "total": 95,
            "projects": {
                "Kokan": 21,
                "Tapi": 19,
                "Godavari Lower": 18,
                "Krishna Bhima": 11,
                "Godavari": 26
            }
        },
        {
            "name": "Dam",
            "total": 172,
            "projects": {
                "Kokan": 11,
                "Tapi": 35,
                "Godavari Lower": 61,
                "Krishna Bhima": 8,
                "Godavari": 57
            }
        },
        {
            "name": "EPAN",
            "total": 70,
            "projects": {
                "Kokan": 3,
                "Tapi": 6,
                "Godavari Lower": 11,
                "Krishna Bhima": 18,
                "Godavari": 32
            }
        },
        {
            "name": "AWS",
            "total": 29,
            "projects": {
                "Kokan": 4,
                "Tapi": 6,
                "Godavari Lower": 3,
                "Krishna Bhima": 6,
                "Godavari": 10
            }
        },
        {
            "name": "ARS",
            "total": 445,
            "projects": {
                "Kokan": 56,
                "Tapi": 95,
                "Godavari Lower": 48,
                "Krishna Bhima": 39,
                "Godavari": 207
            }
        },
        {
            "name": "Gate",
            "total": 173,
            "projects": {
                "Kokan": 6,
                "Tapi": 31,
                "Godavari Lower": 38,
                "Krishna Bhima": 14,
                "Godavari": 84
            }
        }
    ]

    # Create all pie charts first, then display in columns
    figs = []
    for station_info in stations_data:
        station_name = station_info["name"]
        total = station_info["total"]
        projects = station_info["projects"]
        
        project_names = list(projects.keys())
        counts = list(projects.values())
        
        # Create labels with count and percentage
        labels = []
        for name, count in projects.items():
            percent = (count / total) * 100
            labels.append(f"{name}<br>{count} ({percent:.1f}%)")

        fig = px.pie(
            names=project_names,
            values=counts,
            title=f'{station_name} Stations<br>Total: {total}',
            color_discrete_sequence=px.colors.sequential.Viridis,
            hole=0.35,
            height=400
        )
        
        fig.add_annotation(
            text=f"{station_name}<br>Total: {total}",
            x=0.5, y=0.5,
            font_size=16,
            showarrow=False
        )
        
        fig.update_traces(
            text=labels,
            textposition='inside',
            hovertemplate="<b>%{label}</b><br>Stations: %{value}",
            pull=[0.05 if count == max(counts) else 0 for count in counts],
            marker=dict(line=dict(color='#ffffff', width=2)))
        
        fig.update_layout(
            margin=dict(t=60, b=20, l=20, r=20),
            title_x=0.1,
            title_font_size=16,
            showlegend=False,
            uniformtext_minsize=10,
            uniformtext_mode='hide'
        )
        
        figs.append(fig)

    # Display all charts in columns
    cols = st.columns(2)
    for idx, fig in enumerate(figs):
        with cols[idx % 2]:
            st.plotly_chart(fig, use_container_width=True)

    # Chart interpretation guide
    with st.expander("📊 Chart Interpretation Guide"):
        st.markdown("""
            How to read these charts:
            - Each pie chart shows station distribution across projects
            - The largest segment is slightly pulled out for emphasis
            - The center shows total stations of that type
            - Each segment shows project name, station count, and percentage
            - Hover over segments for additional details
        """)

    st.markdown("---")
    st.markdown("## 🌀 Maharashtra Water Monitoring Network")
    
    # Add a button to load the map and alerts
    if st.button("🗺 Show Station Locations Overview", type="primary"):
        with st.spinner("Loading station locations and alerts..."):
            show_map_and_alerts()

def show_map_and_alerts():
    """Function to show the map chart and alerts (only called when button is clicked)"""
    st.markdown("### Station Locations Overview")

    # Load master tables - cache this if possible
    master_tables = fetch_master_tables()
    if not master_tables:
        st.error("Failed to load master tables")
        return

    # Get locations data and simplified mapping
    locations_df = master_tables['locations']
    simplified_mapping = master_tables['simplified_categories']
    
    # Pre-process data for efficiency
    locations_df['simplified_category'] = locations_df['station_type_id'].map(simplified_mapping)
    projects_df = master_tables['projects']
    project_id_to_name = dict(zip(projects_df['mst_project_id'], projects_df['mst_project_name']))
    
    # Load recent data for each station type and detect alerts - parallelize if possible
    alert_data = []
    progress_bar = st.progress(0)
    total_steps = len(locations_df['simplified_category'].unique())
    
    # Pre-calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    for i, category in enumerate(locations_df['simplified_category'].unique()):
        progress_bar.progress((i + 1) / total_steps, text=f"Checking {category} stations for alerts...")
        
        # Get station IDs for this category
        station_ids = locations_df[locations_df['simplified_category'] == category]['location_id'].tolist()
        
        # Load recent data (last 7 days) in batches if needed
        data = load_station_data(category, station_ids, start_date, end_date)
        
        if not data.empty:
            # Detect alerts
            alerts = detect_alerts(category, data)
            
            # Process alerts
            for alert in alerts:
                station_id = alert['location_id']
                station_details = locations_df[locations_df['location_id'] == station_id].iloc[0]
                
                # Handle alert time formatting more efficiently
                alert_time = alert.get('last_updated', alert.get('data_date', 'N/A'))
                if isinstance(alert_time, str):
                    try:
                        alert_time = pd.to_datetime(alert_time, dayfirst=True, errors='coerce')
                        alert_time = alert_time.strftime('%Y-%m-%d %H:%M:%S') if not pd.isna(alert_time) else 'N/A'
                    except:
                        alert_time = 'N/A'
                elif isinstance(alert_time, (pd.Timestamp, datetime)):
                    alert_time = alert_time.strftime('%Y-%m-%d %H:%M:%S')
                
                alert_data.append({
                    'Remote Station Id': station_id,
                    'Remote Station Name': station_details['location_name'],
                    'Project Id': station_details['project_id'],
                    'Project': project_id_to_name.get(station_details['project_id'], 'Unknown'),
                    'Station Type Id': station_details['station_type_id'],
                    'Station Type': category,
                    'Alert Type': alert['alert_type'],
                    'Alert Value': str(alert.get('alert_value', 'N/A')),
                    'Alert Time': alert_time,
                    'Latitude': station_details['mst_latitude'],
                    'Longitude': station_details['mst_longitude']
                })
    
    progress_bar.empty()
    
    # Create alerts DataFrame more efficiently
    alerts_df = pd.DataFrame(alert_data) if alert_data else pd.DataFrame()
    
    # KML Boundary Loading Function - keep cached
    @st.cache_data
    def load_boundary(file_path='maharashtra_boundary.kml'):
        try:
            gdf = gpd.read_file(file_path, driver='KML')
            if gdf.empty:
                return None
            
            geometry = gdf.geometry.iloc[0]
            
            if geometry.geom_type == 'MultiPolygon':
                all_coords = []
                for polygon in geometry.geoms:
                    if polygon.geom_type == 'Polygon':
                        coords = list(polygon.exterior.coords)
                        all_coords.extend([(y, x) for x, y in coords])
                        all_coords.append((None, None))
                return all_coords
            
            elif geometry.geom_type == 'Polygon':
                coords = list(geometry.exterior.coords)
                return [(y, x) for x, y in coords]
            else:
                return None
                
        except Exception as e:
            st.error(f"Error loading boundary file: {e}")
            return None

    # Create the map
    fig = go.Figure()

    # Load KML boundary - cache this if called multiple times
    boundary_coords = load_boundary('maharashtra_boundary.kml')
    
    if boundary_coords:
        lats = [coord[0] for coord in boundary_coords if coord[0] is not None]
        lons = [coord[1] for coord in boundary_coords if coord[1] is not None]
        
        fig.add_trace(go.Scattermapbox(
            lat=lats,
            lon=lons,
            mode="lines",
            line=dict(width=3, color="rgba(128, 0, 0, 0.8)"),
            hoverinfo="none",
            showlegend=False
        ))

    # Create alert station IDs set for faster lookup
    alert_station_ids = set(alerts_df['Remote Station Id'].unique()) if not alerts_df.empty else set()
    
    # Split stations more efficiently
    normal_mask = ~locations_df['location_id'].isin(alert_station_ids)
    normal_stations = locations_df[normal_mask]
    alert_stations = locations_df[~normal_mask]
    
    # Add normal stations as blue dots
    if not normal_stations.empty:
        hover_texts = [
            f"<b>{row['location_name']}</b><br>ID: {row['location_id']}<br>"
            f"Project: {project_id_to_name.get(row['project_id'], 'Unknown')}<br>"
            f"Type: {simplified_mapping.get(row['station_type_id'], 'Unknown')}"
            for _, row in normal_stations.iterrows()
        ]
        
        fig.add_trace(go.Scattermapbox(
            lat=normal_stations["mst_latitude"],
            lon=normal_stations["mst_longitude"],
            mode="markers",
            marker=dict(size=8, color="blue", opacity=0.7),
            name="Normal Stations",
            hovertext=hover_texts,
            hoverinfo="text"
        ))
    
    # Add alert stations as red dots if there are any alerts
    if not alert_stations.empty and not alerts_df.empty:
        # Merge alert details more efficiently
        alert_details = alerts_df.set_index('Remote Station Id')
        alert_stations = alert_stations.join(alert_details, on='location_id', how='left')
        
        hover_texts = [
            f"<b>ALERT: {row['location_name']}</b><br>"
            f"ID: {row['location_id']}<br>"
            f"Project: {project_id_to_name.get(row['project_id'], 'Unknown')}<br>"
            f"Type: {simplified_mapping.get(row['station_type_id'], 'Unknown')}<br>"
            f"<span style='color:red'>{row['Alert Type']}: {row['Alert Value']}</span><br>"
            f"Last Alert: {row['Alert Time']}"
            for _, row in alert_stations.iterrows()
        ]
        
        fig.add_trace(go.Scattermapbox(
            lat=alert_stations["mst_latitude"],
            lon=alert_stations["mst_longitude"],
            mode="markers",
            marker=dict(size=6, color="red"),
            name="Alert Stations",
            hovertext=hover_texts,
            hoverinfo="text"
        ))
    
    # Configure map layout
    fig.update_layout(
        mapbox_style="carto-positron",
        mapbox_zoom=6,
        mapbox_center={"lat": 19.7515, "lon": 75.7139},
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
        height=650,
        title="<b>Water Monitoring Station Locations</b><br><sup>Red markers indicate active alerts</sup>",
        title_x=0.05,
        title_font_size=18,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        )
    )
    
    # Display the map
    st.plotly_chart(fig, use_container_width=True)
    
    # Display station and alert summary
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Stations", len(locations_df))
    
    with col2:
        alert_count = len(alerts_df) if not alerts_df.empty else 0
        st.metric("Active Alerts", alert_count, delta_color="inverse")
    
    # Alert details expander
    if not alerts_df.empty:
        with st.expander("🚨 View Active Alert Details"):
            # Format the alerts for display more efficiently
            display_alerts = alerts_df[[
                'Remote Station Id', 
                'Remote Station Name', 
                'Project',
                'Station Type',
                'Alert Type',
                'Alert Value',
                'Alert Time'
            ]].copy()
            
            display_alerts['Alert Time'] = pd.to_datetime(
                display_alerts['Alert Time'], 
                errors='coerce',
                dayfirst=True
            )
            
            display_alerts = display_alerts.sort_values('Alert Time', ascending=False)
            display_alerts['Alert Time'] = display_alerts['Alert Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            st.dataframe(
                display_alerts,
                column_config={
                    "Remote Station Id": "Station ID",
                    "Remote Station Name": "Station Name",
                    "Alert Type": "Alert Type",
                    "Alert Value": "Value",
                    "Alert Time": "Time"
                },
                hide_index=True,
                use_container_width=True
            )