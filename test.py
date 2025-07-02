import streamlit as st
import extra_streamlit_components as stx
from streamlit_modal import Modal
import time
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import re
import io
import numpy as np
import mysql.connector
from mysql.connector import Error
from sqlalchemy import create_engine
from urllib.parse import quote_plus
import plotly.graph_objects as go
from auth import authenticate_user, check_admin_credentials
from db import create_user, get_user
import hashlib
from sqlalchemy import create_engine
from psycopg2 import sql  # Add this import
from sqlalchemy import text  # Add this import at the top of your file



from streamlit import config as _config
_config.set_option("theme.base", "light")





# --------------------------- CONSTANTS ---------------------------
STATION_TYPE_MAPPING = {
    'ARS': 1,
    'AWS': 6,
    'River': 2,
    'Dam': 3,
    'Gate': 5,
    'EPAN': 4
}


DATA_SOURCES = {
    "River": "river_data",
    "Dam": "dam_data",
    "EPAN": "epan_data",
    "AWS": "aws_data",
    "ARS": "ars_data",
    "Gate": "gate_data"
}

MAHARASHTRA_LOCATIONS = {
    # Major cities
    "Mumbai": (19.0760, 72.8777),
    "Pune": (18.5204, 73.8567),
    "Nagpur": (21.1458, 79.0882),
    "Nashik": (20.0059, 73.7910),
    "Aurangabad": (19.8762, 75.3433),
    "Solapur": (17.6599, 75.9064),
    "Amravati": (20.9374, 77.7796),
    "Kolhapur": (16.7050, 74.2433),
    # River basins
    "Godavari Basin": (19.9249, 74.3785),
    "Krishna Basin": (17.0000, 74.0000),
    "Tapi Basin": (21.0000, 75.0000),
    # Major dams
    "Koyna Dam": (17.4000, 73.7500),
    "Jayakwadi Dam": (19.4950, 75.3767),
    "Ujani Dam": (18.0833, 75.1167),
    "Bhandardara Dam": (19.5400, 73.7500),
    # Other important locations
    "Konkan Region": (17.0000, 73.0000),
    "Marathwada": (18.5000, 76.5000),
    "Vidarbha": (21.0000, 78.0000),
}

# --------------------------- PAGE CONFIG ---------------------------

st.set_page_config(
    page_title="HydroAnalytics Pro",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)
col1, col2, col3 = st.columns([1, 3, 1])  # Adjust 3 to control visual width

with col2:
    st.image("strip.png", width=800)
    
def create_db_connection():
    try:
        password = "22BCI0023"
        connection_string = f"mysql+mysqlconnector://root:{password}@localhost:3306/masterdb"
        engine = create_engine(connection_string)
        return engine
    except Exception as e:
        st.error(f"Error connecting to MySQL database: {e}")
        return None

@st.cache_data(ttl=60)
def fetch_master_tables():
    """Load all master tables into a dictionary"""
    engine = create_db_connection()
    if not engine:
        return None
    
    master_tables = {}
    
    try:
        # Load mst_project (correct column names)
        master_tables['projects'] = pd.read_sql(
            "SELECT mst_project_id, mst_project_name FROM masterprojectdetails", engine)
        
        # Load mst_station_type (correct column names)
        master_tables['station_types'] = pd.read_sql(
            "SELECT mst_station_type_id, mst_station_type_name FROM masterremotestationtype", engine)
        
        # Load ms_location (correct column names)
        master_tables['locations'] = pd.read_sql(
            """SELECT mst_remote_station_id AS location_id, 
                      mst_remote_station_name AS location_name, 
                      mst_station_type_id AS station_type_id, 
                      mst_project_id AS project_id, 
                      mst_latitude, 
                      mst_longitude 
               FROM masterremotelocation""", engine)
        
        # Create station type mapping for filtering
        station_type_mapping = {}
        for _, row in master_tables['station_types'].iterrows():
            type_name = row['mst_station_type_name']
            if '+' in type_name:
                base_types = [t.strip() for t in type_name.split('+')]
                for base_type in base_types:
                    if base_type not in station_type_mapping:
                        station_type_mapping[base_type] = []
                    station_type_mapping[base_type].append(row['mst_station_type_id'])
            else:
                if type_name not in station_type_mapping:
                    station_type_mapping[type_name] = []
                station_type_mapping[type_name].append(row['mst_station_type_id'])
        
        master_tables['station_type_mapping'] = station_type_mapping
        
        # Create simplified station type categories
        simplified_categories = {
            'ARS': ['ARS'],
            'AWS': ['AWS'],
            'River': ['AWLG-River'],
            'Dam': ['AWLG-Dam'],
            'Gate': ['Gate'],
            'EPAN': ['EPAN', 'E-Pan']
        }
        
        # Create reverse mapping from station type IDs to simplified categories
        simplified_mapping = {}
        for category, types in simplified_categories.items():
            for type_name in types:
                if type_name in station_type_mapping:
                    for type_id in station_type_mapping[type_name]:
                        simplified_mapping[type_id] = category
        
        master_tables['simplified_categories'] = simplified_mapping
        
        return master_tables
    
    except Exception as e:
        st.error(f"Error loading master tables: {e}")
        return None
    finally:
        if engine:
            engine.dispose()

def get_data_table_name(simplified_category):
    """Map simplified category to corresponding data table"""
    simplified_category = simplified_category.lower()
    if simplified_category == 'ars':
        return 'ars_data'
    elif simplified_category == 'aws':
        return 'aws_data'
    elif simplified_category == 'river':
        return 'river_data'
    elif simplified_category == 'epan':
        return 'epan_data'
    elif simplified_category == 'gate':
        return 'gate_data'
    elif simplified_category == 'dam':
        return 'dam_data'
    else:
        return None

def convert_varchar_to_datetime(date_str):
    """Convert date string in 'dd/mm/yyyy HH:MM' format to datetime object"""
    try:
        return datetime.strptime(date_str, '%d/%m/%Y %H:%M')
    except:
        return None

@st.cache_data(ttl=60)
def load_station_data(simplified_category, location_ids=None, start_date=None, end_date=None):
    """Load data from the appropriate table based on simplified category"""
    data_table = get_data_table_name(simplified_category)
    if not data_table:
        st.error(f"No data table mapped for category: {simplified_category}")
        return pd.DataFrame()
    
    engine = create_db_connection()
    if not engine:
        return pd.DataFrame()
    
    try:
        # First get all data for the selected locations (without date filter)
        query = f"SELECT * FROM {data_table}"
        conditions = []
        params = {}
        
        # Handle location filter
        if location_ids:
            if len(location_ids) == 1:
                conditions.append("location_id = :location_id")
                params['location_id'] = location_ids[0]
            else:
                placeholders = ",".join([f":loc_{i}" for i in range(len(location_ids))])
                conditions.append(f"location_id IN ({placeholders})")
                params.update({f"loc_{i}": loc_id for i, loc_id in enumerate(location_ids)})
        
        # Combine conditions if any exist
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        # Execute the query with parameters
        with engine.connect() as connection:
            result = connection.execute(text(query), params)
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
        
        if df.empty:
            return df
        
        # Now handle date filtering based on table type
        date_column = 'last_updated' if 'last_updated' in df.columns else 'data_date'
        
        if simplified_category.lower() == 'ars':
            # ARS table has proper DATETIME format
            df[date_column] = pd.to_datetime(df[date_column])
            if start_date and end_date:
                mask = (df[date_column] >= pd.to_datetime(start_date)) & \
                       (df[date_column] <= pd.to_datetime(end_date))
                df = df.loc[mask]
        else:
            # Other tables have VARCHAR dates in 'dd/mm/yyyy HH:MM' format
            # Convert to datetime first
            df['converted_date'] = df[date_column].apply(convert_varchar_to_datetime)
            df = df.dropna(subset=['converted_date'])
            
            if start_date and end_date:
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date) + timedelta(days=1)  # Include entire end day
                mask = (df['converted_date'] >= start_dt) & (df['converted_date'] <= end_dt)
                df = df.loc[mask]
            
            # Drop the temporary column
            df = df.drop(columns=['converted_date'])
        
        return df
    
    except Exception as e:
        st.error(f"Error loading {data_table} data: {str(e)}")
        return pd.DataFrame()
    finally:
        if engine:
            engine.dispose()

            
            
# --------------------------- AUTHENTICATION ---------------------------
def login_page():
    """Render the login page and handle authentication"""
    with st.container():
        st.title("Dashboard")
        
        # Initialize session state
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'is_admin' not in st.session_state:
            st.session_state.is_admin = False
        if 'username' not in st.session_state:
            st.session_state.username = None
        
        if st.session_state.authenticated:
            return True
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit_button = st.form_submit_button("Login")
            
            if submit_button:
                user = authenticate_user(username, password)
                if user:
                    st.session_state.authenticated = True
                    st.session_state.is_admin = user["is_admin"]
                    st.session_state.username = username
                    st.success("Login successful!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Invalid username or password")
        
        if not st.session_state.authenticated and st.button("Admin Login"):
            st.session_state.admin_login = True
        
        if st.session_state.get('admin_login', False):
            with st.form("admin_login_form"):
                st.subheader("Admin Authentication")
                admin_username = st.text_input("Admin Username")
                admin_password = st.text_input("Admin Password", type="password")
                admin_submit = st.form_submit_button("Authenticate as Admin")
                
                if admin_submit:
                    if check_admin_credentials(admin_username, admin_password):
                        st.session_state.admin_authenticated = True
                        st.session_state.admin_username = admin_username
                        st.success("Admin authentication successful!")
                    else:
                        st.error("Invalid admin credentials")
            
        if st.session_state.get('admin_authenticated', False):
            st.subheader("User Management")
            
            with st.expander("Create New User", expanded=True):
                with st.form("create_user_form"):
                    new_username = st.text_input("New Username")
                    new_password = st.text_input("New Password", type="password")
                    is_admin = st.checkbox("Is Admin?")
                    create_button = st.form_submit_button("Create User")
                    
                    if create_button:
                        if create_user(new_username, new_password, is_admin):
                            st.success(f"User {new_username} created successfully!")
                        else:
                            st.error("Failed to create user (username may already exist)")
            
            if st.button("Back to Login"):
                st.session_state.admin_login = False
                st.session_state.admin_authenticated = False
                st.rerun()
        
        return st.session_state.authenticated

# --------------------------- UI COMPONENTS ---------------------------
def render_sidebar():
    with st.sidebar:
        logo_path = Path(r"logo.png")
        st.image(str(logo_path), use_container_width=True)
        st.markdown("---")
        
        if st.button("🚪 Logout", key="logout_button", use_container_width=True):
            st.session_state['authenticated'] = False
            st.session_state.pop('username', None)
            st.success("Logged out successfully!")
            time.sleep(1)
            st.rerun()
    
        st.markdown("### 🛠 SYSTEM STATUS")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.markdown(f"""
            <div style='background: rgba(255,255,255,0.05); 
                        padding: 20px;
                        border-radius: 12px;
                        margin: 16px 0;
                        border: 1px solid #3d484d'>
                <div style='color: #b2bec3; font-size: 0.9em'>LAST UPDATED</div>
                <div style='color: white; font-size: 1.1em; margin: 8px 0'>{current_time}</div>
                <div style='margin: 16px 0'>
                    <div>
                        <div style='color: #b2bec3; font-size: 0.9em'>ACTIVE Locations</div>
                        <div style='color: white; font-size: 1.4em'>692</div>
                    </div>
                </div>
                <div style='height: 6px; background: #3d484d; border-radius: 3px'>
                    <div style='width: 85%; height: 100%; background: #0984e3; border-radius: 3px'></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

# Load all station data into a dictionary

def get_total_data_count():
    """Get the total number of rows across all data tables"""
    engine = create_db_connection()
    if engine is None:
        return 0
    
    total = 0
    try:
        for table_name in DATA_SOURCES.values():
            # Get row count using pandas
            count = pd.read_sql(f"SELECT COUNT(*) as count FROM {table_name}", engine)['count'].iloc[0]
            total += count
        return total
    except Exception as e:
        st.error(f"Error counting database rows: {e}")
        return 0
    finally:
        if engine:
            engine.dispose()

# Load all station data into a dictionary
def render_top_metrics():
    # Get the total data count from database
    total_data_count = get_total_data_count()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-card-icon">
                    <span>🌍</span>
                </div>
                <div class="metric-card-value">692</div>
                <div class="metric-card-label">Active Locations</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-card-icon">
                    <span>📊</span>
                </div>
                <div class="metric-card-value">{total_data_count:,}</div>
                <div class="metric-card-label">Total Data Entries</div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-card-icon">
                    <span>⚡</span>
                </div>
                <div class="metric-card-value">{datetime.now().strftime('%H:%M')}</div>
                <div class="metric-card-label">Last Updated</div>
            </div>
        """, unsafe_allow_html=True)

# --------------------------- TAB CONTENT ---------------------------
def show_overview_tab():
    st.markdown("""
        <div style='padding: 16px 0 24px 0'>
            <h2 style='color: #2d3436; margin:0; font-size:2.1em'>
                📊 Project Data Distribution Analysis
            </h2>
            <p style='color: #636e72; margin:0; font-size:1.1em'>
                Distribution of monitoring data across projects for each station
            </p>
        </div>
    """, unsafe_allow_html=True)

    # Load data for stations with project info
    stations_with_data = []
    for station_name in DATA_SOURCES:
        with st.spinner(f"Loading {station_name} data..."):
            df = load_station_data(station_name)
            if not df.empty and 'project_name' in df.columns:
                stations_with_data.append((station_name, df))

    if stations_with_data:
        cols = st.columns(2)
        for idx, (station_name, df) in enumerate(stations_with_data):
            try:
                project_counts = df['project_name'].value_counts().reset_index()
                project_counts.columns = ['Project', 'Count']
                total_records = project_counts['Count'].sum()
                
                # Create custom labels with both count and percentage
                labels = []
                for _, row in project_counts.iterrows():
                    percent = row['Count'] / total_records * 100
                    labels.append(f"{row['Project']}<br>{row['Count']}")
                
                fig = px.pie(
                    project_counts,
                    names='Project',
                    values='Count',
                    title=f'{station_name} Station<br>Project Distribution',
                    color_discrete_sequence=px.colors.sequential.Viridis,
                    hole=0.35,
                    height=400
                )
                
                # Add center annotation with total records
                fig.add_annotation(
                    text=f"Total:<br>{total_records}",
                    x=0.5, y=0.5,
                    font_size=16,
                    showarrow=False
                )
                
                fig.update_traces(
                    text=labels,
                    textposition='inside',
                    hovertemplate="<b>%{label}</b><br>Records: %{value}",
                    pull=[0.05 if i == project_counts['Count'].idxmax() else 0 for i in range(len(project_counts))],
                    marker=dict(line=dict(color='#ffffff', width=2))
                )
                
                fig.update_layout(
                    margin=dict(t=60, b=20, l=20, r=20),
                    title_x=0.1,
                    title_font_size=16,
                    showlegend=False,
                    uniformtext_minsize=10,
                    uniformtext_mode='hide'
                )

                with cols[idx % 2]:
                    st.plotly_chart(fig, use_container_width=True)
                    
            except Exception as e:
                continue
    else:
        st.warning("No project data available for any station")

    with st.expander("📊 Chart Interpretation Guide"):
        st.markdown("""
            How to read these charts:
            - Each pie chart shows how data is distributed across projects for a specific station
            - The largest segment is slightly pulled out for emphasis
            - The center shows total records for that station
            - Each segment shows project name, record count, and percentage
            - Hover over segments for additional details
        """)

    st.markdown("---")
    st.markdown("## 🌀 Maharashtra Water Monitoring Network")
    st.markdown("### Station Status with Alert Indicators")
    
    # Function to get alerts for a station
    def get_station_alerts(station_id, df):
        alerts = []
        
        if df.empty or 'timestamp' not in df.columns:
            return alerts
            
        try:
            # Convert to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Check battery voltage for all station types
            if 'battery_voltage' in df.columns:
                battery_voltage = pd.to_numeric(df['battery_voltage'], errors='coerce')
                if battery_voltage.min() < 10.5:
                    alerts.append("Low Battery (<10.5V)")
            
            # Get station type from metadata
            station_meta = stations_df[stations_df["Remote Station Id"] == station_id]
            if station_meta.empty:
                return alerts
                
            station_type_id = station_meta.iloc[0]['Sation Type Id']
            station_type = STATION_TYPE_MAPPING.get(station_type_id, "UNKNOWN")
            
            # EPAN station alerts
            if station_type == "EPAN":
                if 'epan' in df.columns:
                    epan_values = pd.to_numeric(df['epan'], errors='coerce')
                    
                    # Check for values in 0-50 or 200+
                    if any((epan_values >= 0) & (epan_values <= 50)) or any(epan_values >= 200):
                        alerts.append("EPAN Value Alert (0-50 or 200+)")
                    
                    # Check day-to-day difference >15mm
                    daily_epan = epan_values.resample('D', on=df['timestamp']).mean()
                    daily_diff = daily_epan.diff().abs()
                    if any(daily_diff > 15):
                        alerts.append("EPAN Daily Change >15mm")
                    
                    # Check if last 4 days have same value
                    if len(daily_epan) >= 4:
                        last_4 = daily_epan.iloc[-4:]
                        if last_4.nunique() == 1:  # All values are the same
                            alerts.append("EPAN Same Value for 4 Days")
            
            # GATE station alerts
            elif station_type == "GATE":
                # Find gate columns (any column with 'gate' in name)
                gate_cols = [col for col in df.columns if 'gate' in col.lower()]
                for col in gate_cols:
                    gate_values = pd.to_numeric(df[col], errors='coerce')
                    if any(gate_values > 0):
                        alerts.append(f"Gate Open ({col})")
                        break  # Only need one gate open to trigger alert
            
            # RIVER and DAM station alerts
            elif station_type in ["RIVER", "DAM"]:
                if 'water_level' in df.columns:
                    water_level = pd.to_numeric(df['water_level'], errors='coerce')
                    
                    # Check day-to-day difference >1m
                    daily_level = water_level.resample('D', on=df['timestamp']).mean()
                    daily_diff = daily_level.diff().abs()
                    if any(daily_diff > 1):
                        alerts.append("Water Level Change >1m")
            
            # ARS station alerts
            elif station_type == "ARS":
                if 'daily_rain' in df.columns:
                    daily_rain = pd.to_numeric(df['daily_rain'], errors='coerce')
                    if any(daily_rain > 100):
                        alerts.append("Daily Rain >100mm")
                
                if 'hourly_rain' in df.columns:
                    hourly_rain = pd.to_numeric(df['hourly_rain'], errors='coerce')
                    if any(hourly_rain > 100):
                        alerts.append("Hourly Rain >100mm")
            
            # AWS station alerts
            elif station_type == "AWS":
                # Sensor check
                sensors = ['wind_speed', 'wind_direction', 'atm_pressure', 
                          'temperature', 'humidity', 'solar_radiation']
                for sensor in sensors:
                    if sensor in df.columns:
                        sensor_values = pd.to_numeric(df[sensor], errors='coerce')
                        if any(sensor_values == 0):
                            alerts.append(f"{sensor} Zero Reading")
                
                # Rain check
                if 'daily_rain' in df.columns:
                    daily_rain = pd.to_numeric(df['daily_rain'], errors='coerce')
                    if any(daily_rain > 100):
                        alerts.append("Daily Rain >100mm")
                
                if 'hourly_rain' in df.columns:
                    hourly_rain = pd.to_numeric(df['hourly_rain'], errors='coerce')
                    if any(hourly_rain > 100):
                        alerts.append("Hourly Rain >100mm")
                        
        except Exception as e:
            st.error(f"Error processing alerts for {station_id}: {str(e)}")
        
        return alerts

    # Station type mapping
    STATION_TYPE_MAPPING = {
        1: "EPAN",
        2: "GATE",
        3: "RIVER",
        4: "DAM",
        5: "ARS",
        6: "AWS"
    }
    
    # Project mapping
    PROJECTS = {
        1: "Kokan",
        2: "Krishna Bhima",
        3: "Tapi",
        4: "Godavari",
        6: "Krishna Bhima-Non-NHP",
        7: "Godavari Lower"
    }
    
    # Load station metadata
    def load_station_metadata():
        return pd.DataFrame([
            {"Remote Station Id": "101B0008", "Remote Station Name": "Kashedi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.87916667, "Longitude": 73.42916667},
            {"Remote Station Id": "101B0010", "Remote Station Name": "Kond Fanasvane", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.43757664, "Longitude": 73.67167119},
            {"Remote Station Id": "101B0011", "Remote Station Name": "Jamda Project", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.43757664, "Longitude": 73.67167119},
            {"Remote Station Id": "101B0014", "Remote Station Name": "Deoghar Dam", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.424773, "Longitude": 73.804044},
            {"Remote Station Id": "101B0016", "Remote Station Name": "Amboli", "Project Id": 1, "Sation Type Id": 1, "Latitude": 15.978281, "Longitude": 74.014476},
            {"Remote Station Id": "101B0017", "Remote Station Name": "Shirshingi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.013457, "Longitude": 73.956258},
            {"Remote Station Id": "101B0018", "Remote Station Name": "Virdi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 15.626944, "Longitude": 74.057829},
            {"Remote Station Id": "101B0019", "Remote Station Name": "Talamba", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.038034, "Longitude": 73.892773},
            {"Remote Station Id": "101B0020", "Remote Station Name": "Nardave", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.200813, "Longitude": 73.877104},
            {"Remote Station Id": "101B0021", "Remote Station Name": "Aruna", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.595788, "Longitude": 73.790558},
            {"Remote Station Id": "101B0023", "Remote Station Name": "Sarambal", "Project Id": 1, "Sation Type Id": 1, "Latitude": 15.874157, "Longitude": 73.898144},
            {"Remote Station Id": "101B0024", "Remote Station Name": "Karjat", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.912061, "Longitude": 73.329385},
            {"Remote Station Id": "73AE8326", "Remote Station Name": "Dhamni", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.35888889, "Longitude": 73.01194444},
            {"Remote Station Id": "73AE8DF4", "Remote Station Name": "Dugad", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.43611111, "Longitude": 73.03611111},
            {"Remote Station Id": "73AE9050", "Remote Station Name": "Goregaon", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.1075, "Longitude": 73.27666667},
            {"Remote Station Id": "73AE9E82", "Remote Station Name": "Kaman", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.38444444, "Longitude": 72.91055556},
            {"Remote Station Id": "73AEA5CA", "Remote Station Name": "Khapari", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.32444444, "Longitude": 73.59333333},
            {"Remote Station Id": "73AEAB18", "Remote Station Name": "Raghuwadi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.13777778, "Longitude": 73.42416667},
            {"Remote Station Id": "73AEB6BC", "Remote Station Name": "Sakurli", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.47388889, "Longitude": 73.61444444},
            {"Remote Station Id": "73AEB86E", "Remote Station Name": "Shelavali", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.37666667, "Longitude": 73.47916667},
            {"Remote Station Id": "73AEC02C", "Remote Station Name": "Tulai", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.21888889, "Longitude": 73.50222222},
            {"Remote Station Id": "73AECEFE", "Remote Station Name": "Manor", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.75, "Longitude": 72.9166},
            {"Remote Station Id": "73AED35A", "Remote Station Name": "Chinchara", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.8475, "Longitude": 72.85611111},
            {"Remote Station Id": "73AEDD88", "Remote Station Name": "Somata", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.82305556, "Longitude": 72.95805556},
            {"Remote Station Id": "73AEE6C0", "Remote Station Name": "Khutal", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.71055556, "Longitude": 72.9675},
            {"Remote Station Id": "73AEE812", "Remote Station Name": "Savarkhand", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.60138889, "Longitude": 73.14944444},
            {"Remote Station Id": "73AEF5B6", "Remote Station Name": "Ogade", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.72055556, "Longitude": 73.26666667},
            {"Remote Station Id": "73AEFB64", "Remote Station Name": "Surymal", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.75444444, "Longitude": 73.3475},
            {"Remote Station Id": "73AF07C8", "Remote Station Name": "Umberpada", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.475, "Longitude": 73.07138889},
            {"Remote Station Id": "73AF091A", "Remote Station Name": "Akre", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.93888889, "Longitude": 73.13833333},
            {"Remote Station Id": "73AF14BE", "Remote Station Name": "Waki", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.17111111, "Longitude": 73.56777778},
            {"Remote Station Id": "73AF1A6C", "Remote Station Name": "Birwadi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.11083333, "Longitude": 73.52916667},
            {"Remote Station Id": "73AF2124", "Remote Station Name": "Varandoli", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.20388889, "Longitude": 73.40083333},
            {"Remote Station Id": "73AF2FF6", "Remote Station Name": "Kumbhe Dam", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.31138889, "Longitude": 73.37833333},
            {"Remote Station Id": "73AF3252", "Remote Station Name": "Sanderi Dam", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.08277778, "Longitude": 73.23777778},
            {"Remote Station Id": "73AF3C80", "Remote Station Name": "Kalamb", "Project Id": 1, "Sation Type Id": 1, "Latitude": 19.09277778, "Longitude": 73.39055556},
            {"Remote Station Id": "73AF44C2", "Remote Station Name": "Rajnala LBC", "Project Id": 1, "Sation Type Id": 1, "Latitude": 18.94, "Longitude": 73.42222222},
            {"Remote Station Id": "73AF4A10", "Remote Station Name": "Nandivase", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.54222222, "Longitude": 73.68833333},
            {"Remote Station Id": "73AF57B4", "Remote Station Name": "Karambavane", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.56888889, "Longitude": 73.41916667},
            {"Remote Station Id": "73AF5966", "Remote Station Name": "Chatav", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.76638889, "Longitude": 73.54055556},
            {"Remote Station Id": "73AF622E", "Remote Station Name": "Lavel", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.64944444, "Longitude": 73.47611111},
            {"Remote Station Id": "73AF6CFC", "Remote Station Name": "Dabhol", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.59194444, "Longitude": 73.17861111},
            {"Remote Station Id": "73AF7158", "Remote Station Name": "Poynar", "Project Id": 1, "Sation Type Id": 1, "Latitude": 17.77222222, "Longitude": 73.33333333},
            {"Remote Station Id": "73AF7F8A", "Remote Station Name": "Arjuna Dam", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.70166667, "Longitude": 73.71305556},
            {"Remote Station Id": "73AF92AA", "Remote Station Name": "Adivare", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.71555556, "Longitude": 73.36},
            {"Remote Station Id": "73AF9C78", "Remote Station Name": "Het", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.59383333, "Longitude": 73.77838889},
            {"Remote Station Id": "73AFA730", "Remote Station Name": "Kharepathan", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.55375, "Longitude": 73.62872222},
            {"Remote Station Id": "73AFA9E2", "Remote Station Name": "Sangulwadi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.48511111, "Longitude": 73.77180556},
            {"Remote Station Id": "73AFB446", "Remote Station Name": "Walawal", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.00472222, "Longitude": 73.60894444},
            {"Remote Station Id": "73AFBA94", "Remote Station Name": "Dukanwadi", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.03172222, "Longitude": 73.87655556},
            {"Remote Station Id": "73AFC2D6", "Remote Station Name": "Oras", "Project Id": 1, "Sation Type Id": 1, "Latitude": 16.11472222, "Longitude": 73.69333333},
            {"Remote Station Id": "73AFCC04", "Remote Station Name": "Pimpalgaon Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.31861111, "Longitude": 73.38361111},
            {"Remote Station Id": "73AFD1A0", "Remote Station Name": "Vashind Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.3975, "Longitude": 73.26611111},
            {"Remote Station Id": "73AFDF72", "Remote Station Name": "Gorha Borande Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.92083333, "Longitude": 73.05555556},
            {"Remote Station Id": "73AFE43A", "Remote Station Name": "Wada Manor Sapne Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.66666667, "Longitude": 73.08888889},
            {"Remote Station Id": "73AFEAE8", "Remote Station Name": "Mandwa-Pinjal Gargaon Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.72194444, "Longitude": 73.20527778},
            {"Remote Station Id": "73AFF74C", "Remote Station Name": "Wada-Manor Karalgaon Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.71916667, "Longitude": 72.94527778},
            {"Remote Station Id": "73AFF99E", "Remote Station Name": "Bhiwandi-Wada Ambadi Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.96638889, "Longitude": 73.12972222},
            {"Remote Station Id": "73B006C4", "Remote Station Name": "Surya River Charoti Naka Bridge NH-48", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.89805556, "Longitude": 72.94083333},
            {"Remote Station Id": "73B00816", "Remote Station Name": "Akale Bhorao Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 18.08888889, "Longitude": 73.47444444},
            {"Remote Station Id": "73B015B2", "Remote Station Name": "Pale-Mohapre Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 18.09444444, "Longitude": 73.41194444},
            {"Remote Station Id": "73B01B60", "Remote Station Name": "Poshir Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.09222222, "Longitude": 73.38694444},
            {"Remote Station Id": "73B02028", "Remote Station Name": "Sugave Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 19.03027778, "Longitude": 73.41136111},
            {"Remote Station Id": "73B02EFA", "Remote Station Name": "Jagbudi Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 17.71844444, "Longitude": 73.41713889},
            {"Remote Station Id": "73B0335E", "Remote Station Name": "Rajapur Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 16.64983333, "Longitude": 73.52422222},
            {"Remote Station Id": "73B03D8C", "Remote Station Name": "Nanivade Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 16.59177778, "Longitude": 73.69238889},
            {"Remote Station Id": "73B045CE", "Remote Station Name": "Sonar sakhali Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 15.979975, "Longitude": 73.74386389},
            {"Remote Station Id": "73AF81DC", "Remote Station Name": "Chiplun Vashithi", "Project Id": 1, "Sation Type Id": 2, "Latitude": 17.525759, "Longitude": 73.538374},
            {"Remote Station Id": "101B0028", "Remote Station Name": "Gaheli", "Project Id": 1, "Sation Type Id": 2, "Latitude": 20.095879, "Longitude": 73.270798},
            {"Remote Station Id": "101B0009", "Remote Station Name": "NH 66 Bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 17.87916667, "Longitude": 73.42916667},
            {"Remote Station Id": "101B0001", "Remote Station Name": "Savitri Bhoi ghat Mahad", "Project Id": 1, "Sation Type Id": 2, "Latitude": 18.077957, "Longitude": 73.418664},
            {"Remote Station Id": "101B0004", "Remote Station Name": "Roha Astami bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 18.4408, "Longitude": 73.11908},
            {"Remote Station Id": "101B0005", "Remote Station Name": "Pali bridge", "Project Id": 1, "Sation Type Id": 2, "Latitude": 18.5449, "Longitude": 73.2155},
            {"Remote Station Id": "101B0006", "Remote Station Name": "Nagothane K.T.Weir", "Project Id": 1, "Sation Type Id": 3, "Latitude": 18.5231, "Longitude": 73.1461},
            {"Remote Station Id": "101B0013", "Remote Station Name": "Tillari Dam", "Project Id": 1, "Sation Type Id": 3, "Latitude": 15.7601341, "Longitude": 74.0891247},
            {"Remote Station Id": "101B0027", "Remote Station Name": "Vandri Medium Project", "Project Id": 1, "Sation Type Id": 3, "Latitude": 19.614573, "Longitude": 72.937894},
            {"Remote Station Id": "101B0025", "Remote Station Name": "Hetawane Dam", "Project Id": 1, "Sation Type Id": 3, "Latitude": 18.72219, "Longitude": 73.181093},
            {"Remote Station Id": "73B07E86", "Remote Station Name": "Natuwadi Dam", "Project Id": 1, "Sation Type Id": 3, "Latitude": 17.831837, "Longitude": 73.398497},
            {"Remote Station Id": "73B06322", "Remote Station Name": "Surya Dam", "Project Id": 1, "Sation Type Id": 3, "Latitude": 19.92083333, "Longitude": 73.05555556},
            {"Remote Station Id": "73B04B1C", "Remote Station Name": "Bhatsanagar", "Project Id": 1, "Sation Type Id": 4, "Latitude": 19.51888889, "Longitude": 73.40888889},
            {"Remote Station Id": "73B056B8", "Remote Station Name": "Upper Vaitarna Dam", "Project Id": 1, "Sation Type Id": 4, "Latitude": 19.81805556, "Longitude": 73.50611111},
            {"Remote Station Id": "73B0586A", "Remote Station Name": "Surya Dam", "Project Id": 1, "Sation Type Id": 4, "Latitude": 19.92083333, "Longitude": 73.05555556},
            {"Remote Station Id": "73B06DF0", "Remote Station Name": "Surya Dam", "Project Id": 1, "Sation Type Id": 5, "Latitude": 19.92083333, "Longitude": 73.05555556},
            {"Remote Station Id": "73B080D0", "Remote Station Name": "Natuwadi Dam", "Project Id": 1, "Sation Type Id": 5, "Latitude": 17.831837, "Longitude": 73.398497},
            {"Remote Station Id": "101B0026", "Remote Station Name": "Hetawane Dam", "Project Id": 1, "Sation Type Id": 5, "Latitude": 18.72219, "Longitude": 73.181093},
            {"Remote Station Id": "101B0030", "Remote Station Name": "Upper Vaitarna Dam", "Project Id": 1, "Sation Type Id": 5, "Latitude": 19.81813, "Longitude": 73.505721},
            {"Remote Station Id": "73AF8F0E", "Remote Station Name": "Arjuna Dam", "Project Id": 1, "Sation Type Id": 5, "Latitude": 16.70166667, "Longitude": 73.71305556},
            {"Remote Station Id": "101B0031", "Remote Station Name": "Bhatsanagar", "Project Id": 1, "Sation Type Id": 6, "Latitude": 19.519534, "Longitude": 73.409324},
            {"Remote Station Id": "101B0002", "Remote Station Name": "Birwadi", "Project Id": 1, "Sation Type Id": 6, "Latitude": 18.11194, "Longitude": 73.52889},
            {"Remote Station Id": "73B08E02", "Remote Station Name": "Suksale", "Project Id": 1, "Sation Type Id": 6, "Latitude": 19.79944444, "Longitude": 73.11777778},
            {"Remote Station Id": "73B07054", "Remote Station Name": "Natuwadi Dam", "Project Id": 1, "Sation Type Id": 6, "Latitude": 17.831837, "Longitude": 73.398497},
            {"Remote Station Id": "101B0003", "Remote Station Name": "Dolwahal Bandhara", "Project Id": 1, "Sation Type Id": 8, "Latitude": 18.426198, "Longitude": 73.220627},
            {"Remote Station Id": "101B0007", "Remote Station Name": "Gadnadi Project", "Project Id": 1, "Sation Type Id": 8, "Latitude": 17.282396, "Longitude": 73.637221},
            {"Remote Station Id": "101B0022", "Remote Station Name": "Korle Satardi", "Project Id": 1, "Sation Type Id": 8, "Latitude": 16.5068417, "Longitude": 73.5984424},
            {"Remote Station Id": "101B0029", "Remote Station Name": "Upper Vaitarna Dam", "Project Id": 1, "Sation Type Id": 8, "Latitude": 19.81813, "Longitude": 73.505721},
            {"Remote Station Id": "101B0012", "Remote Station Name": "Tillari Dam", "Project Id": 1, "Sation Type Id": 9, "Latitude": 15.7601341, "Longitude": 74.0891247},
            {"Remote Station Id": "101B0015", "Remote Station Name": "Deoghar Dam", "Project Id": 1, "Sation Type Id": 14, "Latitude": 16.424773, "Longitude": 73.804044},
            {"Remote Station Id": "1001", "Remote Station Name": "Dhom Dam Site", "Project Id": 2, "Sation Type Id": 1, "Latitude": 17.97305556, "Longitude": 73.82027778},
            {"Remote Station Id": "1002", "Remote Station Name": "Dhom Balkawadi Dam Site", "Project Id": 2, "Sation Type Id": 1, "Latitude": 17.89527778, "Longitude": 73.71055556},
            {"Remote Station Id": "1003", "Remote Station Name": "Dhom(Jambhali)", "Project Id": 2, "Sation Type Id": 1, "Latitude": 18.02638889, "Longitude": 73.715},
            {"Remote Station Id": "1004", "Remote Station Name": "Dhom Balkawadi(Jor)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.98138889, "Longitude": 73.67444444},
            {"Remote Station Id": "1005", "Remote Station Name": "Nagewadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.92222222, "Longitude": 73.83527778},
            {"Remote Station Id": "1006", "Remote Station Name": "Targaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.51305556, "Longitude": 74.15472222},
            {"Remote Station Id": "1007", "Remote Station Name": "Apshinge", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.61611111, "Longitude": 74.22833333},
            {"Remote Station Id": "1008", "Remote Station Name": "Shirdhon", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.67416667, "Longitude": 74.14222222},
            {"Remote Station Id": "1009", "Remote Station Name": "Ranjani", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.88527778, "Longitude": 73.79333333},
            {"Remote Station Id": "1010", "Remote Station Name": "Kanher(Malewadi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.7275, "Longitude": 73.91527778},
            {"Remote Station Id": "1011", "Remote Station Name": "Kanher(Moleshwar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.885, "Longitude": 73.725},
            {"Remote Station Id": "1012", "Remote Station Name": "Kanher(Medha)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.79416667, "Longitude": 73.8275},
            {"Remote Station Id": "1013", "Remote Station Name": "Urmodi(Sandvali)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.64083333, "Longitude": 73.83805556},
            {"Remote Station Id": "1014", "Remote Station Name": "Urmodi(Kas)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.71388889, "Longitude": 73.80916667},
            {"Remote Station Id": "1015", "Remote Station Name": "Nagthane", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.56611111, "Longitude": 74.04666667},
            {"Remote Station Id": "1016", "Remote Station Name": "Tarali(Thoseghar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.59916667, "Longitude": 73.86833333},
            {"Remote Station Id": "1017", "Remote Station Name": "Tarali", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.53361111, "Longitude": 73.89861111},
            {"Remote Station Id": "1018", "Remote Station Name": "Uttarmand (Padloshi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.42805556, "Longitude": 73.95444444},
            {"Remote Station Id": "1019", "Remote Station Name": "Koyna(Koyna Nagar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.38861111, "Longitude": 73.74111111},
            {"Remote Station Id": "101F0002", "Remote Station Name": "Chankhed", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.648568, "Longitude": 73.647714},
            {"Remote Station Id": "101F0003", "Remote Station Name": "Yavat", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.475133, "Longitude": 74.275111},
            {"Remote Station Id": "101F0007", "Remote Station Name": "Ahamadnagar", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.101053, "Longitude": 74.740677},
            {"Remote Station Id": "101F0008", "Remote Station Name": "Nher", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.74722222, "Longitude": 74.30111111},
            {"Remote Station Id": "101F0010", "Remote Station Name": "Rendal", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.61915, "Longitude": 74.42437},
            {"Remote Station Id": "101F0011", "Remote Station Name": "Agran Dhulgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.61388889, "Longitude": 74.99277778},
            {"Remote Station Id": "101F0016", "Remote Station Name": "Naldurg", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.81687, "Longitude": 76.27205556},
            {"Remote Station Id": "101F0017", "Remote Station Name": "Delawadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.34027778, "Longitude": 74.92730556},
            {"Remote Station Id": "101F0018", "Remote Station Name": "Anjandoh", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.35086111, "Longitude": 75.09541667},
            {"Remote Station Id": "101F0019", "Remote Station Name": "Saiyyad Warvade", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.71597222, "Longitude": 75.64022222},
            {"Remote Station Id": "101F0020", "Remote Station Name": "Bajar Bhogaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.75822222, "Longitude": 73.98327778},
            {"Remote Station Id": "101F0021", "Remote Station Name": "Gadhinglaj", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.22252778, "Longitude": 74.04491667},
            {"Remote Station Id": "101F0022", "Remote Station Name": "Kolik", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.7033333, "Longitude": 73.88086111},
            {"Remote Station Id": "101F0023", "Remote Station Name": "Ghanwde", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.57843611, "Longitude": 74.04106944},
            {"Remote Station Id": "101F0024", "Remote Station Name": "Kothali", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.58005, "Longitude": 74.13347222},
            {"Remote Station Id": "101F0025", "Remote Station Name": "Jambhare Dam", "Project Id": 2, "Station Type Id": 1, "Latitude": 15.88905556, "Longitude": 74.11238889},
            {"Remote Station Id": "1020", "Remote Station Name": "Koyna(Bamnoli)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.73194444, "Longitude": 73.76444444},
            {"Remote Station Id": "1021", "Remote Station Name": "Koyna(Navaja)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.44333333, "Longitude": 73.73111111},
            {"Remote Station Id": "1022", "Remote Station Name": "Koyna(Valawan)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.73277778, "Longitude": 73.60111111},
            {"Remote Station Id": "1023", "Remote Station Name": "Koyna(Kati)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.48666667, "Longitude": 73.81333333},
            {"Remote Station Id": "1024", "Remote Station Name": "Koyna(Pratapgad)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.9375, "Longitude": 73.57805556},
            {"Remote Station Id": "1025", "Remote Station Name": "Koyna(Sonat)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.83777778, "Longitude": 73.70888889},
            {"Remote Station Id": "1026", "Remote Station Name": "Surul", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.39416667, "Longitude": 73.90138889},
            {"Remote Station Id": "1027", "Remote Station Name": "Uttarmand(Chaphal)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.39638889, "Longitude": 74.01694444},
            {"Remote Station Id": "1028", "Remote Station Name": "Belewade", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.32694444, "Longitude": 73.92833333},
            {"Remote Station Id": "1029", "Remote Station Name": "Warana RBC", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.13805556, "Longitude": 73.8675},
            {"Remote Station Id": "1030", "Remote Station Name": "Warana(Dhangarwada)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.17472222, "Longitude": 73.87666667},
            {"Remote Station Id": "1031", "Remote Station Name": "Nivale", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.09722222, "Longitude": 73.76666667},
            {"Remote Station Id": "1032", "Remote Station Name": "Warana(Patherpunj)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.30083333, "Longitude": 73.69777778},
            {"Remote Station Id": "1033", "Remote Station Name": "Shigaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.87833333, "Longitude": 74.35916667},
            {"Remote Station Id": "1034", "Remote Station Name": "Satve Sawarde", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.90416667, "Longitude": 74.1125},
            {"Remote Station Id": "1035", "Remote Station Name": "Morna colony", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.98083333, "Longitude": 74.11638889},
            {"Remote Station Id": "1036", "Remote Station Name": "Ambawade – 1", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.26472222, "Longitude": 74.06388889},
            {"Remote Station Id": "1037", "Remote Station Name": "Kadvi Dam Site", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.00944444, "Longitude": 73.87},
            {"Remote Station Id": "1038", "Remote Station Name": "Jambhur", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.03611111, "Longitude": 73.9225},
            {"Remote Station Id": "1039", "Remote Station Name": "Kasari(Gajapur)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.88916667, "Longitude": 73.76194444},
            {"Remote Station Id": "1040", "Remote Station Name": "Borivade", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.83916667, "Longitude": 74.06666667},
            {"Remote Station Id": "1041", "Remote Station Name": "Revachiwadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.55194444, "Longitude": 73.87277778},
            {"Remote Station Id": "1042", "Remote Station Name": "Kumbhi Dam Site", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.52416667, "Longitude": 73.86194444},
            {"Remote Station Id": "1043", "Remote Station Name": "Gaganbawada", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.54888889, "Longitude": 73.79666667},
            {"Remote Station Id": "1044", "Remote Station Name": "Mandukali", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.64111111, "Longitude": 73.94},
            {"Remote Station Id": "1045", "Remote Station Name": "Tulshi(Padsali)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.75777778, "Longitude": 73.88056},
            {"Remote Station Id": "1046", "Remote Station Name": "Radhanagari(Dajipur)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.38444444, "Longitude": 73.865},
            {"Remote Station Id": "1047", "Remote Station Name": "Radhanagari(Hasne)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.35277778, "Longitude": 73.86222222},
            {"Remote Station Id": "1048", "Remote Station Name": "Radhanagari(Padali)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.41361111, "Longitude": 73.97},
            {"Remote Station Id": "1049", "Remote Station Name": "Bhagojipatilwadi (Keloshi BK.)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.95527778, "Longitude": 73.85555556},
            {"Remote Station Id": "1050", "Remote Station Name": "Dudhganga Nagar", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.35694444, "Longitude": 74.00666667},
            {"Remote Station Id": "1051", "Remote Station Name": "Dudhganga(Bhandane)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.33444444, "Longitude": 73.97},
            {"Remote Station Id": "1052", "Remote Station Name": "Dudhganga(Savarde)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.23805556, "Longitude": 73.97333333},
            {"Remote Station Id": "1053", "Remote Station Name": "Dudhganga(Waki)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.28611111, "Longitude": 74.0075},
            {"Remote Station Id": "1054", "Remote Station Name": "Yelgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.13194444, "Longitude": 74.02583333},
            {"Remote Station Id": "1055", "Remote Station Name": "Wathar", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.1925, "Longitude": 74.18138889},
            {"Remote Station Id": "1056", "Remote Station Name": "Wathar Station", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.88388889, "Longitude": 74.14416667},
            {"Remote Station Id": "1057", "Remote Station Name": "Mahabaleshwar", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.01472222, "Longitude": 74.18666667},
            {"Remote Station Id": "1058", "Remote Station Name": "Sangli", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.95194444, "Longitude": 74.60583333},
            {"Remote Station Id": "1059", "Remote Station Name": "Kirloskarwadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.08388889, "Longitude": 74.41444444},
            {"Remote Station Id": "1060", "Remote Station Name": "Siddhewadi (Krishna)", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.16416667, "Longitude": 74.76916667},
            {"Remote Station Id": "1061", "Remote Station Name": "Goregaon Wangi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.43666667, "Longitude": 74.32527778},
            {"Remote Station Id": "1062", "Remote Station Name": "Songe Bange", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.433205, "Longitude": 74.258172},
            {"Remote Station Id": "1063", "Remote Station Name": "Kagal", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.55444444, "Longitude": 74.31805556},
            {"Remote Station Id": "1064", "Remote Station Name": "Tandulwadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.68083333, "Longitude": 74.01611111},
            {"Remote Station Id": "1065", "Remote Station Name": "Nitawade", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.74583333, "Longitude": 74.14305556},
            {"Remote Station Id": "1067", "Remote Station Name": "Wadange (Rajaram Talav)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.71194444, "Longitude": 74.27222222},
            {"Remote Station Id": "1068", "Remote Station Name": "Chilewadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.34055556, "Longitude": 73.96916667},
            {"Remote Station Id": "1069", "Remote Station Name": "18.Pimpalgaon Joga(Madh)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.30583333, "Longitude": 73.82583333},
            {"Remote Station Id": "1070", "Remote Station Name": "18.Pimpalgaon Joga(Khireshwar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.3675, "Longitude": 73.81333333},
            {"Remote Station Id": "1071", "Remote Station Name": "Pimpalgaon Joga", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.31416667, "Longitude": 73.88194444},
            {"Remote Station Id": "1072", "Remote Station Name": "03.Panshet(Bhalwadi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.3425, "Longitude": 73.53222222},
            {"Remote Station Id": "1073", "Remote Station Name": "19.Manikdoh(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.24138889, "Longitude": 73.81611111},
            {"Remote Station Id": "1074", "Remote Station Name": "20.Yedgaon(Ozar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.20083333, "Longitude": 73.95777778},
            {"Remote Station Id": "1075", "Remote Station Name": "Askhed", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.82277778, "Longitude": 73.67166667},
            {"Remote Station Id": "1076", "Remote Station Name": "22.Dimbhe(Ahupe)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.17416667, "Longitude": 73.56805556},
            {"Remote Station Id": "1077", "Remote Station Name": "22.Dimbe(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.08611111, "Longitude": 73.75055556},
            {"Remote Station Id": "1078", "Remote Station Name": "09.Chaskman(Bhimashankar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.07277778, "Longitude": 73.53527778},
            {"Remote Station Id": "1079", "Remote Station Name": "22.Dimbhe(Asane)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.165, "Longitude": 73.67277778},
            {"Remote Station Id": "1080", "Remote Station Name": "22.Dimbhe(Rajapur)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.08972222, "Longitude": 73.6075},
            {"Remote Station Id": "1081", "Remote Station Name": "Chandoh", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.97166667, "Longitude": 74.17694444},
            {"Remote Station Id": "1082", "Remote Station Name": "Khodad", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.07416667, "Longitude": 74.04055556},
            {"Remote Station Id": "1083", "Remote Station Name": "22.Dimbhe(Ambegaon)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.11861111, "Longitude": 73.73333333},
            {"Remote Station Id": "1084", "Remote Station Name": "10.Bhama Askhed(Aundhe)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.95444444, "Longitude": 73.62805556},
            {"Remote Station Id": "1085", "Remote Station Name": "09.Chaskaman(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.95666667, "Longitude": 73.78388889},
            {"Remote Station Id": "1086", "Remote Station Name": "10.Bhama Askhed(Whiram)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.95861111, "Longitude": 73.59333333},
            {"Remote Station Id": "1087", "Remote Station Name": "10.Bhama Askhed(Koliye)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.89666667, "Longitude": 73.635},
            {"Remote Station Id": "1088", "Remote Station Name": "21.Wadaj(Amboli)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.94305556, "Longitude": 73.60805556},
            {"Remote Station Id": "1089", "Remote Station Name": "Bhama Askheda Dam", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.83305556, "Longitude": 73.72444444},
            {"Remote Station Id": "1090", "Remote Station Name": "09.Chaskman(Kharoshi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 19.02194444, "Longitude": 73.68},
            {"Remote Station Id": "1092", "Remote Station Name": "Nimgaon Ketki", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.08666667, "Longitude": 74.92861111},
            {"Remote Station Id": "1093", "Remote Station Name": "25.Ujjani(Palasdev)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.21666667, "Longitude": 73.88444444},
            {"Remote Station Id": "1094", "Remote Station Name": "Pabal", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.83861111, "Longitude": 74.06111111},
            {"Remote Station Id": "1095", "Remote Station Name": "Waki (BK)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.785, "Longitude": 73.87555556},
            {"Remote Station Id": "1096", "Remote Station Name": "Bhalawani", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.69777778, "Longitude": 75.12055556},
            {"Remote Station Id": "1097", "Remote Station Name": "08.Kalmodi(Ghotwadi )", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.98916667, "Longitude": 73.63361111},
            {"Remote Station Id": "1098", "Remote Station Name": "11.Andhra(Savale)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.95416667, "Longitude": 73.49027778},
            {"Remote Station Id": "1099", "Remote Station Name": "11.Andhra(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.78555556, "Longitude": 73.65055556},
            {"Remote Station Id": "1100", "Remote Station Name": "11.Andhra(Wadeshwar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.86055556, "Longitude": 73.5575},
            {"Remote Station Id": "1101", "Remote Station Name": "11.Andhra(Nigade)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.83027778, "Longitude": 73.64861111},
            {"Remote Station Id": "1102", "Remote Station Name": "Alandi", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.67972222, "Longitude": 73.88916667},
            {"Remote Station Id": "1103", "Remote Station Name": "12.Wadiwale", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.81861111, "Longitude": 73.515},
            {"Remote Station Id": "1104", "Remote Station Name": "Bhudhawadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.78805556, "Longitude": 73.54305556},
            {"Remote Station Id": "1105", "Remote Station Name": "Mhavhasi", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.05861111, "Longitude": 74.02111111},
            {"Remote Station Id": "1106", "Remote Station Name": "05.Pawana(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.34166667, "Longitude": 73.49361111},
            {"Remote Station Id": "1107", "Remote Station Name": "05.Pawana(Kole)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.67416667, "Longitude": 73.45916667},
            {"Remote Station Id": "1108", "Remote Station Name": "25.Ujjani(Tathwade)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.65694444, "Longitude": 73.72277778},
            {"Remote Station Id": "1109", "Remote Station Name": "06.Kasar Sai(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.61861111, "Longitude": 73.66444444},
            {"Remote Station Id": "1110", "Remote Station Name": "07.Mulshi(Kumbheri)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.58777778, "Longitude": 73.39777778},
            {"Remote Station Id": "1111", "Remote Station Name": "07.Mulshi(Davdi Camp)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.47194444, "Longitude": 73.44611111},
            {"Remote Station Id": "1112", "Remote Station Name": "25.Ujjani(Yerwada)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.55833333, "Longitude": 73.89444444},
            {"Remote Station Id": "1113", "Remote Station Name": "01.Temghar Dam Site", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.45416667, "Longitude": 73.54388889},
            {"Remote Station Id": "1114", "Remote Station Name": "04.Khadakwasala Dam Site", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.44722222, "Longitude": 73.77333333},
            {"Remote Station Id": "1115", "Remote Station Name": "16.Veer(Katraj Tunnel)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.39694444, "Longitude": 73.85777778},
            {"Remote Station Id": "1116", "Remote Station Name": "Khamgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.55944444, "Longitude": 74.21916667},
            {"Remote Station Id": "1117", "Remote Station Name": "02.Warasgaon(Dasawe)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.4, "Longitude": 73.49777778},
            {"Remote Station Id": "1118", "Remote Station Name": "03.Panshet(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.37972222, "Longitude": 73.61111111},
            {"Remote Station Id": "1119", "Remote Station Name": "03.Panshet(Shirkoli)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.35138889, "Longitude": 73.5625},
            {"Remote Station Id": "101F0027", "Remote Station Name": "Malkapur (Lalewadi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.936025, "Longitude": 73.93288889},
            {"Remote Station Id": "1120", "Remote Station Name": "02.Warasgaon(Goradwadi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.3975, "Longitude": 73.61722222},
            {"Remote Station Id": "1121", "Remote Station Name": "Kolgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.805, "Longitude": 74.66444444},
            {"Remote Station Id": "1122", "Remote Station Name": "Chichondi Patil (Sina Kolegaon)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.99805556, "Longitude": 74.91722222},
            {"Remote Station Id": "1123", "Remote Station Name": "Karmala (Sina Kolegaon)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.40888889, "Longitude": 75.19083333},
            {"Remote Station Id": "1124", "Remote Station Name": "Shrigonda", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.60555556, "Longitude": 74.69722222},
            {"Remote Station Id": "1125", "Remote Station Name": "13.Gunjawani(Ghisar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.29444444, "Longitude": 73.55638889},
            {"Remote Station Id": "1126", "Remote Station Name": "13.Gunjawani(Bhattiwaghdara)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.28305556, "Longitude": 73.55944444},
            {"Remote Station Id": "1127", "Remote Station Name": "16.Veer(Velhe)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.30222222, "Longitude": 73.64305556},
            {"Remote Station Id": "1128", "Remote Station Name": "14.Bhatghar (New Sangvi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.16777778, "Longitude": 73.86416667},
            {"Remote Station Id": "1129", "Remote Station Name": "14.Bhatghar(Pangari)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.19472222, "Longitude": 73.72666667},
            {"Remote Station Id": "1130", "Remote Station Name": "14.Bhatghar(Bhutonde)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.21472222, "Longitude": 73.65166667},
            {"Remote Station Id": "1131", "Remote Station Name": "14.Bhatghar(Kurunje)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.21666667, "Longitude": 73.70944444},
            {"Remote Station Id": "1132", "Remote Station Name": "16.Veer(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.12055556, "Longitude": 74.0975},
            {"Remote Station Id": "1133", "Remote Station Name": "15.Nira Deoghar(Shirgaon)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.09861111, "Longitude": 73.62888889},
            {"Remote Station Id": "1134", "Remote Station Name": "15.Nira Deoghar(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.10444444, "Longitude": 73.73138889},
            {"Remote Station Id": "1135", "Remote Station Name": "25.Ujjani(Khandala(Lonavala))", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.74638889, "Longitude": 73.37},
            {"Remote Station Id": "1136", "Remote Station Name": "16.Veer(Khengarewadi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.25138889, "Longitude": 74.06805556},
            {"Remote Station Id": "1137", "Remote Station Name": "15.Nira Deoghar(Shirvali )", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.08277778, "Longitude": 73.67472222},
            {"Remote Station Id": "1138", "Remote Station Name": "15.Nira Deoghar(Hirdoshi)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.11638889, "Longitude": 73.67},
            {"Remote Station Id": "1139", "Remote Station Name": "17.Nazare(Saswad)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.34916667, "Longitude": 74.02666667},
            {"Remote Station Id": "1140", "Remote Station Name": "Morgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.27444444, "Longitude": 74.32277778},
            {"Remote Station Id": "1141", "Remote Station Name": "16.Veer(Ambeghar)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.13527778, "Longitude": 73.79972222},
            {"Remote Station Id": "1142", "Remote Station Name": "Sansar", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.11666667, "Longitude": 74.69361111},
            {"Remote Station Id": "1143", "Remote Station Name": "Dharmpuri", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.935, "Longitude": 74.68611111},
            {"Remote Station Id": "1144", "Remote Station Name": "Banganga Dam", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.929766, "Longitude": 74.387097},
            {"Remote Station Id": "1145", "Remote Station Name": "Siddhewadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.55777778, "Longitude": 75.41111111},
            {"Remote Station Id": "1146", "Remote Station Name": "Madha (Pimpalgaon Joga)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.03416667, "Longitude": 75.52083333},
            {"Remote Station Id": "1147", "Remote Station Name": "Umadi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.42, "Longitude": 75.59583333},
            {"Remote Station Id": "1148", "Remote Station Name": "Andhali", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.75833333, "Longitude": 74.48},
            {"Remote Station Id": "1149", "Remote Station Name": "Mhaswad", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.63972222, "Longitude": 74.80555556},
            {"Remote Station Id": "1150", "Remote Station Name": "Diksal", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.90638889, "Longitude": 75.69444444},
            {"Remote Station Id": "1151", "Remote Station Name": "23.Ghod(Dam Site)", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.679528, "Longitude": 74.496626},
            {"Remote Station Id": "1152", "Remote Station Name": "Urmodi", "Project Id": 2, "Station Type Id": 1, "Latitude": 17.66222222, "Longitude": 73.90972222},
            {"Remote Station Id": "73BBE69E", "Remote Station Name": "Mulshi", "Project Id": 2, "Station Type Id": 1, "Latitude": 18.52194444, "Longitude": 73.51527778},
            {"Remote Station Id": "73BBE84C", "Remote Station Name": "Patgaon", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.12306, "Longitude": 73.93194},
            {"Remote Station Id": "73BC0758", "Remote Station Name": "Tulshi-ARG", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.52278, "Longitude": 74.01778},
            {"Remote Station Id": "73BC1AFC", "Remote Station Name": "Kitawade", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.06194, "Longitude": 74.04222},
            {"Remote Station Id": "73BC2F66", "Remote Station Name": "Ajara", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.10639, "Longitude": 74.20667},
            {"Remote Station Id": "73BC3C10", "Remote Station Name": "Nadagadwadi-ARG", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.01444, "Longitude": 74.40917},
            {"Remote Station Id": "73BC4452", "Remote Station Name": "Gargoti", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.31611, "Longitude": 74.13556},
            {"Remote Station Id": "73BC4A80", "Remote Station Name": "Jangamhatti-Dam", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.85833, "Longitude": 74.35},
            {"Remote Station Id": "73BC59F6", "Remote Station Name": "Chitri", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.07083, "Longitude": 74.15833},
            {"Remote Station Id": "73BCA7A0", "Remote Station Name": "Kadal", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.22222, "Longitude": 74.47028},
            {"Remote Station Id": "73BD3038", "Remote Station Name": "Tarewadi-ARG", "Project Id": 2, "Station Type Id": 1, "Latitude": 16.05167, "Longitude": 74.35111},
            {"Remote Station Id": "73BC814C", "Remote Station Name": "Nadagadwadi", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.01444, "Longitude": 74.40917},
            {"Remote Station Id": "73BC8F9E", "Remote Station Name": "Devikavatha", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.35080556, "Longitude": 76.03769444},
            {"Remote Station Id": "73BCB4D6", "Remote Station Name": "Walwan", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.76555556, "Longitude": 73.43194444},
            {"Remote Station Id": "73BCBA04", "Remote Station Name": "Shirawata", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.81027778, "Longitude": 73.48027778},
            {"Remote Station Id": "73BC71C8", "Remote Station Name": "Songe Bange-GD", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.433205, "Longitude": 74.258172},
            {"Remote Station Id": "73BC32C2", "Remote Station Name": "Kadal-GD", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.22222, "Longitude": 74.47028},
            {"Remote Station Id": "73BC21B4", "Remote Station Name": "Tarewadi", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.05167, "Longitude": 74.35111},
            {"Remote Station Id": "9001", "Remote Station Name": "Ujjani LBC", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.0675, "Longitude": 75.12},
            {"Remote Station Id": "9002", "Remote Station Name": "Kanher Canal", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.73694444, "Longitude": 73.91583333},
            {"Remote Station Id": "9003", "Remote Station Name": "Dhom Canal", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.97305556, "Longitude": 73.82027778},
            {"Remote Station Id": "9004", "Remote Station Name": "Warana Canal", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.14083333, "Longitude": 73.86555556},
            {"Remote Station Id": "9005", "Remote Station Name": "Veer LBC", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.12222222, "Longitude": 74.09666667},
            {"Remote Station Id": "9006", "Remote Station Name": "Veer RBC", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.12222222, "Longitude": 74.09666667},
            {"Remote Station Id": "9007", "Remote Station Name": "Khadakwasala", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.44194444, "Longitude": 73.76805556},
            {"Remote Station Id": "2001", "Remote Station Name": "Krishna Bridge (Sangam Mahuli)", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.68722222, "Longitude": 74.04972222},
            {"Remote Station Id": "2002", "Remote Station Name": "Navarasta (Sangavad Bridge)", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.33472222, "Longitude": 73.96194444},
            {"Remote Station Id": "2003", "Remote Station Name": "Shigaon", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.87138889, "Longitude": 74.355},
            {"Remote Station Id": "2004", "Remote Station Name": "Nitawade", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.74583333, "Longitude": 74.14305556},
            {"Remote Station Id": "2005", "Remote Station Name": "Balinga", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.69166667, "Longitude": 74.16527778},
            {"Remote Station Id": "2006", "Remote Station Name": "Wadange (Shiroli Bridge)", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.71194444, "Longitude": 74.27222222},
            {"Remote Station Id": "2007", "Remote Station Name": "Ichalkaranji", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.66555556, "Longitude": 74.47611111},
            {"Remote Station Id": "2008", "Remote Station Name": "Shivade", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.39722222, "Longitude": 74.10444444},
            {"Remote Station Id": "2009", "Remote Station Name": "Sangli Bypass", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.78333333, "Longitude": 74.58333333},
            {"Remote Station Id": "2010", "Remote Station Name": "Ankali Bridge", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.80527778, "Longitude": 74.56611111},
            {"Remote Station Id": "2011", "Remote Station Name": "Mhaisal", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.72583333, "Longitude": 74.70083333},
            {"Remote Station Id": "2012", "Remote Station Name": "Shelakbao (Arphal Aqueduct)", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.23638889, "Longitude": 74.425},
            {"Remote Station Id": "2013", "Remote Station Name": "Karad", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.28888889, "Longitude": 74.195},
            {"Remote Station Id": "2016", "Remote Station Name": "Amdabad", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.85555556, "Longitude": 74.25944444},
            {"Remote Station Id": "2017", "Remote Station Name": "Koregaon Bhima", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.64388889, "Longitude": 74.05416667},
            {"Remote Station Id": "2018", "Remote Station Name": "Nighoje (Ujjani)", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.70972222, "Longitude": 73.79361111},
            {"Remote Station Id": "2019", "Remote Station Name": "Pimple Gurav", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.60472222, "Longitude": 73.81333333},
            {"Remote Station Id": "2020", "Remote Station Name": "Paud", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.52861111, "Longitude": 73.61111111},
            {"Remote Station Id": "2021", "Remote Station Name": "Dattawadi", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.50444444, "Longitude": 73.83638889},
            {"Remote Station Id": "2022", "Remote Station Name": "Kalyani nagar Bridge", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.54083333, "Longitude": 73.90444444},
            {"Remote Station Id": "2023", "Remote Station Name": "Khamgaon", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.545, "Longitude": 74.21861111},
            {"Remote Station Id": "2024", "Remote Station Name": "Ujjani(Pargaon)", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.56944444, "Longitude": 74.37888889},
            {"Remote Station Id": "2025", "Remote Station Name": "25.Ujjani(Kashti)", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.55027778, "Longitude": 74.57722222},
            {"Remote Station Id": "2026", "Remote Station Name": "Pandharpur", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.69083333, "Longitude": 75.32666667},
            {"Remote Station Id": "2027", "Remote Station Name": "Takli Barur", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.41472222, "Longitude": 75.84583333},
            {"Remote Station Id": "2028", "Remote Station Name": "Siddhewadi", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.565, "Longitude": 75.40861111},
            {"Remote Station Id": "2029", "Remote Station Name": "Kagal (NH4) GD", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.55388889, "Longitude": 74.3175},
            {"Remote Station Id": "2031", "Remote Station Name": "Nira Narsinhpur", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.97, "Longitude": 75.1375},
            {"Remote Station Id": "2032", "Remote Station Name": "Umbre Kasurdi (Vir)", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.2175, "Longitude": 73.90083333},
            {"Remote Station Id": "2033", "Remote Station Name": "Late", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.06916667, "Longitude": 74.40472222},
            {"Remote Station Id": "2035", "Remote Station Name": "Pargaon Tarfe Aale (Ujjani)", "Project Id": 2, "Station Type Id": 2, "Latitude": 19.04361111, "Longitude": 74.15833333},
            {"Remote Station Id": "2036", "Remote Station Name": "Daund", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.47944444, "Longitude": 74.05861111},
            {"Remote Station Id": "101F0013", "Remote Station Name": "Diksal", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.90711111, "Longitude": 75.69244444},
            {"Remote Station Id": "101F0001", "Remote Station Name": "Ambeghar", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.13649722, "Longitude": 73.79953},
            {"Remote Station Id": "101F0015", "Remote Station Name": "Ruddhewadi", "Project Id": 2, "Station Type Id": 2, "Latitude": 17.37947222, "Longitude": 76.32172222},
            {"Remote Station Id": "101F0029", "Remote Station Name": "Sangli", "Project Id": 2, "Station Type Id": 2, "Latitude": 16.85833333, "Longitude": 74.56611111},
            {"Remote Station Id": "101F0005", "Remote Station Name": "Barhanpur (Karha)", "Project Id": 2, "Station Type Id": 2, "Latitude": 18.173886, "Longitude": 74.558998},
            {"Remote Station Id": "101F0026", "Remote Station Name": "Ambehol Dam", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.214, "Longitude": 74.253194},
            {"Remote Station Id": "101A0001", "Remote Station Name": "Chitri", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.07083, "Longitude": 74.15833},
            {"Remote Station Id": "4001", "Remote Station Name": "Dhom", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.97547, "Longitude": 73.819318},
            {"Remote Station Id": "4002", "Remote Station Name": "Dhom Balkawadi", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.960056, "Longitude": 73.71003},
            {"Remote Station Id": "4003", "Remote Station Name": "Mahu", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.89027778, "Longitude": 73.81583333},
            {"Remote Station Id": "4004", "Remote Station Name": "Kanher", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.73694444, "Longitude": 73.91583333},
            {"Remote Station Id": "4005", "Remote Station Name": "Urmodi", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.66222222, "Longitude": 73.90972222},
            {"Remote Station Id": "4006", "Remote Station Name": "Tarali", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.53361111, "Longitude": 73.89861111},
            {"Remote Station Id": "4007", "Remote Station Name": "Koyna", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.402681, "Longitude": 73.751088},
            {"Remote Station Id": "4008", "Remote Station Name": "Uttarmand", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.40305556, "Longitude": 74.01083333},
            {"Remote Station Id": "4009", "Remote Station Name": "Morna (Gureghar)", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.29388889, "Longitude": 73.83444444},
            {"Remote Station Id": "4010", "Remote Station Name": "Warna", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.132798, "Longitude": 73.85855},
            {"Remote Station Id": "4011", "Remote Station Name": "Patgaon", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.12305556, "Longitude": 73.93194444},
            {"Remote Station Id": "4012", "Remote Station Name": "Kadvi", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.00944444, "Longitude": 73.87},
            {"Remote Station Id": "4013", "Remote Station Name": "Kasari", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.8575, "Longitude": 73.79444444},
            {"Remote Station Id": "4014", "Remote Station Name": "Kumbhi", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.52416667, "Longitude": 73.86194444},
            {"Remote Station Id": "4015", "Remote Station Name": "24.Visapur", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.805, "Longitude": 74.59055556},
            {"Remote Station Id": "4016", "Remote Station Name": "Radhanagari", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.40527778, "Longitude": 73.95972222},
            {"Remote Station Id": "4017", "Remote Station Name": "Dudhganga", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.35694444, "Longitude": 74.00666667},
            {"Remote Station Id": "4018", "Remote Station Name": "Tembhu Barrage", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.27555556, "Longitude": 74.23166667},
            {"Remote Station Id": "4019", "Remote Station Name": "Satpewadi Barrage", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.11638889, "Longitude": 74.35666667},
            {"Remote Station Id": "4020", "Remote Station Name": "Chilewadi", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.34277778, "Longitude": 73.96777778},
            {"Remote Station Id": "4021", "Remote Station Name": "Pimpalgaon Joga", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.30861111, "Longitude": 73.88111111},
            {"Remote Station Id": "4022", "Remote Station Name": "Manikdoh", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.23583333, "Longitude": 73.81444444},
            {"Remote Station Id": "4023", "Remote Station Name": "Yedgaon", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.17305556, "Longitude": 74.02055556},
            {"Remote Station Id": "4024", "Remote Station Name": "Wadaj", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.15416667, "Longitude": 73.85666667},
            {"Remote Station Id": "4025", "Remote Station Name": "Dimbe", "Project Id": 2, "Station Type Id": 3, "Latitude": 19.09361111, "Longitude": 73.74361111},
            {"Remote Station Id": "4026", "Remote Station Name": "Chaskaman", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.95666667, "Longitude": 73.78388889},
            {"Remote Station Id": "4027", "Remote Station Name": "Kalmodi", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.999598, "Longitude": 73.670891},
            {"Remote Station Id": "4028", "Remote Station Name": "Bhama Askheda", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.843559, "Longitude": 73.726954},
            {"Remote Station Id": "4029", "Remote Station Name": "Andhra", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.78527778, "Longitude": 73.65},
            {"Remote Station Id": "4030", "Remote Station Name": "Wadiwale", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.81888889, "Longitude": 73.51222222},
            {"Remote Station Id": "4031", "Remote Station Name": "Pawana", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.68055556, "Longitude": 73.49472222},
            {"Remote Station Id": "4032", "Remote Station Name": "Kasar Sai", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.61861111, "Longitude": 73.66444444},
            {"Remote Station Id": "4033", "Remote Station Name": "Mulshi", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.53166667, "Longitude": 73.51138889},
            {"Remote Station Id": "4034", "Remote Station Name": "Temghar", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.45305556, "Longitude": 73.54055556},
            {"Remote Station Id": "4035", "Remote Station Name": "Warasgaon", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.38694444, "Longitude": 73.6125},
            {"Remote Station Id": "4036", "Remote Station Name": "Panshet", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.379871, "Longitude": 73.611117},
            {"Remote Station Id": "4037", "Remote Station Name": "Khadakwasala", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.44277778, "Longitude": 73.76416667},
            {"Remote Station Id": "4038", "Remote Station Name": "Ghod", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "4039", "Remote Station Name": "Ujjani", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.074981, "Longitude": 75.120487},
            {"Remote Station Id": "4040", "Remote Station Name": "Sina-Kolegaon", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.30861111, "Longitude": 75.40055556},
            {"Remote Station Id": "4041", "Remote Station Name": "Sina (Nimgaon)", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.8275, "Longitude": 74.94833333},
            {"Remote Station Id": "4042", "Remote Station Name": "Tulshi", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.52277778, "Longitude": 74.01777778},
            {"Remote Station Id": "4043", "Remote Station Name": "Bhatghar", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.17416667, "Longitude": 73.86972222},
            {"Remote Station Id": "4044", "Remote Station Name": "Veer", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.12222222, "Longitude": 74.09666667},
            {"Remote Station Id": "4045", "Remote Station Name": "Nira Deoghar", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.10027778, "Longitude": 73.72388889},
            {"Remote Station Id": "4046", "Remote Station Name": "Nazare", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.2975, "Longitude": 74.19166667},
            {"Remote Station Id": "4047", "Remote Station Name": "Yeralwadi", "Project Id": 2, "Station Type Id": 3, "Latitude": 17.52333333, "Longitude": 74.49305556},
            {"Remote Station Id": "73BC7F1A", "Remote Station Name": "Khadakewada", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.4125, "Longitude": 74.31389},
            {"Remote Station Id": "73BCC246", "Remote Station Name": "Gunjawani-WL", "Project Id": 2, "Station Type Id": 3, "Latitude": 18.30380556, "Longitude": 73.62519444},
            {"Remote Station Id": "73BC923A", "Remote Station Name": "Jangamhatti", "Project Id": 2, "Station Type Id": 3, "Latitude": 16.85833, "Longitude": 74.3},
            {"Remote Station Id": "73BC9CE8", "Remote Station Name": "Jambhare", "Project Id": 2, "Station Type Id": 3, "Latitude": 15.87972, "Longitude": 74.1111},
            {"Remote Station Id": "73BD1806", "Remote Station Name": "Dudhaganga", "Project Id": 2, "Station Type Id": 4, "Latitude": 16.35694, "Longitude": 74.00667},
            {"Remote Station Id": "73BD234E", "Remote Station Name": "Warana", "Project Id": 2, "Station Type Id": 4, "Latitude": 17.132798, "Longitude": 73.85855},
            {"Remote Station Id": "73BD2D9C", "Remote Station Name": "Koyna", "Project Id": 2, "Station Type Id": 4, "Latitude": 17.402681, "Longitude": 73.751088},
            {"Remote Station Id": "73BCCC94", "Remote Station Name": "Dimbhe", "Project Id": 2, "Station Type Id": 4, "Latitude": 19.09361111, "Longitude": 73.74361111},
            {"Remote Station Id": "73BCD130", "Remote Station Name": "Pawana", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.68055556, "Longitude": 73.49472222},
            {"Remote Station Id": "73BCDFE2", "Remote Station Name": "Khadakwasala", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.44194444, "Longitude": 73.76805556},
            {"Remote Station Id": "73BCE4AA", "Remote Station Name": "Bhatghar", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.17416667, "Longitude": 73.86972222},
            {"Remote Station Id": "73BCEA78", "Remote Station Name": "Chaskman", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.95666667, "Longitude": 73.78388889},
            {"Remote Station Id": "73BCF7DC", "Remote Station Name": "Ghod-Epan", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "73BCF90E", "Remote Station Name": "Ujjani", "Project Id": 2, "Station Type Id": 4, "Latitude": 18.06666667, "Longitude": 75.12083333},
            {"Remote Station Id": "73BD05A2", "Remote Station Name": "Urmodi", "Project Id": 2, "Station Type Id": 4, "Latitude": 17.66222222, "Longitude": 73.90972222},
            {"Remote Station Id": "73BD0B70", "Remote Station Name": "Dhom", "Project Id": 2, "Station Type Id": 4, "Latitude": 17.97305556, "Longitude": 73.82027778},
            {"Remote Station Id": "73BC62BE", "Remote Station Name": "Chikotra-Gate", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.225, "Longitude": 74.20639},
            {"Remote Station Id": "73BD3EEA", "Remote Station Name": "Ghod-1", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "73BD46A8", "Remote Station Name": "Ghod-2", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "73BD487A", "Remote Station Name": "Ghod-3", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "73BD55DE", "Remote Station Name": "Ghod-4", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.68, "Longitude": 74.49694444},
            {"Remote Station Id": "73BD5B0C", "Remote Station Name": "Kasarsai", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.61861111, "Longitude": 73.66444444},
            {"Remote Station Id": "73BD6044", "Remote Station Name": "Tarali", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.53361111, "Longitude": 73.89861111},
            {"Remote Station Id": "73BD6E96", "Remote Station Name": "Tulshi", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.52278, "Longitude": 74.01778},
            {"Remote Station Id": "73BD7332", "Remote Station Name": "Morana (Gureghar)", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.29388889, "Longitude": 73.83444444},
            {"Remote Station Id": "73BD7DE0", "Remote Station Name": "Pimpalgaon Joge", "Project Id": 2, "Station Type Id": 5, "Latitude": 19.30861111, "Longitude": 73.88111111},
            {"Remote Station Id": "73BD83B6", "Remote Station Name": "Satpewadi bandhara", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.01639, "Longitude": 74.35667},
            {"Remote Station Id": "73BD8D64", "Remote Station Name": "Tembhu bandhara-1", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.27556, "Longitude": 74.23167},
            {"Remote Station Id": "73BD90C0", "Remote Station Name": "Tembhu bandhara-2", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.27556, "Longitude": 74.23167},
            {"Remote Station Id": "5001", "Remote Station Name": "Koyna", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.40361111, "Longitude": 73.74888889},
            {"Remote Station Id": "5002", "Remote Station Name": "Radhanagari", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.40527778, "Longitude": 73.95972222},
            {"Remote Station Id": "5003", "Remote Station Name": "Dhom", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.97305556, "Longitude": 73.82027778},
            {"Remote Station Id": "5004", "Remote Station Name": "Dhom Balkawadi", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.96194444, "Longitude": 73.71055556},
            {"Remote Station Id": "5006", "Remote Station Name": "Ujjani", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.074534, "Longitude": 75.120308},
            {"Remote Station Id": "5007", "Remote Station Name": "Khadakwasala", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.44194444, "Longitude": 73.76805556},
            {"Remote Station Id": "5008", "Remote Station Name": "Veer", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.12222222, "Longitude": 74.09666667},
            {"Remote Station Id": "5009", "Remote Station Name": "Kanher", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.73694444, "Longitude": 73.91583333},
            {"Remote Station Id": "5010", "Remote Station Name": "Urmodi", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.66222222, "Longitude": 73.90972222},
            {"Remote Station Id": "5011", "Remote Station Name": "Uttarmand", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.40305556, "Longitude": 74.01083333},
            {"Remote Station Id": "5013", "Remote Station Name": "Kumbhi", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.52416667, "Longitude": 73.86194444},
            {"Remote Station Id": "5014", "Remote Station Name": "Dudhganga", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.35694444, "Longitude": 74.00666667},
            {"Remote Station Id": "5015", "Remote Station Name": "Manikdoh", "Project Id": 2, "Station Type Id": 5, "Latitude": 19.23583333, "Longitude": 73.81444444},
            {"Remote Station Id": "5016", "Remote Station Name": "Warasgaon", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.38694444, "Longitude": 73.6125},
            {"Remote Station Id": "5017", "Remote Station Name": "Nira Deoghar", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.10027778, "Longitude": 73.72388889},
            {"Remote Station Id": "5019", "Remote Station Name": "Wadaj", "Project Id": 2, "Station Type Id": 5, "Latitude": 19.15416667, "Longitude": 73.85666667},
            {"Remote Station Id": "5020", "Remote Station Name": "Dimbe", "Project Id": 2, "Station Type Id": 5, "Latitude": 19.09361111, "Longitude": 73.74361111},
            {"Remote Station Id": "5021", "Remote Station Name": "Chaskaman", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.95666667, "Longitude": 73.78388889},
            {"Remote Station Id": "5023", "Remote Station Name": "Wadiwale", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.81888889, "Longitude": 73.51222222},
            {"Remote Station Id": "5024", "Remote Station Name": "Pawana", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.68055556, "Longitude": 73.49472222},
            {"Remote Station Id": "5025", "Remote Station Name": "Mulshi", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.52194444, "Longitude": 73.51527778},
            {"Remote Station Id": "5026", "Remote Station Name": "Yedgaon", "Project Id": 2, "Station Type Id": 5, "Latitude": 19.17305556, "Longitude": 74.02055556},
            {"Remote Station Id": "5505", "Remote Station Name": "Warna", "Project Id": 2, "Station Type Id": 5, "Latitude": 17.14083333, "Longitude": 73.86555556},
            {"Remote Station Id": "5512", "Remote Station Name": "Kasari", "Project Id": 2, "Station Type Id": 5, "Latitude": 16.8575, "Longitude": 73.79444444},
            {"Remote Station Id": "5518", "Remote Station Name": "Panshet", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.37972222, "Longitude": 73.611117},
            {"Remote Station Id": "5522", "Remote Station Name": "Bhama Askheda", "Project Id": 2, "Station Type Id": 5, "Latitude": 18.83305556, "Longitude": 73.72444444},
            {"Remote Station Id": "3025", "Remote Station Name": "Jat", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.04611111, "Longitude": 75.23027778},
            {"Remote Station Id": "3030", "Remote Station Name": "Bhuinj", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.85, "Longitude": 73.99277778},
            {"Remote Station Id": "3031", "Remote Station Name": "Urmodi(Parali)", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.66, "Longitude": 73.91416667},
            {"Remote Station Id": "3032", "Remote Station Name": "Ambale", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.50527778, "Longitude": 73.93472222},
            {"Remote Station Id": "3033", "Remote Station Name": "Shivade", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.39694444, "Longitude": 74.10694444},
            {"Remote Station Id": "3034", "Remote Station Name": "Sarud", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.915, "Longitude": 74.04222222},
            {"Remote Station Id": "3035", "Remote Station Name": "Gudhe", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.23388889, "Longitude": 73.97805556},
            {"Remote Station Id": "3036", "Remote Station Name": "Patrayachiwadi (Balapwadi)", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.61333333, "Longitude": 73.9975},
            {"Remote Station Id": "3037", "Remote Station Name": "Mhaisal", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.72694444, "Longitude": 74.70111111},
            {"Remote Station Id": "3038", "Remote Station Name": "Kavate Ekand", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.85138889, "Longitude": 74.62083333},
            {"Remote Station Id": "3039", "Remote Station Name": "Rukadi", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.72611111, "Longitude": 74.36222222},
            {"Remote Station Id": "3040", "Remote Station Name": "Kuchi", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.05888889, "Longitude": 74.85805556},
            {"Remote Station Id": "3041", "Remote Station Name": "Chandgad", "Project Id": 2, "Station Type Id": 6, "Latitude": 15.93666667, "Longitude": 74.17694444},
            {"Remote Station Id": "3042", "Remote Station Name": "Islampur", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.04138889, "Longitude": 74.24194444},
            {"Remote Station Id": "3043", "Remote Station Name": "Khanapur", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.26416667, "Longitude": 74.70666667},
            {"Remote Station Id": "3044", "Remote Station Name": "Rahimatpur", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.59333333, "Longitude": 74.19888889},
            {"Remote Station Id": "3045", "Remote Station Name": "Wangi", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.23638889, "Longitude": 74.425},
            {"Remote Station Id": "3046", "Remote Station Name": "18.Pimpalgaon Joga(Pimpalwandi)", "Project Id": 2, "Station Type Id": 6, "Latitude": 19.30944444, "Longitude": 73.88111111},
            {"Remote Station Id": "3047", "Remote Station Name": "Chaskaman", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.90861111, "Longitude": 73.84472222},
            {"Remote Station Id": "3048", "Remote Station Name": "Shikrapur", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.69166667, "Longitude": 74.13888889},
            {"Remote Station Id": "3049", "Remote Station Name": "25.Ujjani(Nighoje)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.71027778, "Longitude": 73.78416667},
            {"Remote Station Id": "3050", "Remote Station Name": "25.Ujjani(Pargaon)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.56333333, "Longitude": 74.37027778},
            {"Remote Station Id": "3051", "Remote Station Name": "25.Ujjani(Bhigwan)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.29666667, "Longitude": 74.75861111},
            {"Remote Station Id": "3052", "Remote Station Name": "25.Ujjani(Kashti)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.55111111, "Longitude": 74.58111111},
            {"Remote Station Id": "3053", "Remote Station Name": "25.Ujjani(Bhimanagar)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.0675, "Longitude": 75.12},
            {"Remote Station Id": "3054", "Remote Station Name": "17.Nazare", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.2975, "Longitude": 74.19166667},
            {"Remote Station Id": "3055", "Remote Station Name": "Takli Barur", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.42027778, "Longitude": 75.85194444},
            {"Remote Station Id": "3056", "Remote Station Name": "Nimgaon Gangurde (Sina Kolegaon)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.81166667, "Longitude": 74.94861111},
            {"Remote Station Id": "3057", "Remote Station Name": "25.Ujjani(Kolawadi)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.51944444, "Longitude": 74.98527778},
            {"Remote Station Id": "3058", "Remote Station Name": "Rosa (Sina Kolegaon)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.49277778, "Longitude": 75.73861111},
            {"Remote Station Id": "3059", "Remote Station Name": "Ashti", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.84333333, "Longitude": 75.40861111},
            {"Remote Station Id": "3060", "Remote Station Name": "Nannaj", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.82944444, "Longitude": 75.86277778},
            {"Remote Station Id": "3061", "Remote Station Name": "Sangola", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.44416667, "Longitude": 75.18416667},
            {"Remote Station Id": "3062", "Remote Station Name": "Nighoj", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.96416667, "Longitude": 74.28583333},
            {"Remote Station Id": "3063", "Remote Station Name": "Bhoom", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.48638889, "Longitude": 75.65888889},
            {"Remote Station Id": "3064", "Remote Station Name": "Bori Dam", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.61805556, "Longitude": 76.21277778},
            {"Remote Station Id": "3065", "Remote Station Name": "Mangalwedha", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.51416667, "Longitude": 75.45277778},
            {"Remote Station Id": "3066", "Remote Station Name": "16.Veer(Sakhar )", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.27555556, "Longitude": 73.72083333},
            {"Remote Station Id": "3067", "Remote Station Name": "16.Veer(Umbre Kasurdi)", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.2125, "Longitude": 73.89666667},
            {"Remote Station Id": "3068", "Remote Station Name": "Late", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.07166667, "Longitude": 74.40694444},
            {"Remote Station Id": "3069", "Remote Station Name": "Malshiras (Solapur)", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.85833333, "Longitude": 74.90027778},
            {"Remote Station Id": "3070", "Remote Station Name": "Khadakwasala", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.44722222, "Longitude": 73.77333333},
            {"Remote Station Id": "3071", "Remote Station Name": "Barhanpur", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.2, "Longitude": 74.53333333},
            {"Remote Station Id": "101F0006", "Remote Station Name": "Sinchan Bhavan, Pune", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.525248, "Longitude": 73.865587},
            {"Remote Station Id": "101F0004", "Remote Station Name": "Paud", "Project Id": 2, "Station Type Id": 6, "Latitude": 74.275111, "Longitude": 73.607216},
            {"Remote Station Id": "101F0012", "Remote Station Name": "Barshi", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.25463889, "Longitude": 75.70930556},
            {"Remote Station Id": "101F0009", "Remote Station Name": "Koyna", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.40361111, "Longitude": 73.74888889},
            {"Remote Station Id": "101F0014", "Remote Station Name": "Osmanabad", "Project Id": 2, "Station Type Id": 6, "Latitude": 18.15786111, "Longitude": 76.05608333},
            {"Remote Station Id": "101F0028", "Remote Station Name": "Agran Dhulgaon_1", "Project Id": 2, "Station Type Id": 6, "Latitude": 17.60013889, "Longitude": 74.99527778},
            {"Remote Station Id": "73BD16D4", "Remote Station Name": "Songe Bange", "Project Id": 2, "Station Type Id": 6, "Latitude": 16.433205, "Longitude": 74.258172},
            {"Remote Station Id": "73BC098A", "Remote Station Name": "Yedagaon", "Project Id": 2, "Station Type Id": 7, "Latitude": 19.17305556, "Longitude": 74.02055556},
            {"Remote Station Id": "73BC142E", "Remote Station Name": "Sina Kolegaon", "Project Id": 2, "Station Type Id": 7, "Latitude": 18.30861111, "Longitude": 75.40055556},
            {"Remote Station Id": "73BBF5E8", "Remote Station Name": "Radhanagari", "Project Id": 2, "Station Type Id": 7, "Latitude": 16.40528, "Longitude": 73.95972},
            {"Remote Station Id": "73BBFB3A", "Remote Station Name": "Kasari", "Project Id": 2, "Station Type Id": 7, "Latitude": 16.8575, "Longitude": 73.79444},
            {"Remote Station Id": "73BC5724", "Remote Station Name": "Ghatprabha", "Project Id": 2, "Station Type Id": 8, "Latitude": 15.94583, "Longitude": 74.0722},
            {"Remote Station Id": "73BC6C6C", "Remote Station Name": "Gunjawani", "Project Id": 2, "Station Type Id": 9, "Latitude": 18.30833333, "Longitude": 73.64083333},
            {"Remote Station Id": "73BCA972", "Remote Station Name": "Chikotra", "Project Id": 2, "Station Type Id": 15, "Latitude": 16.225, "Longitude": 74.20639},
            {"Remote Station Id": "73B64500", "Remote Station Name": "Bopapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.20277778, "Longitude": 77.50694444},
            {"Remote Station Id": "73B64BD2", "Remote Station Name": "Vishroli", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.355, "Longitude": 77.76416667},
            {"Remote Station Id": "73B65676", "Remote Station Name": "Ghatang", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.44777778, "Longitude": 77.44333333},
            {"Remote Station Id": "73B658A4", "Remote Station Name": "Raipur", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.57722222, "Longitude": 77.26916667},
            {"Remote Station Id": "73B663EC", "Remote Station Name": "Jarida", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.6375, "Longitude": 77.48555556},
            {"Remote Station Id": "73B66D3E", "Remote Station Name": "Hatru", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.68194444, "Longitude": 77.33888889},
            {"Remote Station Id": "73B6709A", "Remote Station Name": "Khatkali", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.26666667, "Longitude": 77.10194444},
            {"Remote Station Id": "73B67E48", "Remote Station Name": "Girguti", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.31944444, "Longitude": 77.21222222},
            {"Remote Station Id": "73B6801E", "Remote Station Name": "Dabida", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.48861111, "Longitude": 76.83416667},
            {"Remote Station Id": "73B68ECC", "Remote Station Name": "Malur", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.51527778, "Longitude": 77.03333333},
            {"Remote Station Id": "73B69368", "Remote Station Name": "Chaurakund", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.60805556, "Longitude": 77.10777778},
            {"Remote Station Id": "73B69DBA", "Remote Station Name": "Dolar  (Titamba)", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.39305556, "Longitude": 76.96638889},
            {"Remote Station Id": "73B6A6F2", "Remote Station Name": "Nagzira", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.38111111, "Longitude": 76.72055556},
            {"Remote Station Id": "73B6A820", "Remote Station Name": "Chunkhadi", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.57472222, "Longitude": 77.41666667},
            {"Remote Station Id": "73B6B584", "Remote Station Name": "Rahu", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.71138889, "Longitude": 77.4325},
            {"Remote Station Id": "73B6BB56", "Remote Station Name": "Semadoh", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.5, "Longitude": 77.32388889},
            {"Remote Station Id": "73B6C314", "Remote Station Name": "Kutasa", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.94916667, "Longitude": 77.10861111},
            {"Remote Station Id": "73B6CDC6", "Remote Station Name": "Popatkhed", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.20444444, "Longitude": 77.08166667},
            {"Remote Station Id": "73B6D062", "Remote Station Name": "Tuljapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.44805556, "Longitude": 76.91944444},
            {"Remote Station Id": "73B6DEB0", "Remote Station Name": "Takli Khetri", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.51361111, "Longitude": 76.76888889},
            {"Remote Station Id": "73B6E5F8", "Remote Station Name": "Gadegaon", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.02361111, "Longitude": 76.86722222},
            {"Remote Station Id": "73B6EB2A", "Remote Station Name": "Anjangaon Surji", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.1675, "Longitude": 77.31583333},
            {"Remote Station Id": "73B6F68E", "Remote Station Name": "Thugaon", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.1025, "Longitude": 77.57805556},
            {"Remote Station Id": "73B6F85C", "Remote Station Name": "Daryapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.92222222, "Longitude": 77.31305556},
            {"Remote Station Id": "73B704F0", "Remote Station Name": "Deulgaon Sakarsha", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.42611111, "Longitude": 76.68833333},
            {"Remote Station Id": "73B70A22", "Remote Station Name": "Lakhanwada", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.49333333, "Longitude": 76.625},
            {"Remote Station Id": "73B71786", "Remote Station Name": "Tandulwadi", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.68388889, "Longitude": 76.45555556},
            {"Remote Station Id": "73B71954", "Remote Station Name": "Motala", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.67916667, "Longitude": 76.20944444},
            {"Remote Station Id": "73B7221C", "Remote Station Name": "Wasali", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.14861111, "Longitude": 76.65833333},
            {"Remote Station Id": "73B72CCE", "Remote Station Name": "Dongar Sevali", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.46583333, "Longitude": 76.32111111},
            {"Remote Station Id": "73B7316A", "Remote Station Name": "Borkhed", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.56833333, "Longitude": 76.27166667},
            {"Remote Station Id": "73B73FB8", "Remote Station Name": "Nimkhed", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.50361111, "Longitude": 76.50722222},
            {"Remote Station Id": "73B747FA", "Remote Station Name": "Rohinkhed", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.62888889, "Longitude": 76.1325},
            {"Remote Station Id": "73B74928", "Remote Station Name": "Parwa", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.54055556, "Longitude": 77.40805556},
            {"Remote Station Id": "73B7548C", "Remote Station Name": "Davha", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.28638889, "Longitude": 77.03861111},
            {"Remote Station Id": "73B75A5E", "Remote Station Name": "Bhourad", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.28194444, "Longitude": 76.85166667},
            {"Remote Station Id": "73B76116", "Remote Station Name": "Changdeo", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.07416667, "Longitude": 76.00861111},
            {"Remote Station Id": "73B76FC4", "Remote Station Name": "Shivre digar", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.72916667, "Longitude": 75.07694444},
            {"Remote Station Id": "73B77260", "Remote Station Name": "Ajanad", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.24444444, "Longitude": 76.1425},
            {"Remote Station Id": "73B77CB2", "Remote Station Name": "Rangaon", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.06833333, "Longitude": 75.8925},
            {"Remote Station Id": "73B782E4", "Remote Station Name": "Lohara", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.26111111, "Longitude": 75.93833333},
            {"Remote Station Id": "73B78C36", "Remote Station Name": "Pal", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.36194444, "Longitude": 75.9},
            {"Remote Station Id": "73B79192", "Remote Station Name": "Mohamandali", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.30388889, "Longitude": 75.79861111},
            {"Remote Station Id": "73B79F40", "Remote Station Name": "Chinchave", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.79055556, "Longitude": 74.46472222},
            {"Remote Station Id": "73B7A408", "Remote Station Name": "Zodage", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.65972222, "Longitude": 74.67916667},
            {"Remote Station Id": "73B7AADA", "Remote Station Name": "Khakurdi", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.68333333, "Longitude": 74.41805556},
            {"Remote Station Id": "73B7B77E", "Remote Station Name": "Mahad", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.8, "Longitude": 74.36666667},
            {"Remote Station Id": "73B7B9AC", "Remote Station Name": "Golwad", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.8, "Longitude": 74.03333333},
            {"Remote Station Id": "73B7C1EE", "Remote Station Name": "Barhe", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.52, "Longitude": 73.75},
            {"Remote Station Id": "73B7CF3C", "Remote Station Name": "Vadgaon", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.7925, "Longitude": 75.23111111},
            {"Remote Station Id": "73B7D298", "Remote Station Name": "Jamthi", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.805, "Longitude": 75.98333333},
            {"Remote Station Id": "73B7DC4A", "Remote Station Name": "Chalisgaon", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.46527778, "Longitude": 75.01666667},
            {"Remote Station Id": "73B7E702", "Remote Station Name": "Mehunbare", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.56361111, "Longitude": 74.85},
            {"Remote Station Id": "73B7E9D0", "Remote Station Name": "Bhormadi", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.34, "Longitude": 75.46},
            {"Remote Station Id": "73B7F474", "Remote Station Name": "Shendurni", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.65944444, "Longitude": 75.59333333},
            {"Remote Station Id": "73B7FAA6", "Remote Station Name": "Tondapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.58027778, "Longitude": 75.81666667},
            {"Remote Station Id": "73B80262", "Remote Station Name": "Waghur Dam Site", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.93333333, "Longitude": 75.71666667},
            {"Remote Station Id": "73B80CB0", "Remote Station Name": "Bhokarbari Dam Site", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.91777778, "Longitude": 75.11638889},
            {"Remote Station Id": "73B81114", "Remote Station Name": "Varthan", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.51361111, "Longitude": 75.36},
            {"Remote Station Id": "73B81FC6", "Remote Station Name": "Adgaon Mor", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.2425, "Longitude": 75.555},
            {"Remote Station Id": "73B8248E", "Remote Station Name": "Borkheda", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.30166667, "Longitude": 74.98333333},
            {"Remote Station Id": "73B82A5C", "Remote Station Name": "Saundane", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.44666667, "Longitude": 74.395},
            {"Remote Station Id": "73B837F8", "Remote Station Name": "Lakhamapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.555, "Longitude": 74.3525},
            {"Remote Station Id": "73B8392A", "Remote Station Name": "Rajapur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.18638889, "Longitude": 74.65361111},
            {"Remote Station Id": "73B84168", "Remote Station Name": "Vinchur", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.71722222, "Longitude": 74.86555556},
            {"Remote Station Id": "73B84FBA", "Remote Station Name": "Purmepada", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.72722222, "Longitude": 74.70027778},
            {"Remote Station Id": "73B8521E", "Remote Station Name": "Songir", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.08027778, "Longitude": 74.78361111},
            {"Remote Station Id": "73B85CCC", "Remote Station Name": "Kaksewad", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.9375, "Longitude": 74.04388889},
            {"Remote Station Id": "73B86784", "Remote Station Name": "Shewadi", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.99166667, "Longitude": 74.35888889},
            {"Remote Station Id": "73B86956", "Remote Station Name": "Runmali", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.14472222, "Longitude": 74.29055556},
            {"Remote Station Id": "73B874F2", "Remote Station Name": "Betawad", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.16666667, "Longitude": 74.91027778},
            {"Remote Station Id": "73B87A20", "Remote Station Name": "Chimthane", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.1775, "Longitude": 74.69555556},
            {"Remote Station Id": "73B88476", "Remote Station Name": "Deojipada", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.14333333, "Longitude": 74.16916667},
            {"Remote Station Id": "73B88AA4", "Remote Station Name": "Malkatar", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.61416667, "Longitude": 74.77888889},
            {"Remote Station Id": "73B89700", "Remote Station Name": "Ambe", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.42888889, "Longitude": 75.11138889},
            {"Remote Station Id": "73B899D2", "Remote Station Name": "Thanepada", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.25888889, "Longitude": 74.26777778},
            {"Remote Station Id": "73B8A29A", "Remote Station Name": "Lonkheda", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.56666667, "Longitude": 74.48472222},
            {"Remote Station Id": "73B8AC48", "Remote Station Name": "Kuruswade", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.08361111, "Longitude": 74.05},
            {"Remote Station Id": "73B8B1EC", "Remote Station Name": "Dighave", "Project Id": 3, "Station Type Id": 1, "Latitude": 20.88388889, "Longitude": 74.22444444},
            {"Remote Station Id": "73B8BF3E", "Remote Station Name": "Dusane", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.15027778, "Longitude": 74.43333333},
            {"Remote Station Id": "73B8C77C", "Remote Station Name": "Vakwad", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.53388889, "Longitude": 74.98333333},
            {"Remote Station Id": "73B8C9AE", "Remote Station Name": "Akkalkuwa", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.53388889, "Longitude": 74.01666667},
            {"Remote Station Id": "73B8D40A", "Remote Station Name": "Ashte", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.26694444, "Longitude": 74.20055556},
            {"Remote Station Id": "73B8DAD8", "Remote Station Name": "Kholvihir", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.25, "Longitude": 74.08388889},
            {"Remote Station Id": "73B8E190", "Remote Station Name": "Khamla", "Project Id": 3, "Station Type Id": 1, "Latitude": 21.75, "Longitude": 74.35055556},
            {"Remote Station Id": "73BAA76E", "Remote Station Name": "Dhule", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.999, "Longitude": 74.106},
            {"Remote Station Id": "73B950E4", "Remote Station Name": "Aurangpur", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.81888889, "Longitude": 77.53388889},
            {"Remote Station Id": "73B95E36", "Remote Station Name": "Daryapur", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.925, "Longitude": 77.31111111},
            {"Remote Station Id": "73B9657E", "Remote Station Name": "Takli Khetri", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.68, "Longitude": 76.77},
            {"Remote Station Id": "73B96BAC", "Remote Station Name": "Manasgaon", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.93, "Longitude": 76.68111111},
            {"Remote Station Id": "73B97608", "Remote Station Name": "Sawkheda", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.96111111, "Longitude": 75.50805556},
            {"Remote Station Id": "73B978DA", "Remote Station Name": "Jamner", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.80805556, "Longitude": 75.795},
            {"Remote Station Id": "73B9868C", "Remote Station Name": "Malegaon Girna", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.52888889, "Longitude": 74.53388889},
            {"Remote Station Id": "73B9885E", "Remote Station Name": "Pal", "Project Id": 3, "Station Type Id": 2, "Latitude": 21.36111111, "Longitude": 75.89694444},
            {"Remote Station Id": "73B995FA", "Remote Station Name": "Morchida", "Project Id": 3, "Station Type Id": 2, "Latitude": 21.38388889, "Longitude": 75.14111111},
            {"Remote Station Id": "73B99B28", "Remote Station Name": "Supale", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.593, "Longitude": 73.938},
            {"Remote Station Id": "73B9A060", "Remote Station Name": "Vinchur", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.71694444, "Longitude": 74.86611111},
            {"Remote Station Id": "73B9AEB2", "Remote Station Name": "Lonkheda", "Project Id": 3, "Station Type Id": 2, "Latitude": 21.56805556, "Longitude": 74.48305556},
            {"Remote Station Id": "73B9B316", "Remote Station Name": "Raisingpur", "Project Id": 3, "Station Type Id": 2, "Latitude": 21.57694444, "Longitude": 73.93388889},
            {"Remote Station Id": "73B9BDC4", "Remote Station Name": "Harisaal", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.84611111, "Longitude": 76.89},
            {"Remote Station Id": "73B9C586", "Remote Station Name": "Kutanga", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.88694444, "Longitude": 76.85611111},
            {"Remote Station Id": "73B9CB54", "Remote Station Name": "Nandura", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.83, "Longitude": 76.46194444},
            {"Remote Station Id": "73B9D6F0", "Remote Station Name": "Wadner Bholaji", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.83805556, "Longitude": 76.31611111},
            {"Remote Station Id": "73B9D822", "Remote Station Name": "Datarti", "Project Id": 3, "Station Type Id": 2, "Latitude": 20.96388889, "Longitude": 74.36305556},
            {"Remote Station Id": "73B9E36A", "Remote Station Name": "Sapan", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.37, "Longitude": 77.47},
            {"Remote Station Id": "73B9EDB8", "Remote Station Name": "Katepurna", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.48, "Longitude": 77.16},
            {"Remote Station Id": "73B9F01C", "Remote Station Name": "Morna", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.42, "Longitude": 77},
            {"Remote Station Id": "73B9FECE", "Remote Station Name": "Nirguna", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.34, "Longitude": 76.85},
            {"Remote Station Id": "73BA0796", "Remote Station Name": "Uma", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.6, "Longitude": 77.4},
            {"Remote Station Id": "73BA0944", "Remote Station Name": "Mun", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.34, "Longitude": 76.51},
            {"Remote Station Id": "73BA14E0", "Remote Station Name": "Mus", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.61, "Longitude": 76.66},
            {"Remote Station Id": "73BA1A32", "Remote Station Name": "Utawali", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.42, "Longitude": 76.69},
            {"Remote Station Id": "73BA217A", "Remote Station Name": "Paldhag", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.6, "Longitude": 76.3},
            {"Remote Station Id": "73BA2FA8", "Remote Station Name": "Dhyanganga", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.54, "Longitude": 76.42},
            {"Remote Station Id": "73BA320C", "Remote Station Name": "Nalganga", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.73, "Longitude": 76.187},
            {"Remote Station Id": "73BA3CDE", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.072, "Longitude": 75.945},
            {"Remote Station Id": "73BA449C", "Remote Station Name": "Girna", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.49, "Longitude": 74.72},
            {"Remote Station Id": "73BA4A4E", "Remote Station Name": "Waghur", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.93333333, "Longitude": 75.71666667},
            {"Remote Station Id": "73BA57EA", "Remote Station Name": "Suki", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.29, "Longitude": 75.928},
            {"Remote Station Id": "73BA5938", "Remote Station Name": "Hivra", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.6, "Longitude": 75.35},
            {"Remote Station Id": "73BA6270", "Remote Station Name": "Aner", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.31, "Longitude": 75.14},
            {"Remote Station Id": "73BA6CA2", "Remote Station Name": "Bhokarbari", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.917, "Longitude": 75.116},
            {"Remote Station Id": "73BA7106", "Remote Station Name": "Chankapur", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.491, "Longitude": 73.883},
            {"Remote Station Id": "73BA7FD4", "Remote Station Name": "Nagyasakya", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.35, "Longitude": 74.6},
            {"Remote Station Id": "73BA8182", "Remote Station Name": "Bori", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.777, "Longitude": 75.038},
            {"Remote Station Id": "73BA8F50", "Remote Station Name": "Punad", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.627, "Longitude": 73.877},
            {"Remote Station Id": "73BA92F4", "Remote Station Name": "Anjani Dam", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.476, "Longitude": 74.789},
            {"Remote Station Id": "73BA9C26", "Remote Station Name": "Upper Panzara", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.927, "Longitude": 74.094},
            {"Remote Station Id": "73BAA9BC", "Remote Station Name": "Malangaon", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.095, "Longitude": 74.097},
            {"Remote Station Id": "73BAB418", "Remote Station Name": "Lower Panzara", "Project Id": 3, "Station Type Id": 3, "Latitude": 20.942, "Longitude": 74.452},
            {"Remote Station Id": "73BABACA", "Remote Station Name": "Amravati", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.278, "Longitude": 74.49388889},
            {"Remote Station Id": "73BAC288", "Remote Station Name": "Karawand", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.45, "Longitude": 74.96},
            {"Remote Station Id": "73BACC5A", "Remote Station Name": "Wadishewadi", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.154, "Longitude": 74.568},
            {"Remote Station Id": "73BAD1FE", "Remote Station Name": "Burai", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.152, "Longitude": 74.576},
            {"Remote Station Id": "73BADF2C", "Remote Station Name": "Rangawali", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.067, "Longitude": 73.867},
            {"Remote Station Id": "73BAE464", "Remote Station Name": "Dara", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.73, "Longitude": 74.44},
            {"Remote Station Id": "73BAEAB6", "Remote Station Name": "Kordi", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.24, "Longitude": 74.04},
            {"Remote Station Id": "73BAF712", "Remote Station Name": "Nagan", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.2, "Longitude": 73.976},
            {"Remote Station Id": "73BAF9C0", "Remote Station Name": "Sonwad", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.07, "Longitude": 74.84},
            {"Remote Station Id": "101D0003", "Remote Station Name": "Shahanoor", "Project Id": 3, "Station Type Id": 3, "Latitude": 21.258071, "Longitude": 77.32296},
            {"Remote Station Id": "73B91D3C", "Remote Station Name": "Katepurna Dam", "Project Id": 3, "Station Type Id": 4, "Latitude": 20.475, "Longitude": 77.15},
            {"Remote Station Id": "73B92674", "Remote Station Name": "Sapan Dam", "Project Id": 3, "Station Type Id": 4, "Latitude": 20.36666667, "Longitude": 77.46666667},
            {"Remote Station Id": "73B928A6", "Remote Station Name": "Nalganga Dam", "Project Id": 3, "Station Type Id": 4, "Latitude": 20.72944444, "Longitude": 76.1875},
            {"Remote Station Id": "73B93502", "Remote Station Name": "Girna Dam", "Project Id": 3, "Station Type Id": 4, "Latitude": 20.35277778, "Longitude": 74.70305556},
            {"Remote Station Id": "73B93BD0", "Remote Station Name": "Hatnur Dam", "Project Id": 3, "Station Type Id": 4, "Latitude": 21.07611111, "Longitude": 75.93722222},
            {"Remote Station Id": "73BB73FC", "Remote Station Name": "Waghur", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.93333333, "Longitude": 75.71666667},
            {"Remote Station Id": "73BB7D2E", "Remote Station Name": "Waghur", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.93333333, "Longitude": 75.71666667},
            {"Remote Station Id": "73BB8378", "Remote Station Name": "Aner", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.32583333, "Longitude": 75.13333333},
            {"Remote Station Id": "73BB8DAA", "Remote Station Name": "Aner", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.32583333, "Longitude": 75.13333333},
            {"Remote Station Id": "73BB900E", "Remote Station Name": "Chankapur", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.49166667, "Longitude": 73.88333333},
            {"Remote Station Id": "73BB9EDC", "Remote Station Name": "Punad", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.625, "Longitude": 73.875},
            {"Remote Station Id": "73BBA594", "Remote Station Name": "Lower Panzara", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.94111111, "Longitude": 74.45611111},
            {"Remote Station Id": "73BBAB46", "Remote Station Name": "Lower Panzara", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.94111111, "Longitude": 74.45611111},
            {"Remote Station Id": "73BBB6E2", "Remote Station Name": "Amravati", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.28333333, "Longitude": 74.5},
            {"Remote Station Id": "73BBB830", "Remote Station Name": "Amravati Project", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.28333333, "Longitude": 74.5},
            {"Remote Station Id": "73BBC072", "Remote Station Name": "Wadishewadi", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.15416667, "Longitude": 74.56805556},
            {"Remote Station Id": "73BBCEA0", "Remote Station Name": "Bori", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.78194444, "Longitude": 75.04138889},
            {"Remote Station Id": "73BBD304", "Remote Station Name": "Nagan", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.2, "Longitude": 73.97083333},
            {"Remote Station Id": "73BBDDD6", "Remote Station Name": "Sonwad", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07083333, "Longitude": 74.84444444},
            {"Remote Station Id": "73BB056C", "Remote Station Name": "Sapan", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.36666667, "Longitude": 77.46666667},
            {"Remote Station Id": "73BB0BBE", "Remote Station Name": "Katepurna", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.475, "Longitude": 77.15},
            {"Remote Station Id": "73BB161A", "Remote Station Name": "Katepurna", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.475, "Longitude": 77.15},
            {"Remote Station Id": "73BB18C8", "Remote Station Name": "Mun", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.34083333, "Longitude": 76.51333333},
            {"Remote Station Id": "73BB2380", "Remote Station Name": "Nalganga", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.34527778, "Longitude": 76.18833333},
            {"Remote Station Id": "73BB2D52", "Remote Station Name": "Nalganga", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.34527778, "Longitude": 76.18833333},
            {"Remote Station Id": "73BB30F6", "Remote Station Name": "Girna", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.51944444, "Longitude": 74.5375},
            {"Remote Station Id": "73BB3E24", "Remote Station Name": "Girna", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.51944444, "Longitude": 74.5375},
            {"Remote Station Id": "73BB4666", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07638889, "Longitude": 75.93722222},
            {"Remote Station Id": "73BB48B4", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07638889, "Longitude": 75.93722222},
            {"Remote Station Id": "73BB5510", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07638889, "Longitude": 75.93722222},
            {"Remote Station Id": "73BB5BC2", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07638889, "Longitude": 75.93722222},
            {"Remote Station Id": "73BB608A", "Remote Station Name": "Hatnur", "Project Id": 3, "Station Type Id": 5, "Latitude": 21.07638889, "Longitude": 75.93722222},
            {"Remote Station Id": "101D0001", "Remote Station Name": "Bori", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.77, "Longitude": 75.038},
            {"Remote Station Id": "101D0002", "Remote Station Name": "Lower Panzara", "Project Id": 3, "Station Type Id": 5, "Latitude": 20.942, "Longitude": 74.452},
            {"Remote Station Id": "73B8EF42", "Remote Station Name": "Khariya", "Project Id": 3, "Station Type Id": 6, "Latitude": 21.59611111, "Longitude": 76.8625},
            {"Remote Station Id": "73B8F2E6", "Remote Station Name": "Aurangpur", "Project Id": 3, "Station Type Id": 6, "Latitude": 20.82111111, "Longitude": 77.54083333},
            {"Remote Station Id": "73B8FC34", "Remote Station Name": "Manasgaon", "Project Id": 3, "Station Type Id": 6, "Latitude": 20.9125, "Longitude": 76.69083333},
            {"Remote Station Id": "73B90098", "Remote Station Name": "Jamner", "Project Id": 3, "Station Type Id": 6, "Latitude": 20.80555556, "Longitude": 75.79166667},
            {"Remote Station Id": "73B90E4A", "Remote Station Name": "Malegaon", "Project Id": 3, "Station Type Id": 6, "Latitude": 20.51944444, "Longitude": 74.5375},
            {"Remote Station Id": "73B913EE", "Remote Station Name": "Burai Dam", "Project Id": 3, "Station Type Id": 6, "Latitude": 21.15, "Longitude": 74.36111111},
            {"Remote Station Id": "73B94392", "Remote Station Name": "Lower Panzara Dam", "Project Id": 3, "Station Type Id": 7, "Latitude": 20.94944444, "Longitude": 74.42277778},
            {"Remote Station Id": "73BB6E58", "Remote Station Name": "Waghur", "Project Id": 3, "Station Type Id": 14, "Latitude": 20.93333333, "Longitude": 75.71666667},
            {"Remote Station Id": "73B29880", "Remote Station Name": "Bavnepangri", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.98333333, "Longitude": 75.87888889},
            {"Remote Station Id": "73B2A3C8", "Remote Station Name": "Ladsangvi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.975, "Longitude": 75.625},
            {"Remote Station Id": "73B2AD1A", "Remote Station Name": "Potanandgaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.27638889, "Longitude": 76.9125},
            {"Remote Station Id": "73B2B0BE", "Remote Station Name": "Salegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.76666667, "Longitude": 76.06666667},
            {"Remote Station Id": "73B42512", "Remote Station Name": "Mukhed", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.70555556, "Longitude": 77.37083333},
            {"Remote Station Id": "73B42BC0", "Remote Station Name": "Ujani", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.71166667, "Longitude": 76.69027778},
            {"Remote Station Id": "73B43664", "Remote Station Name": "Wanjarwadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.77722222, "Longitude": 76.89277778},
            {"Remote Station Id": "73B438B6", "Remote Station Name": "Shivani", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.32916667, "Longitude": 78.10833333},
            {"Remote Station Id": "73B440F4", "Remote Station Name": "Sawargaon Met", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.18444444, "Longitude": 77.77111111},
            {"Remote Station Id": "73B44E26", "Remote Station Name": "Mahur", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.85138889, "Longitude": 77.925},
            {"Remote Station Id": "73B45382", "Remote Station Name": "Himayatnagar", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.42444444, "Longitude": 77.86694444},
            {"Remote Station Id": "73B45D50", "Remote Station Name": "Pathoda", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.47083333, "Longitude": 78.26944444},
            {"Remote Station Id": "73B46618", "Remote Station Name": "Sarkhani", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.79166667, "Longitude": 78.1125},
            {"Remote Station Id": "73B468CA", "Remote Station Name": "Ambadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.68888889, "Longitude": 78.20833333},
            {"Remote Station Id": "73B4756E", "Remote Station Name": "Hadgaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.49277778, "Longitude": 77.65},
            {"Remote Station Id": "73B10AEC", "Remote Station Name": "Deosane", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.42416667, "Longitude": 73.71416667},
            {"Remote Station Id": "73B11748", "Remote Station Name": "Hivarkheda", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.22166667, "Longitude": 75.22361111},
            {"Remote Station Id": "73B1199A", "Remote Station Name": "Indore", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.63333333, "Longitude": 73.70861111},
            {"Remote Station Id": "73B122D2", "Remote Station Name": "Khadak Ozar", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.23805556, "Longitude": 74.12777778},
            {"Remote Station Id": "73B12C00", "Remote Station Name": "Khadakwagh", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.82472222, "Longitude": 74.94555556},
            {"Remote Station Id": "73B131A4", "Remote Station Name": "Khirdisathe", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.13694444, "Longitude": 74.5575},
            {"Remote Station Id": "73B13F76", "Remote Station Name": "Kolgaon Mal", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.85472222, "Longitude": 74.34611111},
            {"Remote Station Id": "73B14734", "Remote Station Name": "Mukhed G", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.01694444, "Longitude": 74.31277778},
            {"Remote Station Id": "73B149E6", "Remote Station Name": "Nagamthan", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.72388889, "Longitude": 74.78277778},
            {"Remote Station Id": "73B15442", "Remote Station Name": "NandurShing", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.71972222, "Longitude": 74.13416667},
            {"Remote Station Id": "73B15A90", "Remote Station Name": "Nilwandi", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.21583333, "Longitude": 73.79277778},
            {"Remote Station Id": "73B0EBE4", "Remote Station Name": "Ambedindori", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.11666667, "Longitude": 73.88333333},
            {"Remote Station Id": "73B0F640", "Remote Station Name": "Bolthan", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.18944444, "Longitude": 74.90694444},
            {"Remote Station Id": "73B17C7C", "Remote Station Name": "Pimpalgaon Dk", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.78333333, "Longitude": 73.7975},
            {"Remote Station Id": "73B1822A", "Remote Station Name": "Sanjegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.82277778, "Longitude": 73.61361111},
            {"Remote Station Id": "73B18CF8", "Remote Station Name": "Shendurwada", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.65, "Longitude": 75.25},
            {"Remote Station Id": "73B1915C", "Remote Station Name": "Vadangali", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.91777778, "Longitude": 74.0825},
            {"Remote Station Id": "73B1AA14", "Remote Station Name": "Sinnar", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.845, "Longitude": 73.99694444},
            {"Remote Station Id": "73B1B7B0", "Remote Station Name": "Tisgaon N", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.19, "Longitude": 75.06888889},
            {"Remote Station Id": "73B1B962", "Remote Station Name": "Bhavarwadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.27722222, "Longitude": 74.82138889},
            {"Remote Station Id": "73B1C120", "Remote Station Name": "Mahaldevi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.54777778, "Longitude": 73.94388889},
            {"Remote Station Id": "73B1CFF2", "Remote Station Name": "Thangaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.69583333, "Longitude": 73.93222222},
            {"Remote Station Id": "73B1D256", "Remote Station Name": "AshwiBk", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.52388889, "Longitude": 74.36888889},
            {"Remote Station Id": "73B1E91E", "Remote Station Name": "Dhawalpuri", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.17611111, "Longitude": 74.53083333},
            {"Remote Station Id": "73B1F4BA", "Remote Station Name": "Khadakvadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.29083333, "Longitude": 74.35583333},
            {"Remote Station Id": "73B1FA68", "Remote Station Name": "Pimpaldari", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.36777778, "Longitude": 74.07722222},
            {"Remote Station Id": "73B20330", "Remote Station Name": "Sawargaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.1575, "Longitude": 74.27833333},
            {"Remote Station Id": "73B20DE2", "Remote Station Name": "Asegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.64333333, "Longitude": 76.73777778},
            {"Remote Station Id": "73B21046", "Remote Station Name": "Bamni", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.75, "Longitude": 76.64166667},
            {"Remote Station Id": "73B21E94", "Remote Station Name": "Chinchkhed", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.23277778, "Longitude": 75.63583333},
            {"Remote Station Id": "73B225DC", "Remote Station Name": "Kavitkheda", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.13333333, "Longitude": 75.5125},
            {"Remote Station Id": "73B22B0E", "Remote Station Name": "Shevli", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.83138889, "Longitude": 76.26416667},
            {"Remote Station Id": "73B236AA", "Remote Station Name": "Shivna", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.47805556, "Longitude": 75.8},
            {"Remote Station Id": "73B23878", "Remote Station Name": "Chinchkheda", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.27194444, "Longitude": 75.97416667},
            {"Remote Station Id": "73B2403A", "Remote Station Name": "Dahipal Kh", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.82361111, "Longitude": 76.40416667},
            {"Remote Station Id": "73B24EE8", "Remote Station Name": "Dhanora Bk", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.75055556, "Longitude": 76.51972222},
            {"Remote Station Id": "73B275A0", "Remote Station Name": "Pishor", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.295, "Longitude": 75.34055556},
            {"Remote Station Id": "73B27B72", "Remote Station Name": "Shindkhedraja", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.95333333, "Longitude": 76.12611111},
            {"Remote Station Id": "73B2DB8A", "Remote Station Name": "Ambad", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.61361111, "Longitude": 75.79416667},
            {"Remote Station Id": "73B2E0C2", "Remote Station Name": "Bodhegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.30444444, "Longitude": 75.46444444},
            {"Remote Station Id": "73B2EE10", "Remote Station Name": "Dawarwadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.54055556, "Longitude": 75.50722222},
            {"Remote Station Id": "73B2F3B4", "Remote Station Name": "Georai", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.25, "Longitude": 75.75},
            {"Remote Station Id": "73B2FD66", "Remote Station Name": "Kuppa", "Project Id": 4, "Station Type Id": 1, "Latitude": 19, "Longitude": 76.14555556},
            {"Remote Station Id": "73B301CA", "Remote Station Name": "Palam", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.0125, "Longitude": 76.95416667},
            {"Remote Station Id": "73B30F18", "Remote Station Name": "Pimpalgaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.83333333, "Longitude": 77.78333333},
            {"Remote Station Id": "73B312BC", "Remote Station Name": "Umri", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.0375, "Longitude": 77.64027778},
            {"Remote Station Id": "73B31C6E", "Remote Station Name": "Amla", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.14, "Longitude": 75.91888889},
            {"Remote Station Id": "73B32726", "Remote Station Name": "Ashti", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.37611111, "Longitude": 76.225},
            {"Remote Station Id": "73B329F4", "Remote Station Name": "Beed", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.98972222, "Longitude": 75.75},
            {"Remote Station Id": "73B33450", "Remote Station Name": "Dharur", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.81916667, "Longitude": 76.10972222},
            {"Remote Station Id": "73B33A82", "Remote Station Name": "Dongarkada", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.37694444, "Longitude": 77.37111111},
            {"Remote Station Id": "73B342C0", "Remote Station Name": "Ghatshil Par", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.11694444, "Longitude": 75.35416667},
            {"Remote Station Id": "73B34C12", "Remote Station Name": "Jamkhed", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.63333333, "Longitude": 75.65},
            {"Remote Station Id": "73B351B6", "Remote Station Name": "Kiwla", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.0375, "Longitude": 77.30694444},
            {"Remote Station Id": "73B394A8", "Remote Station Name": "Awadshirpur", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.56777778, "Longitude": 76.18388889},
            {"Remote Station Id": "73B39A7A", "Remote Station Name": "Bardapur", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.63916667, "Longitude": 76.49444444},
            {"Remote Station Id": "73B3A132", "Remote Station Name": "Gharni Proj", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.37916667, "Longitude": 76.815},
            {"Remote Station Id": "73B3AFE0", "Remote Station Name": "Limbaganesh", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.8, "Longitude": 75.66666667},
            {"Remote Station Id": "73B3B244", "Remote Station Name": "Nitur", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.24027778, "Longitude": 76.77722222},
            {"Remote Station Id": "73B3BC96", "Remote Station Name": "Pangaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.43333333, "Longitude": 75.9},
            {"Remote Station Id": "73B3C4D4", "Remote Station Name": "Tawarajkheda", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.36666667, "Longitude": 76.26666667},
            {"Remote Station Id": "73B3CA06", "Remote Station Name": "Vida", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.81166667, "Longitude": 75.92888889},
            {"Remote Station Id": "73B3D7A2", "Remote Station Name": "Kasarshirsi", "Project Id": 4, "Station Type Id": 1, "Latitude": 17.91666667, "Longitude": 76.75},
            {"Remote Station Id": "73B3D970", "Remote Station Name": "Makni", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.02694444, "Longitude": 76.43888889},
            {"Remote Station Id": "73B3E238", "Remote Station Name": "Sarola", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.21583333, "Longitude": 76.1225},
            {"Remote Station Id": "73B3ECEA", "Remote Station Name": "Taka", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.21666667, "Longitude": 76.35333333},
            {"Remote Station Id": "73B3F14E", "Remote Station Name": "Jamb(Bk)", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.65833333, "Longitude": 77.18333333},
            {"Remote Station Id": "73B3FF9C", "Remote Station Name": "Ravankola", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.44027778, "Longitude": 77.27083333},
            {"Remote Station Id": "73B403FE", "Remote Station Name": "Wadhona", "Project Id": 4, "Station Type Id": 1, "Latitude": 18.52027778, "Longitude": 77.08333333},
            {"Remote Station Id": "111C0002", "Remote Station Name": "Bhavali Dam", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.64083333, "Longitude": 73.58361111},
            {"Remote Station Id": "111C0004", "Remote Station Name": "Taked", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.69138889, "Longitude": 73.76694444},
            {"Remote Station Id": "111C0005", "Remote Station Name": "Wasali", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.64416667, "Longitude": 73.72833333},
            {"Remote Station Id": "111C0007", "Remote Station Name": "Belpimpalgaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.595, "Longitude": 74.845},
            {"Remote Station Id": "111C0013", "Remote Station Name": "Ambelhol", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.84, "Longitude": 75.13944444},
            {"Remote Station Id": "111C0014", "Remote Station Name": "Dhorkin", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.61555556, "Longitude": 75.36722222},
            {"Remote Station Id": "111C0010", "Remote Station Name": "Solegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.70666667, "Longitude": 75.11},
            {"Remote Station Id": "111C0011", "Remote Station Name": "Toka", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.60333333, "Longitude": 75.01194444},
            {"Remote Station Id": "111C0040", "Remote Station Name": "Manjur (Handewadi)", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.915, "Longitude": 74.28083333},
            {"Remote Station Id": "111C0035", "Remote Station Name": "Padhegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.92222222, "Longitude": 74.54805556},
            {"Remote Station Id": "111C0036", "Remote Station Name": "Deogaon Rangari", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.03777778, "Longitude": 75.03333333},
            {"Remote Station Id": "111C0037", "Remote Station Name": "Loni(Kh)", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.14916667, "Longitude": 74.8175},
            {"Remote Station Id": "111C0044", "Remote Station Name": "Somthan", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.95, "Longitude": 74.215},
            {"Remote Station Id": "111C0045", "Remote Station Name": "Kopargaon city", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.89527778, "Longitude": 74.48083333},
            {"Remote Station Id": "111C0046", "Remote Station Name": "Sonewadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.80388889, "Longitude": 74.42083333},
            {"Remote Station Id": "111C0042", "Remote Station Name": "Rahata", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.70277778, "Longitude": 74.485},
            {"Remote Station Id": "111C0062", "Remote Station Name": "Mahaje", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.29361111, "Longitude": 73.62722222},
            {"Remote Station Id": "111C0063", "Remote Station Name": "Bharam", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.05805556, "Longitude": 74.67611111},
            {"Remote Station Id": "111C0064", "Remote Station Name": "Savkhede", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.1525, "Longitude": 74.46388889},
            {"Remote Station Id": "112C0001", "Remote Station Name": "Aswali (NandurVaidya)", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.81972222, "Longitude": 73.73305556},
            {"Remote Station Id": "112C0002", "Remote Station Name": "Bhawali BK", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.78138889, "Longitude": 73.56861111},
            {"Remote Station Id": "112C0003", "Remote Station Name": "Kushegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.86444444, "Longitude": 73.57722222},
            {"Remote Station Id": "112C0006", "Remote Station Name": "Rajur Bahula", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.91555556, "Longitude": 73.70055556},
            {"Remote Station Id": "112C0007", "Remote Station Name": "Ahurli", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.81722222, "Longitude": 73.58111111},
            {"Remote Station Id": "112C0008", "Remote Station Name": "Samangaon (B)", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.9525, "Longitude": 73.88055556},
            {"Remote Station Id": "112C0009", "Remote Station Name": "Chehedi", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.93555556, "Longitude": 73.86194444},
            {"Remote Station Id": "112C0010", "Remote Station Name": "Dahegaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.89361111, "Longitude": 73.64361111},
            {"Remote Station Id": "112C0011", "Remote Station Name": "DiksalPar", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.38722222, "Longitude": 73.53111111},
            {"Remote Station Id": "112C0026", "Remote Station Name": "Ambai", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.97277778, "Longitude": 73.4225},
            {"Remote Station Id": "112C0027", "Remote Station Name": "Anjaneri", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.94694444, "Longitude": 73.58722222},
            {"Remote Station Id": "112C0028", "Remote Station Name": "Dongarpada", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.40416667, "Longitude": 73.55083333},
            {"Remote Station Id": "112C0029", "Remote Station Name": "Mahiravani", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.96722222, "Longitude": 73.66166667},
            {"Remote Station Id": "112C0032", "Remote Station Name": "Waghera", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.0675, "Longitude": 73.49888889},
            {"Remote Station Id": "112C0033", "Remote Station Name": "Ganeshgaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.99722222, "Longitude": 73.62611111},
            {"Remote Station Id": "112C0034", "Remote Station Name": "Mungsare", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.06, "Longitude": 73.7225},
            {"Remote Station Id": "112C0035", "Remote Station Name": "Vilvandi", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.1575, "Longitude": 73.63055556},
            {"Remote Station Id": "112C0036", "Remote Station Name": "Pimpri Trimbak", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.01138889, "Longitude": 73.55611111},
            {"Remote Station Id": "112C0045", "Remote Station Name": "Ramshej", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.09305556, "Longitude": 73.77416667},
            {"Remote Station Id": "112C0046", "Remote Station Name": "Nalwadi", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.28, "Longitude": 73.75972222},
            {"Remote Station Id": "112C0047", "Remote Station Name": "Nanashi", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.34138889, "Longitude": 73.62027778},
            {"Remote Station Id": "112C0048", "Remote Station Name": "Ozarkhed dam", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.28305556, "Longitude": 73.87638889},
            {"Remote Station Id": "112C0049", "Remote Station Name": "Pimpri anchla", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.39972222, "Longitude": 73.82111111},
            {"Remote Station Id": "112C0050", "Remote Station Name": "Vani", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.32805556, "Longitude": 73.89},
            {"Remote Station Id": "112C0051", "Remote Station Name": "Karanjvan Dam", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.29083333, "Longitude": 73.77944444},
            {"Remote Station Id": "112C0040", "Remote Station Name": "Bhanwad", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.40611111, "Longitude": 73.6775},
            {"Remote Station Id": "112C0041", "Remote Station Name": "Charose", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.33388889, "Longitude": 73.67861111},
            {"Remote Station Id": "112C0042", "Remote Station Name": "Dhodambe", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.33111111, "Longitude": 74.05833333},
            {"Remote Station Id": "112C0043", "Remote Station Name": "Karanjkhed", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.42472222, "Longitude": 73.76138889},
            {"Remote Station Id": "112C0054", "Remote Station Name": "Waghad Dam", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.22777778, "Longitude": 73.72944444},
            {"Remote Station Id": "112C0058", "Remote Station Name": "Brahmangaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.95861111, "Longitude": 74.44944444},
            {"Remote Station Id": "112C0059", "Remote Station Name": "Deogaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.02055556, "Longitude": 74.26805556},
            {"Remote Station Id": "112C0060", "Remote Station Name": "Dugaon", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.29416667, "Longitude": 74.32416667},
            {"Remote Station Id": "112C0061", "Remote Station Name": "Mahalkheda", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.98861111, "Longitude": 74.37},
            {"Remote Station Id": "112C0069", "Remote Station Name": "Mothamal", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.55527778, "Longitude": 73.72305556},
            {"Remote Station Id": "112C0070", "Remote Station Name": "Wangan", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.605, "Longitude": 73.50083333},
            {"Remote Station Id": "112C0071", "Remote Station Name": "Karanjul", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.61666667, "Longitude": 73.48777778},
            {"Remote Station Id": "112C0072", "Remote Station Name": "Dolare", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.60166667, "Longitude": 73.55361111},
            {"Remote Station Id": "112C0073", "Remote Station Name": "Kathipada", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.56944444, "Longitude": 73.52},
            {"Remote Station Id": "112C0074", "Remote Station Name": "Bubli(Umaremal)", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.53055556, "Longitude": 73.6625},
            {"Remote Station Id": "112C0075", "Remote Station Name": "Satkhamb (Bhawandagad)", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.57888889, "Longitude": 73.59138889},
            {"Remote Station Id": "112C0076", "Remote Station Name": "Bendwal", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.49888889, "Longitude": 73.48583333},
            {"Remote Station Id": "112C0077", "Remote Station Name": "Jale", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.28472222, "Longitude": 73.50305556},
            {"Remote Station Id": "112C0078", "Remote Station Name": "Ambas(Zari)", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.37972222, "Longitude": 73.44555556},
            {"Remote Station Id": "112C0079", "Remote Station Name": "Ranvihir", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.27055556, "Longitude": 73.43944444},
            {"Remote Station Id": "112C0080", "Remote Station Name": "Umrad", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.21027778, "Longitude": 73.465},
            {"Remote Station Id": "112C0081", "Remote Station Name": "Waygholpada", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.09833333, "Longitude": 73.45277778},
            {"Remote Station Id": "112C0084", "Remote Station Name": "Borvat", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.26555556, "Longitude": 73.55611111},
            {"Remote Station Id": "112C0085", "Remote Station Name": "Dumi pada", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.425, "Longitude": 73.64277778},
            {"Remote Station Id": "112C0086", "Remote Station Name": "Hemadpada", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.4275, "Longitude": 73.59111111},
            {"Remote Station Id": "112C0087", "Remote Station Name": "Shinde", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.22277778, "Longitude": 73.60833333},
            {"Remote Station Id": "112C0088", "Remote Station Name": "Joran", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.33916667, "Longitude": 73.78138889},
            {"Remote Station Id": "112C0089", "Remote Station Name": "Gondune", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.678659, "Longitude": 73.467934},
            {"Remote Station Id": "112C0090", "Remote Station Name": "Koshimbe", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.355, "Longitude": 73.76833333},
            {"Remote Station Id": "112C0091", "Remote Station Name": "Umrale", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.13416667, "Longitude": 73.72138889},
            {"Remote Station Id": "112C0092", "Remote Station Name": "Madakijamb", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.18611111, "Longitude": 73.79416667},
            {"Remote Station Id": "112C0093", "Remote Station Name": "Maledumala", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.37611111, "Longitude": 73.83972222},
            {"Remote Station Id": "112C0094", "Remote Station Name": "Chausala", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.41194444, "Longitude": 73.78583333},
            {"Remote Station Id": "112C0023", "Remote Station Name": "Waki Dam", "Project Id": 4, "Station Type Id": 1, "Latitude": 19.75416667, "Longitude": 73.58888889},
            {"Remote Station Id": "112C0024", "Remote Station Name": "N.M. Weir", "Project Id": 4, "Station Type Id": 1, "Latitude": 20.01833333, "Longitude": 74.13166667},
            {"Remote Station Id": "112C0082", "Remote Station Name": "DiksalPar", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.38722222, "Longitude": 73.53111111},
            {"Remote Station Id": "112C0062", "Remote Station Name": "Karwande", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.57972222, "Longitude": 73.68361111},
            {"Remote Station Id": "112C0063", "Remote Station Name": "Bardipada", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.71638889, "Longitude": 73.45305556},
            {"Remote Station Id": "112C0064", "Remote Station Name": "Sundarban", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.63222222, "Longitude": 73.4525},
            {"Remote Station Id": "112C0065", "Remote Station Name": "Umbarthan", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.56555556, "Longitude": 73.49444444},
            {"Remote Station Id": "112C0066", "Remote Station Name": "Rakshasbhuvan", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.48277778, "Longitude": 73.47083333},
            {"Remote Station Id": "112C0067", "Remote Station Name": "Khirdi", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.37027778, "Longitude": 73.43638889},
            {"Remote Station Id": "112C0068", "Remote Station Name": "Karshet", "Project Id": 4, "Station Type Id": 2, "Latitude": 20.21, "Longitude": 73.42166667},
            {"Remote Station Id": "112C0031", "Remote Station Name": "Nashik GD", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.98805556, "Longitude": 73.82972222},
            {"Remote Station Id": "111C0060", "Remote Station Name": "Manjur (Handewadi)", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.915, "Longitude": 74.28083333},
            {"Remote Station Id": "111C0056", "Remote Station Name": "Nagamthan", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.73888889, "Longitude": 74.78222222},
            {"Remote Station Id": "111C0043", "Remote Station Name": "Samangaon Malegaon", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.34444444, "Longitude": 75.15805556},
            {"Remote Station Id": "111C0038", "Remote Station Name": "Bhagur", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.32333333, "Longitude": 75.20361111},
            {"Remote Station Id": "111C0023", "Remote Station Name": "Mhaladevi (Induri)", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.54444444, "Longitude": 73.95111111},
            {"Remote Station Id": "111C0015", "Remote Station Name": "Shendurwada", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.66694444, "Longitude": 75.23222222},
            {"Remote Station Id": "111C0008", "Remote Station Name": "Panegaon", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.47666667, "Longitude": 74.79388889},
            {"Remote Station Id": "111C0009", "Remote Station Name": "Newasa", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.55944444, "Longitude": 74.91333333},
            {"Remote Station Id": "73B0E536", "Remote Station Name": "Aurad(Sh)", "Project Id": 4, "Station Type Id": 2, "Latitude": 18.05055556, "Longitude": 76.92555556},
            {"Remote Station Id": "73B0BB98", "Remote Station Name": "Samangaon B", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.94333333, "Longitude": 73.88527778},
            {"Remote Station Id": "73B0C3DA", "Remote Station Name": "Sangamner", "Project Id": 4, "Station Type Id": 2, "Latitude": 19.545, "Longitude": 74.23888889},
            {"Remote Station Id": "73B0CD08", "Remote Station Name": "Raher", "Project Id": 4, "Station Type Id": 2, "Latitude": 18.89694444, "Longitude": 77.67722222},
            {"Remote Station Id": "73B0D0AC", "Remote Station Name": "Kesrali", "Project Id": 4, "Station Type Id": 2, "Latitude": 18.65027778, "Longitude": 77.67833333},
            {"Remote Station Id": "73B4984E", "Remote Station Name": "Kadwa Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.66666667, "Longitude": 73.8},
            {"Remote Station Id": "73B4ADD4", "Remote Station Name": "Mukane Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.8, "Longitude": 73.65833333},
            {"Remote Station Id": "73B4BEA2", "Remote Station Name": "Waki Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.77083333, "Longitude": 73.56666667},
            {"Remote Station Id": "73B4C832", "Remote Station Name": "Karanjvan Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.3, "Longitude": 73.8},
            {"Remote Station Id": "73B50104", "Remote Station Name": "Babhali Barrage", "Project Id": 4, "Station Type Id": 3, "Latitude": 18.853262, "Longitude": 77.820431},
            {"Remote Station Id": "73B56A30", "Remote Station Name": "Kashyapi Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.06888889, "Longitude": 73.60666667},
            {"Remote Station Id": "73B57946", "Remote Station Name": "Gautami Godavari Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.98333333, "Longitude": 73.56666667},
            {"Remote Station Id": "73B589C2", "Remote Station Name": "Punegaon Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.33333333, "Longitude": 73.86666667},
            {"Remote Station Id": "73B5EC24", "Remote Station Name": "Ozarkhed Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.280787, "Longitude": 73.875728},
            {"Remote Station Id": "73B5F180", "Remote Station Name": "Waghad Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.23333333, "Longitude": 73.73333333},
            {"Remote Station Id": "73B5FF52", "Remote Station Name": "Manar Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 18.83333333, "Longitude": 77.31666667},
            {"Remote Station Id": "73B6060A", "Remote Station Name": "Alandi Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.11476, "Longitude": 73.689593},
            {"Remote Station Id": "73B608D8", "Remote Station Name": "Bhavali Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.640601, "Longitude": 73.584109},
            {"Remote Station Id": "73B6157C", "Remote Station Name": "Waldevi Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.902515, "Longitude": 73.681821},
            {"Remote Station Id": "73B61BAE", "Remote Station Name": "Tisgaon Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.25654, "Longitude": 73.959099},
            {"Remote Station Id": "73B620E6", "Remote Station Name": "Adhala Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.64305556, "Longitude": 74.03416667},
            {"Remote Station Id": "73B62E34", "Remote Station Name": "Bhojapur Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.681927, "Longitude": 74.058118},
            {"Remote Station Id": "73B63390", "Remote Station Name": "Bindusara Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 18.7625, "Longitude": 75.74166667},
            {"Remote Station Id": "73B63D42", "Remote Station Name": "Mudgal Barrage", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.08888889, "Longitude": 76.49166667},
            {"Remote Station Id": "73B5A1FC", "Remote Station Name": "Gangapur Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.05, "Longitude": 73.67972222},
            {"Remote Station Id": "111C0003", "Remote Station Name": "Bham Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.66305556, "Longitude": 73.65083333},
            {"Remote Station Id": "111C0057", "Remote Station Name": "Ambadi Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 20.28888889, "Longitude": 75.095},
            {"Remote Station Id": "101C0001", "Remote Station Name": "Darna Dam", "Project Id": 4, "Station Type Id": 3, "Latitude": 19.81277778, "Longitude": 73.74777778},
            {"Remote Station Id": "111C0052", "Remote Station Name": "Mhaladevi (Induri)", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.54444444, "Longitude": 73.95111111},
            {"Remote Station Id": "111C0041", "Remote Station Name": "Nagamthan", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.73888889, "Longitude": 74.78222222},
            {"Remote Station Id": "111C0018", "Remote Station Name": "Samangaon Malegaon", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.35583333, "Longitude": 75.14611111},
            {"Remote Station Id": "112C0005", "Remote Station Name": "Pimpalgaon(Dk)", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.93861111, "Longitude": 73.785},
            {"Remote Station Id": "73B59AB4", "Remote Station Name": "Gangapur Dam", "Project Id": 4, "Station Type Id": 4, "Latitude": 20.05, "Longitude": 73.67972222},
            {"Remote Station Id": "73B5B28A", "Remote Station Name": "Nandur Madhemeshwar Dam", "Project Id": 4, "Station Type Id": 4, "Latitude": 20.025, "Longitude": 74.13333333},
            {"Remote Station Id": "73B53A4C", "Remote Station Name": "Lower Terna", "Project Id": 4, "Station Type Id": 4, "Latitude": 18.0287, "Longitude": 76.431718},
            {"Remote Station Id": "73B51CA0", "Remote Station Name": "Manjra Dam", "Project Id": 4, "Station Type Id": 4, "Latitude": 18.55666667, "Longitude": 76.15833333},
            {"Remote Station Id": "73B4DB44", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.5, "Longitude": 75.33333333},
            {"Remote Station Id": "73B485EA", "Remote Station Name": "Mula Dam", "Project Id": 4, "Station Type Id": 4, "Latitude": 19.34083333, "Longitude": 74.60888889},
            {"Remote Station Id": "73B48B38", "Remote Station Name": "Mula Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.34083333, "Longitude": 74.60888889},
            {"Remote Station Id": "73B4969C", "Remote Station Name": "Mula Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.34083333, "Longitude": 74.60888889},
            {"Remote Station Id": "73B3890C", "Remote Station Name": "Vishnupuri", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.12694444, "Longitude": 77.28083333},
            {"Remote Station Id": "73B41E5A", "Remote Station Name": "Nagazari Barrage", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.78055556, "Longitude": 76.08361111},
            {"Remote Station Id": "73B36AFE", "Remote Station Name": "Majalgaon-G", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.15083333, "Longitude": 76.18694444},
            {"Remote Station Id": "73B37988", "Remote Station Name": "Vishnupuri", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.12694444, "Longitude": 77.28083333},
            {"Remote Station Id": "73B4C6E0", "Remote Station Name": "Waki Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.77083333, "Longitude": 73.56666667},
            {"Remote Station Id": "73B4B070", "Remote Station Name": "Mukane Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.8, "Longitude": 73.65833333},
            {"Remote Station Id": "73B47BBC", "Remote Station Name": "Bhandardara", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.54527778, "Longitude": 73.75833333},
            {"Remote Station Id": "73B2C62E", "Remote Station Name": "Lower Dudhana Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.53083333, "Longitude": 76.39277778},
            {"Remote Station Id": "73B26804", "Remote Station Name": "Khadakpurna", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.06833333, "Longitude": 76.15027778},
            {"Remote Station Id": "73B2D558", "Remote Station Name": "Lower Dudhana Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.53083333, "Longitude": 76.39277778},
            {"Remote Station Id": "73B4E00C", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.5, "Longitude": 75.33333333},
            {"Remote Station Id": "73B4EEDE", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.5, "Longitude": 75.33333333},
            {"Remote Station Id": "73B4F37A", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.5, "Longitude": 75.33333333},
            {"Remote Station Id": "73B4FDA8", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.5, "Longitude": 75.33333333},
            {"Remote Station Id": "73B527E8", "Remote Station Name": "Manjra Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.55666667, "Longitude": 76.15833333},
            {"Remote Station Id": "73B5420E", "Remote Station Name": "Lower Terna", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.0287, "Longitude": 76.431718},
            {"Remote Station Id": "73B5349E", "Remote Station Name": "Manjra Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.55666667, "Longitude": 76.15833333},
            {"Remote Station Id": "73B564E2", "Remote Station Name": "Upper Manar Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.78333333, "Longitude": 77.03333333},
            {"Remote Station Id": "73B5BC58", "Remote Station Name": "Nandur Madhemeshwar Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.025, "Longitude": 74.13333333},
            {"Remote Station Id": "73B5C41A", "Remote Station Name": "Narangi Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.93333333, "Longitude": 74.71666667},
            {"Remote Station Id": "73B5CAC8", "Remote Station Name": "Yeldari Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.71666667, "Longitude": 76.75},
            {"Remote Station Id": "73B5D76C", "Remote Station Name": "Yeldari Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.71666667, "Longitude": 76.75},
            {"Remote Station Id": "73B5D9BE", "Remote Station Name": "Masalga Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.24777778, "Longitude": 76.71666667},
            {"Remote Station Id": "73B5E2F6", "Remote Station Name": "Renapur Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.59722222, "Longitude": 76.59805556},
            {"Remote Station Id": "73B28BF6", "Remote Station Name": "Siddeshwar Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.61277778, "Longitude": 76.97194444},
            {"Remote Station Id": "73B1043E", "Remote Station Name": "Darna Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.80277778, "Longitude": 73.73777778},
            {"Remote Station Id": "73B1A4C6", "Remote Station Name": "Shivna Takali Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.11777778, "Longitude": 75.08111111},
            {"Remote Station Id": "73B25D9E", "Remote Station Name": "Khadakpurna", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.06833333, "Longitude": 76.15027778},
            {"Remote Station Id": "73B16F0A", "Remote Station Name": "Palkhed Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.18694444, "Longitude": 73.88694444},
            {"Remote Station Id": "73B5AF2E", "Remote Station Name": "Gangapur Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.05, "Longitude": 73.67972222},
            {"Remote Station Id": "112C0055", "Remote Station Name": "Waghad Dam- Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.227892, "Longitude": 73.729459},
            {"Remote Station Id": "112C0052", "Remote Station Name": "Karanjvan Dam-Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.29083333, "Longitude": 73.77944444},
            {"Remote Station Id": "112C0053", "Remote Station Name": "Palkhed Dam-Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.19, "Longitude": 73.88888889},
            {"Remote Station Id": "111C0020", "Remote Station Name": "Kadwa Dam-Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.76722222, "Longitude": 73.80083333},
            {"Remote Station Id": "111C0029", "Remote Station Name": "Mula Dam- RBHR", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.33527778, "Longitude": 74.61388889},
            {"Remote Station Id": "111C0031", "Remote Station Name": "Nilwande Dam-PH", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.54722222, "Longitude": 73.905},
            {"Remote Station Id": "111C0032", "Remote Station Name": "Nilwande Dam- LBHR", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.54611111, "Longitude": 73.90388889},
            {"Remote Station Id": "111C0048", "Remote Station Name": "Jayakwadi Dam- Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.48361111, "Longitude": 75.36916667},
            {"Remote Station Id": "111C0049", "Remote Station Name": "Jayakwadi Dam- Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 19.44444444, "Longitude": 75.35777778},
            {"Remote Station Id": "111C0054", "Remote Station Name": "Khulgapur Barrage", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.47638889, "Longitude": 76.675},
            {"Remote Station Id": "111C0058", "Remote Station Name": "Shivna Dam-Canal", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.12083333, "Longitude": 75.08083333},
            {"Remote Station Id": "111C0061", "Remote Station Name": "Bordahegaon Barrage", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.85957, "Longitude": 76.35941},
            {"Remote Station Id": "111C0066", "Remote Station Name": "Takalgaon devala Barrage", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.56888889, "Longitude": 76.32333333},
            {"Remote Station Id": "101C0002", "Remote Station Name": "Gangapur Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.04, "Longitude": 73.6797222},
            {"Remote Station Id": "101C0003", "Remote Station Name": "Nandur Madhemeshwar Dam", "Project Id": 4, "Station Type Id": 5, "Latitude": 20.05, "Longitude": 74.13333},
            {"Remote Station Id": "101C0005", "Remote Station Name": "Waghdari Barrage", "Project Id": 4, "Station Type Id": 5, "Latitude": 18.56694444, "Longitude": 76.50027778},
            {"Remote Station Id": "73B093A6", "Remote Station Name": "Samangaon M", "Project Id": 4, "Station Type Id": 6, "Latitude": 19.34055556, "Longitude": 75.10722222},
            {"Remote Station Id": "73B09D74", "Remote Station Name": "Kotul", "Project Id": 4, "Station Type Id": 6, "Latitude": 19.43416667, "Longitude": 73.96888889},
            {"Remote Station Id": "73B0A63C", "Remote Station Name": "Bharadi", "Project Id": 4, "Station Type Id": 6, "Latitude": 20.42611111, "Longitude": 75.5},
            {"Remote Station Id": "73B0A8EE", "Remote Station Name": "Patoda", "Project Id": 4, "Station Type Id": 6, "Latitude": 18.78333333, "Longitude": 75.46666667},
            {"Remote Station Id": "73B0B54A", "Remote Station Name": "Limboti", "Project Id": 4, "Station Type Id": 6, "Latitude": 18.79444444, "Longitude": 77.07916667},
            {"Remote Station Id": "73B161D8", "Remote Station Name": "Palkhed Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 20.18694444, "Longitude": 73.88694444},
            {"Remote Station Id": "73B0F892", "Remote Station Name": "Darna Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.81277778, "Longitude": 73.74777778},
            {"Remote Station Id": "73B19F8E", "Remote Station Name": "Shivna Takali Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 20.11777778, "Longitude": 75.08111111},
            {"Remote Station Id": "73B1DC84", "Remote Station Name": "Nilwande Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.54583333, "Longitude": 73.90277778},
            {"Remote Station Id": "73B28524", "Remote Station Name": "Siddeshwar Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.61277778, "Longitude": 76.97194444},
            {"Remote Station Id": "73B2534C", "Remote Station Name": "Khadakpurna", "Project Id": 4, "Station Type Id": 7, "Latitude": 20.06833333, "Longitude": 76.15027778},
            {"Remote Station Id": "73B40D2C", "Remote Station Name": "Lendi Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 18.52083333, "Longitude": 77.42083333},
            {"Remote Station Id": "73B35F64", "Remote Station Name": "Majalgaon", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.15083333, "Longitude": 76.18694444},
            {"Remote Station Id": "73B55178", "Remote Station Name": "Upper Manar Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 18.78333333, "Longitude": 77.03333333},
            {"Remote Station Id": "73B2BE6C", "Remote Station Name": "Lower Dudhana Dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.53083333, "Longitude": 76.39277778},
            {"Remote Station Id": "73B3775A", "Remote Station Name": "Vishnupuri", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.12694444, "Longitude": 77.28083333},
            {"Remote Station Id": "111C0001", "Remote Station Name": "Bham dam", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.66305556, "Longitude": 73.65083333},
            {"Remote Station Id": "111C0027", "Remote Station Name": "Tirde", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.73083333, "Longitude": 73.85694444},
            {"Remote Station Id": "111C0019", "Remote Station Name": "Bhagur", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.32527778, "Longitude": 75.205},
            {"Remote Station Id": "111C0006", "Remote Station Name": "Wadala Mahadev", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.6125, "Longitude": 74.71305556},
            {"Remote Station Id": "111C0016", "Remote Station Name": "Pategaon", "Project Id": 4, "Station Type Id": 7, "Latitude": 19.46416667, "Longitude": 75.40277778},
            {"Remote Station Id": "111C0017", "Remote Station Name": "Jayakwadi Dam", "Project Id": 4, "Station Type Id": 8, "Latitude": 19.515, "Longitude": 75.37722222},
            {"Remote Station Id": "111C0030", "Remote Station Name": "Mandohol Dam", "Project Id": 4, "Station Type Id": 8, "Latitude": 19.20111111, "Longitude": 74.3125},
            {"Remote Station Id": "111C0059", "Remote Station Name": "Kolhi", "Project Id": 4, "Station Type Id": 8, "Latitude": 20.05777778, "Longitude": 74.82638889},
            {"Remote Station Id": "111C0053", "Remote Station Name": "Narangi Dam", "Project Id": 4, "Station Type Id": 8, "Latitude": 19.93305556, "Longitude": 74.71388889},
            {"Remote Station Id": "111C0051", "Remote Station Name": "Dheku", "Project Id": 4, "Station Type Id": 8, "Latitude": 20.09861111, "Longitude": 74.94138889},
            {"Remote Station Id": "112C0020", "Remote Station Name": "Alandi dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 20.11472222, "Longitude": 73.68972222},
            {"Remote Station Id": "112C0021", "Remote Station Name": "Mukane Dam-Canal", "Project Id": 4, "Station Type Id": 9, "Latitude": 19.82194444, "Longitude": 73.65694444},
            {"Remote Station Id": "112C0022", "Remote Station Name": "Waldevi Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 19.9025, "Longitude": 73.68222222},
            {"Remote Station Id": "112C0037", "Remote Station Name": "Gangapur Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 20.04, "Longitude": 73.67888889},
            {"Remote Station Id": "112C0038", "Remote Station Name": "Gautami-Godavari dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 19.98833333, "Longitude": 73.57222222},
            {"Remote Station Id": "112C0039", "Remote Station Name": "Kashyapi Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 20.06916667, "Longitude": 73.60916667},
            {"Remote Station Id": "112C0056", "Remote Station Name": "Tisgaon Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 20.25444444, "Longitude": 73.95388889},
            {"Remote Station Id": "112C0057", "Remote Station Name": "Punegaon Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 20.35861111, "Longitude": 73.84},
            {"Remote Station Id": "111C0021", "Remote Station Name": "Adhala Dam-Canal", "Project Id": 4, "Station Type Id": 9, "Latitude": 19.64083333, "Longitude": 74.03194444},
            {"Remote Station Id": "111C0022", "Remote Station Name": "Bhojapur Dam", "Project Id": 4, "Station Type Id": 9, "Latitude": 19.68277778, "Longitude": 74.05833333},
            {"Remote Station Id": "111C0028", "Remote Station Name": "Mula Dam-LBHR", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.345, "Longitude": 74.60055556},
            {"Remote Station Id": "111C0055", "Remote Station Name": "Tembhapuri-Canal", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.74027778, "Longitude": 75.17944444},
            {"Remote Station Id": "111C0067", "Remote Station Name": "Takalgaon devala Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.56888889, "Longitude": 76.32333333},
            {"Remote Station Id": "111C0068", "Remote Station Name": "Renapur Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.56111111, "Longitude": 76.60083333},
            {"Remote Station Id": "111C0065", "Remote Station Name": "Khulgapur Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.47638889, "Longitude": 76.675},
            {"Remote Station Id": "111C0050", "Remote Station Name": "Shivna Dam-LBHR", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.12083333, "Longitude": 75.08111111},
            {"Remote Station Id": "111C0047", "Remote Station Name": "Nagazari Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.78055556, "Longitude": 76.08361111},
            {"Remote Station Id": "111C0034", "Remote Station Name": "Ozar Weir", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.54555556, "Longitude": 74.31166667},
            {"Remote Station Id": "112C0012", "Remote Station Name": "Ghansargaon Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.49055556, "Longitude": 76.65555556},
            {"Remote Station Id": "112C0013", "Remote Station Name": "Kasara Pohergaon barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.54555556, "Longitude": 76.45694444},
            {"Remote Station Id": "112C0014", "Remote Station Name": "Sai barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.45027778, "Longitude": 76.56694444},
            {"Remote Station Id": "112C0015", "Remote Station Name": "Dongargaon Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.28888889, "Longitude": 76.76277778},
            {"Remote Station Id": "112C0016", "Remote Station Name": "Kharola Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.49333333, "Longitude": 76.65611111},
            {"Remote Station Id": "112C0017", "Remote Station Name": "Bindagihal Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.29111111, "Longitude": 76.70833333},
            {"Remote Station Id": "112C0018", "Remote Station Name": "Dhanegaon Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.19583333, "Longitude": 76.90833333},
            {"Remote Station Id": "112C0019", "Remote Station Name": "Shivani Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.3625, "Longitude": 76.68666667},
            {"Remote Station Id": "112C0025", "Remote Station Name": "Wanjarkheda Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.55027778, "Longitude": 76.37222222},
            {"Remote Station Id": "73B387DE", "Remote Station Name": "Vishnupuri", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.12694444, "Longitude": 77.28083333},
            {"Remote Station Id": "73B4A306", "Remote Station Name": "Kadwa Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.66666667, "Longitude": 73.8},
            {"Remote Station Id": "73B4D596", "Remote Station Name": "Karanjvan Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.3, "Longitude": 73.8},
            {"Remote Station Id": "73B2C8FC", "Remote Station Name": "Lower Dudhana Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.53083333, "Longitude": 76.39277778},
            {"Remote Station Id": "73B55FAA", "Remote Station Name": "Upper Manar Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.78333333, "Longitude": 77.03333333},
            {"Remote Station Id": "73B54CDC", "Remote Station Name": "Lower Terna", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.0287, "Longitude": 76.431718},
            {"Remote Station Id": "73B57794", "Remote Station Name": "Kashyapi Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.06888889, "Longitude": 73.60666667},
            {"Remote Station Id": "73B5293A", "Remote Station Name": "Manjra Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.55666667, "Longitude": 76.15833333},
            {"Remote Station Id": "73B50FD6", "Remote Station Name": "Babhali Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.853262, "Longitude": 77.820431},
            {"Remote Station Id": "73B51272", "Remote Station Name": "Babhali Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.853262, "Longitude": 77.820431},
            {"Remote Station Id": "73B59466", "Remote Station Name": "Punegaon Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.33333333, "Longitude": 73.86666667},
            {"Remote Station Id": "73B58710", "Remote Station Name": "Gautami Godavari Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.98333333, "Longitude": 73.56666667},
            {"Remote Station Id": "73B3642C", "Remote Station Name": "Majalgaon Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.15083333, "Longitude": 76.18694444},
            {"Remote Station Id": "73B41088", "Remote Station Name": "Waghdari Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.56694444, "Longitude": 76.50027778},
            {"Remote Station Id": "73B29652", "Remote Station Name": "Siddeshwar Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.61277778, "Longitude": 76.97194444},
            {"Remote Station Id": "73B266D6", "Remote Station Name": "Khadakpurna", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.06833333, "Longitude": 76.15027778},
            {"Remote Station Id": "73B1E7CC", "Remote Station Name": "Nilwande Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 19.54583333, "Longitude": 73.90277778},
            {"Remote Station Id": "73B172AE", "Remote Station Name": "Palkhed Dam", "Project Id": 4, "Station Type Id": 14, "Latitude": 20.18694444, "Longitude": 73.88694444},
            {"Remote Station Id": "73B0DE7E", "Remote Station Name": "Hosur Barrage", "Project Id": 4, "Station Type Id": 14, "Latitude": 18.13861111, "Longitude": 76.94666667},
            {"Remote Station Id": "111C0033", "Remote Station Name": "Bhandardara", "Project Id": 4, "Station Type Id": 15, "Latitude": 19.54694444, "Longitude": 73.75722222},
            {"Remote Station Id": "111C0024", "Remote Station Name": "Newasa", "Project Id": 4, "Station Type Id": 16, "Latitude": 19.55555556, "Longitude": 74.91027778},
            {"Remote Station Id": "111C0025", "Remote Station Name": "Panegaon", "Project Id": 4, "Station Type Id": 16, "Latitude": 19.48194444, "Longitude": 74.795},
            {"Remote Station Id": "111C0026", "Remote Station Name": "Sangamner (Ghulewadi)", "Project Id": 4, "Station Type Id": 16, "Latitude": 19.59805556, "Longitude": 74.19},
            {"Remote Station Id": "112C0004", "Remote Station Name": "Padali", "Project Id": 4, "Station Type Id": 16, "Latitude": 19.80361111, "Longitude": 73.66138889},
            {"Remote Station Id": "101C0004", "Remote Station Name": "Nashik_JVB", "Project Id": 4, "Station Type Id": 16, "Latitude": 20.026111, "Longitude": 73.798333},
            {"Remote Station Id": "112C0044", "Remote Station Name": "Niphad", "Project Id": 4, "Station Type Id": 17, "Latitude": 20.09055556, "Longitude": 74.08194444},
            {"Remote Station Id": "112C0083", "Remote Station Name": "Usthale", "Project Id": 4, "Station Type Id": 17, "Latitude": 20.19888889, "Longitude": 73.545},
            {"Remote Station Id": "111C0012", "Remote Station Name": "Malunja", "Project Id": 4, "Station Type Id": 17, "Latitude": 19.77, "Longitude": 75.01055556},
            {"Remote Station Id": "111C0039", "Remote Station Name": "Kopargaon", "Project Id": 4, "Station Type Id": 17, "Latitude": 19.875, "Longitude": 74.51555556},
            {"Remote Station Id": "56086E6E", "Remote Station Name": "Kamlapur", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.19388889, "Longitude": 80.19194444},
            {"Remote Station Id": "560873CA", "Remote Station Name": "Kudkeli", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.42, "Longitude": 80.40083333},
            {"Remote Station Id": "56087D18", "Remote Station Name": "Gotta", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.055, "Longitude": 80.32416667},
            {"Remote Station Id": "5608834E", "Remote Station Name": "Gatta", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.62861111, "Longitude": 80.53083333},
            {"Remote Station Id": "56088D9C", "Remote Station Name": "Kansansor", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.83638889, "Longitude": 80.35472222},
            {"Remote Station Id": "56089038", "Remote Station Name": "Laheri", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.44027778, "Longitude": 80.73},
            {"Remote Station Id": "73BEC960", "Remote Station Name": "Sadeshwar", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.7375, "Longitude": 78.12472222},
            {"Remote Station Id": "73BED4C4", "Remote Station Name": "Virur", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.63416667, "Longitude": 79.44055556},
            {"Remote Station Id": "73BEDA16", "Remote Station Name": "Wadki", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.28, "Longitude": 78.72},
            {"Remote Station Id": "73BEE15E", "Remote Station Name": "Nakapardi", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.58194444, "Longitude": 78.08638889},
            {"Remote Station Id": "73BEEF8C", "Remote Station Name": "Anjansingi", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.91638889, "Longitude": 78.13805556},
            {"Remote Station Id": "73BEF228", "Remote Station Name": "Gumgaon", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.95388889, "Longitude": 78.34194444},
            {"Remote Station Id": "73BEFCFA", "Remote Station Name": "Malegaon Kali", "Project Id": 7, "Station Type Id": 1, "Latitude": 21.10638889, "Longitude": 78.26555556},
            {"Remote Station Id": "73BF0056", "Remote Station Name": "Shivangaon", "Project Id": 7, "Station Type Id": 1, "Latitude": 21.0325, "Longitude": 77.95222222},
            {"Remote Station Id": "73BF0E84", "Remote Station Name": "MangrulChawala", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.60805556, "Longitude": 77.81888889},
            {"Remote Station Id": "73BF1320", "Remote Station Name": "Sakhra Raja", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.41916667, "Longitude": 79.09611111},
            {"Remote Station Id": "73BF1DF2", "Remote Station Name": "Bazargaon", "Project Id": 7, "Station Type Id": 1, "Latitude": 21.13972222, "Longitude": 78.81916667},
            {"Remote Station Id": "73BF26BA", "Remote Station Name": "Girad", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.66166667, "Longitude": 79.12277778},
            {"Remote Station Id": "73BDA55A", "Remote Station Name": "Kalammahali", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.14388889, "Longitude": 77.19805556},
            {"Remote Station Id": "73BDAB88", "Remote Station Name": "Sawargaon Mangrulpir", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.23166667, "Longitude": 77.39972222},
            {"Remote Station Id": "73BDB62C", "Remote Station Name": "Kurha talni", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.08777778, "Longitude": 78.12083333},
            {"Remote Station Id": "73BDB8FE", "Remote Station Name": "Parwa", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.9875, "Longitude": 78.3375},
            {"Remote Station Id": "73BDC0BC", "Remote Station Name": "Sawargaon Bangla", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.78083333, "Longitude": 77.50111111},
            {"Remote Station Id": "73BDCE6E", "Remote Station Name": "Korat", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.63694444, "Longitude": 78.0425},
            {"Remote Station Id": "73BDD3CA", "Remote Station Name": "Kenwad", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.19694444, "Longitude": 76.80972222},
            {"Remote Station Id": "73BDDD18", "Remote Station Name": "Mohada", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.15527778, "Longitude": 78.40277778},
            {"Remote Station Id": "73BDE650", "Remote Station Name": "Mangrulpir", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.315, "Longitude": 77.345},
            {"Remote Station Id": "73BDE882", "Remote Station Name": "Risod", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.97083333, "Longitude": 76.77888889},
            {"Remote Station Id": "73BDF526", "Remote Station Name": "Fardapur", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.17583333, "Longitude": 76.56388889},
            {"Remote Station Id": "73BDFBF4", "Remote Station Name": "Adan", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.36805556, "Longitude": 77.61888889},
            {"Remote Station Id": "73BE02AC", "Remote Station Name": "Lower Pus", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.78888889, "Longitude": 77.70555556},
            {"Remote Station Id": "5600949E", "Remote Station Name": "Charvidand", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.72333333, "Longitude": 80.35972222},
            {"Remote Station Id": "56009A4C", "Remote Station Name": "Dongargaon B", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.63888889, "Longitude": 80.36361111},
            {"Remote Station Id": "5600A104", "Remote Station Name": "Makepalli", "Project Id": 7, "Station Type Id": 1, "Latitude": 19.82611111, "Longitude": 80.07555556},
            {"Remote Station Id": "5600AFD6", "Remote Station Name": "Khobramendha", "Project Id": 7, "Station Type Id": 1, "Latitude": 20.53388889, "Longitude": 80.10638889},
            {"Remote Station Id": "560079BE", "Remote Station Name": "Bonde", "Project Id": 7, "Station Type Id": 1, "Latitude": 21.06138889, "Longitude": 80.98611111},
            {"Remote Station Id": "560E0000000000", "Remote Station Name": "Sirpur Dam", "Project Id": 7, "Station Type Id": 1, "Latitude": 21.67055556, "Longitude": 80.55472222},
            {"Remote Station Id": "5606FF64", "Remote Station Name": "Kardha", "Project Id": 7, "Station Type Id": 2, "Latitude": 21.14861111, "Longitude": 79.66611111},
            {"Remote Station Id": "560703C8", "Remote Station Name": "Wadshi", "Project Id": 7, "Station Type Id": 2, "Latitude": 21.41694444, "Longitude": 79.87055556},
            {"Remote Station Id": "56070D1A", "Remote Station Name": "Pipriya", "Project Id": 7, "Station Type Id": 2, "Latitude": 21.33972222, "Longitude": 80.55472222},
            {"Remote Station Id": "560710BE", "Remote Station Name": "Tembhurdoh", "Project Id": 7, "Station Type Id": 2, "Latitude": 21.50694444, "Longitude": 78.94638889},
            {"Remote Station Id": "56071E6C", "Remote Station Name": "WagholiButi", "Project Id": 7, "Station Type Id": 2, "Latitude": 20.13388889, "Longitude": 79.92611111},
            {"Remote Station Id": "56072524", "Remote Station Name": "Bhimkund", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.92555556, "Longitude": 79.975},
            {"Remote Station Id": "56072BF6", "Remote Station Name": "Mahagaon", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.44944444, "Longitude": 79.97},
            {"Remote Station Id": "56073652", "Remote Station Name": "Parsewada", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.71111, "Longitude": 79.93},
            {"Remote Station Id": "56073880", "Remote Station Name": "Ghatkul", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.77222222, "Longitude": 79.73638889},
            {"Remote Station Id": "73BE5C02", "Remote Station Name": "Kolgaon (Kolsi)", "Project Id": 7, "Station Type Id": 2, "Latitude": 20.05861111, "Longitude": 77.94805556},
            {"Remote Station Id": "73BE674A", "Remote Station Name": "Takali", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.8625, "Longitude": 79.1225},
            {"Remote Station Id": "73BE6998", "Remote Station Name": "Arni", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.46805556, "Longitude": 77.98611111},
            {"Remote Station Id": "73BE743C", "Remote Station Name": "Anantwadi", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.86888889, "Longitude": 78.27194444},
            {"Remote Station Id": "73BE7AEE", "Remote Station Name": "Murli", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.97, "Longitude": 78.33527778},
            {"Remote Station Id": "73BE84B8", "Remote Station Name": "Sharad", "Project Id": 7, "Station Type Id": 2, "Latitude": 20.27888889, "Longitude": 78.82},
            {"Remote Station Id": "73BF8890", "Remote Station Name": "Movad", "Project Id": 7, "Station Type Id": 2, "Latitude": 21.08916667, "Longitude": 78.14694444},
            {"Remote Station Id": "73BF9534", "Remote Station Name": "Gadbori", "Project Id": 7, "Station Type Id": 2, "Latitude": 20.29055556, "Longitude": 79.58861111},
            {"Remote Station Id": "73BF9BE6", "Remote Station Name": "Ambhora", "Project Id": 7, "Station Type Id": 2, "Latitude": 20.00222222, "Longitude": 79.26944444},
            {"Remote Station Id": "56089EEA", "Remote Station Name": "Bhamragad", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.41666667, "Longitude": 80.58611111},
            {"Remote Station Id": "5608A5A2", "Remote Station Name": "Petta", "Project Id": 7, "Station Type Id": 2, "Latitude": 19.63555556, "Longitude": 80.30638889},
            {"Remote Station Id": "56085BF4", "Remote Station Name": "Nagaram", "Project Id": 7, "Station Type Id": 2, "Latitude": 18.80361111, "Longitude": 79.92361111},
            {"Remote Station Id": "560860BC", "Remote Station Name": "Somnur", "Project Id": 7, "Station Type Id": 2, "Latitude": 18.7325, "Longitude": 80.26361111},
            {"Remote Station Id": "5607ADE2", "Remote Station Name": "Bor", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.97305556, "Longitude": 78.69916667},
            {"Remote Station Id": "560785DC", "Remote Station Name": "Pench Project", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.45416667, "Longitude": 79.19166667},
            {"Remote Station Id": "56079878", "Remote Station Name": "Khekranalla", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.53666667, "Longitude": 78.94833333},
            {"Remote Station Id": "73BFA0AE", "Remote Station Name": "Lower Wenna (Wadgaon Tank)", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.825, "Longitude": 79.04166667},
            {"Remote Station Id": "73BFC548", "Remote Station Name": "Nand Tank", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.72916667, "Longitude": 79.11694444},
            {"Remote Station Id": "73BFD63E", "Remote Station Name": "Lalnala", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.50805556, "Longitude": 79.11833333},
            {"Remote Station Id": "73BF502A", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BEA254", "Remote Station Name": "Amal-Nallah", "Project Id": 7, "Station Type Id": 3, "Latitude": 19.70138889, "Longitude": 79.16694444},
            {"Remote Station Id": "73BEAC86", "Remote Station Name": "Goki", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.30416667, "Longitude": 77.92472222},
            {"Remote Station Id": "73BEB122", "Remote Station Name": "Saikheda", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.10944444, "Longitude": 78.4825},
            {"Remote Station Id": "73BEBFF0", "Remote Station Name": "Waghadi", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.26805556, "Longitude": 78.30694444},
            {"Remote Station Id": "73BEC7B2", "Remote Station Name": "Koradi", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.2275, "Longitude": 76.47083333},
            {"Remote Station Id": "73BF35CC", "Remote Station Name": "Bembla", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.605, "Longitude": 78.13555556},
            {"Remote Station Id": "73BFE3A4", "Remote Station Name": "Upper Wardha", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.27638889, "Longitude": 78.05722222},
            {"Remote Station Id": "73BFFE00", "Remote Station Name": "Vena Project", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.13361111, "Longitude": 79.86694444},
            {"Remote Station Id": "73BE8A6A", "Remote Station Name": "Upper Penganga (Isapur Dam)", "Project Id": 7, "Station Type Id": 3, "Latitude": 19.76416667, "Longitude": 77.37638889},
            {"Remote Station Id": "73BE2440", "Remote Station Name": "Pentakli", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.305, "Longitude": 76.44694444},
            {"Remote Station Id": "73BE41A6", "Remote Station Name": "Upper Pus", "Project Id": 7, "Station Type Id": 3, "Latitude": 19.99111111, "Longitude": 77.45888889},
            {"Remote Station Id": "560740C2", "Remote Station Name": "Bawanthadi", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.54166667, "Longitude": 79.54166667},
            {"Remote Station Id": "560753B4", "Remote Station Name": "Sirpur Dam", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.67055556, "Longitude": 80.55472222},
            {"Remote Station Id": "56075D66", "Remote Station Name": "Pujari Tola", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.23722222, "Longitude": 80.43388889},
            {"Remote Station Id": "5606C42C", "Remote Station Name": "Itiadoh", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.81722222, "Longitude": 80.19444444},
            {"Remote Station Id": "56077558", "Remote Station Name": "Kalisarar", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.17666667, "Longitude": 80.45388889},
            {"Remote Station Id": "5607C6D6", "Remote Station Name": "Bodalkasa", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.355, "Longitude": 80.025},
            {"Remote Station Id": "5607C804", "Remote Station Name": "Chorakhmara", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.28972222, "Longitude": 80.06694444},
            {"Remote Station Id": "5607D5A0", "Remote Station Name": "Khairbandha", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.48611111, "Longitude": 80.07305556},
            {"Remote Station Id": "5607DB72", "Remote Station Name": "Managarh", "Project Id": 7, "Station Type Id": 3, "Latitude": 80.07305556, "Longitude": 80.20027778},  # Note: Latitude might be incorrect
            {"Remote Station Id": "5607E03A", "Remote Station Name": "Chulbandh", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.22916667, "Longitude": 80.21972222},
            {"Remote Station Id": "5607EEE8", "Remote Station Name": "Khindsi", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.37083333, "Longitude": 79.37722222},
            {"Remote Station Id": "5607F34C", "Remote Station Name": "Umari", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.42916667, "Longitude": 78.79444444},
            {"Remote Station Id": "5607FD9E", "Remote Station Name": "Kolar", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.40027778, "Longitude": 78.815},
            {"Remote Station Id": "5608055A", "Remote Station Name": "Kesarnalla", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.36694444, "Longitude": 78.8336111},
            {"Remote Station Id": "56080B88", "Remote Station Name": "Chandrabhaga", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.26944444, "Longitude": 78.77638889},
            {"Remote Station Id": "5608162C", "Remote Station Name": "Mordham", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.22222222, "Longitude": 78.80555556},
            {"Remote Station Id": "560818FE", "Remote Station Name": "Pandrabodi", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.82527778, "Longitude": 79.28111111},
            {"Remote Station Id": "560823B6", "Remote Station Name": "Makardhokada", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.86277778, "Longitude": 79.21277778},
            {"Remote Station Id": "56082D64", "Remote Station Name": "Saiki", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.915, "Longitude": 79.18444444},
            {"Remote Station Id": "560830C0", "Remote Station Name": "Navegaon Bandh", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.92027778, "Longitude": 80.11111111},
            {"Remote Station Id": "5610000000000000", "Remote Station Name": "Umarzari", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.16611111, "Longitude": 80.26611111},  # Converted scientific notation
            {"Remote Station Id": "56084650", "Remote Station Name": "Rengepar", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.26611111, "Longitude": 80.1275},
            {"Remote Station Id": "56084882", "Remote Station Name": "Ghodazari", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.50277778, "Longitude": 79.50194444},
            {"Remote Station Id": "56085526", "Remote Station Name": "Nalleshwar", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.23361111, "Longitude": 79.58361111},
            {"Remote Station Id": "56011EA2", "Remote Station Name": "Asolamendha", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.25444444, "Longitude": 79.82166667},
            {"Remote Station Id": "5606D75A", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 3, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5600BCA0", "Remote Station Name": "Totladoh", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.65833333, "Longitude": 79.23361111},
            {"Remote Station Id": "5600E20E", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "56006AC8", "Remote Station Name": "Erai", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.16777778, "Longitude": 79.30472222},
            {"Remote Station Id": "560001FC", "Remote Station Name": "Kanholibara", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.94444444, "Longitude": 78.84444444},
            {"Remote Station Id": "56000F2E", "Remote Station Name": "Jam Project", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.22305556, "Longitude": 78.63861111},
            {"Remote Station Id": "5600128A", "Remote Station Name": "Chargaon", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.39444444, "Longitude": 79.17527778},
            {"Remote Station Id": "56001C58", "Remote Station Name": "Chandai", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.41694444, "Longitude": 79.225},
            {"Remote Station Id": "56002710", "Remote Station Name": "Labhansarad", "Project Id": 7, "Station Type Id": 3, "Latitude": 19.70138889, "Longitude": 79.05027778},
            {"Remote Station Id": "560029C2", "Remote Station Name": "Dongargaon", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.92472222, "Longitude": 78.68194444},
            {"Remote Station Id": "56003466", "Remote Station Name": "Borgaon", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.11305556, "Longitude": 78.18972222},
            {"Remote Station Id": "56003AB4", "Remote Station Name": "Dham", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.97305556, "Longitude": 78.4475},
            {"Remote Station Id": "560042F6", "Remote Station Name": "Madan", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.93861111, "Longitude": 78.53527778},
            {"Remote Station Id": "56004C24", "Remote Station Name": "Panchdhara", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.30027778, "Longitude": 76.93583333},
            {"Remote Station Id": "56005180", "Remote Station Name": "Pothra", "Project Id": 7, "Station Type Id": 3, "Latitude": 20.55833333, "Longitude": 79.04111111},
            {"Remote Station Id": "56005F52", "Remote Station Name": "Kar", "Project Id": 7, "Station Type Id": 3, "Latitude": 21.22138889, "Longitude": 78.46611111},
            {"Remote Station Id": "5600776C", "Remote Station Name": "Erai", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.16777778, "Longitude": 79.30472222},
            {"Remote Station Id": "5600ECDC", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "5600F178", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "5600FFAA", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "56010306", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "56010DD4", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "5600C4E2", "Remote Station Name": "Totladoh", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.65833333, "Longitude": 79.23361111},
            {"Remote Station Id": "5600CA30", "Remote Station Name": "Totladoh", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.65833333, "Longitude": 79.23361111},
            {"Remote Station Id": "5606D988", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5606E2C0", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5606EC12", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5606F1B6", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5600893A", "Remote Station Name": "Sirpur Dam", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.67055556, "Longitude": 80.55472222},
            {"Remote Station Id": "56077B8A", "Remote Station Name": "Kalisarar", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.17666667, "Longitude": 80.45388889},
            {"Remote Station Id": "5607662E", "Remote Station Name": "Pujari Tola", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.23722222, "Longitude": 80.43388889},
            {"Remote Station Id": "560768FC", "Remote Station Name": "Pujari Tola", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.23722222, "Longitude": 80.43388889},
            {"Remote Station Id": "561000000000014", "Remote Station Name": "Bawanthadi", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.54166667, "Longitude": 79.54166667},
            {"Remote Station Id": "73BE11DA", "Remote Station Name": "Lower Pus", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.78888889, "Longitude": 77.70555556},
            {"Remote Station Id": "73BE2A92", "Remote Station Name": "Pentakli", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.305, "Longitude": 76.44694444},
            {"Remote Station Id": "73BE3736", "Remote Station Name": "Pentakli", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.305, "Longitude": 76.44694444},
            {"Remote Station Id": "73BE97CE", "Remote Station Name": "Upper Penganga (Isapur Dam)", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.76416667, "Longitude": 77.37638889},
            {"Remote Station Id": "73BE991C", "Remote Station Name": "Upper Penganga (Isapur Dam)", "Project Id": 7, "Station Type Id": 5, "Latitude": 19.76416667, "Longitude": 77.37638889},
            {"Remote Station Id": "73BFED76", "Remote Station Name": "Upper Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.27638889, "Longitude": 78.05722222},
            {"Remote Station Id": "73BFF0D2", "Remote Station Name": "Upper Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.27638889, "Longitude": 78.05722222},
            {"Remote Station Id": "73BF3B1E", "Remote Station Name": "Bembla", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.605, "Longitude": 78.13555556},
            {"Remote Station Id": "73BF435C", "Remote Station Name": "Bembla", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.605, "Longitude": 78.13555556},
            {"Remote Station Id": "73BF4D8E", "Remote Station Name": "Bembla", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.605, "Longitude": 78.13555556},
            {"Remote Station Id": "73BF6B62", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BF76C6", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BF7814", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BF8642", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BFD8EC", "Remote Station Name": "Lalnala", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.50805556, "Longitude": 79.11833333},
            {"Remote Station Id": "73BFCB9A", "Remote Station Name": "Nand Tank", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.72916667, "Longitude": 79.11694444},
            {"Remote Station Id": "73BFAE7C", "Remote Station Name": "Lower Wenna (Wadgaon Tank)", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.825, "Longitude": 79.04166667},
            {"Remote Station Id": "73BFB3D8", "Remote Station Name": "Lower Wenna (Wadgaon Tank)", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.825, "Longitude": 79.04166667},
            {"Remote Station Id": "73BFBD0A", "Remote Station Name": "Lower Wenna (Wadgaon Tank)", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.825, "Longitude": 79.04166667},
            {"Remote Station Id": "5607A330", "Remote Station Name": "Khekranalla", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.53666667, "Longitude": 78.94833333},
            {"Remote Station Id": "56078B0E", "Remote Station Name": "Pench Project", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.45416667, "Longitude": 79.19166667},
            {"Remote Station Id": "560796AA", "Remote Station Name": "Pench Project", "Project Id": 7, "Station Type Id": 5, "Latitude": 21.45416667, "Longitude": 79.19166667},
            {"Remote Station Id": "5607B046", "Remote Station Name": "Bor", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.97305556, "Longitude": 78.69916667},
            {"Remote Station Id": "5607BE94", "Remote Station Name": "Bor", "Project Id": 7, "Station Type Id": 5, "Latitude": 20.97305556, "Longitude": 78.69916667},
            {"Remote Station Id": "5600D946", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 6, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "73BF65B0", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 6, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BE4F74", "Remote Station Name": "Upper Pus", "Project Id": 7, "Station Type Id": 6, "Latitude": 19.99111111, "Longitude": 77.45888889},
            {"Remote Station Id": "73BE1F08", "Remote Station Name": "Pentakli", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.305, "Longitude": 76.44694444},
            {"Remote Station Id": "73BE39E4", "Remote Station Name": "Upper Pus", "Project Id": 7, "Station Type Id": 7, "Latitude": 19.99111111, "Longitude": 77.45888889},
            {"Remote Station Id": "73BF5EF8", "Remote Station Name": "Lower Wardha", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.87694444, "Longitude": 78.25972222},
            {"Remote Station Id": "73BF2868", "Remote Station Name": "Bembla", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.605, "Longitude": 78.13555556},
            {"Remote Station Id": "5606CAFE", "Remote Station Name": "Dina", "Project Id": 7, "Station Type Id": 7, "Latitude": 19.78361111, "Longitude": 80.11694444},
            {"Remote Station Id": "5606BC6E", "Remote Station Name": "Itiadoh", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.81722222, "Longitude": 80.19444444},
            {"Remote Station Id": "5600D794", "Remote Station Name": "Gosekhurd", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.8625, "Longitude": 79.6075},
            {"Remote Station Id": "56011070", "Remote Station Name": "Asolamendha", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.25444444, "Longitude": 79.82166667},
            {"Remote Station Id": "5600B272", "Remote Station Name": "Totladoh", "Project Id": 7, "Station Type Id": 7, "Latitude": 21.65833333, "Longitude": 79.23361111},
            {"Remote Station Id": "5600641A", "Remote Station Name": "Erai", "Project Id": 7, "Station Type Id": 7, "Latitude": 20.16777778, "Longitude": 79.30472222},
            {"Remote Station Id": "73BE0C7E", "Remote Station Name": "Lower Pus", "Project Id": 7, "Station Type Id": 14, "Latitude": 19.78888889, "Longitude": 77.70555556},
            {"Remote Station Id": "73BE52D0", "Remote Station Name": "Pakdiguddam", "Project Id": 7, "Station Type Id": 15, "Latitude": 19.21, "Longitude": 79.03305556}    
    
        ])
    # Load station data
    stations_df = load_station_metadata()
    stations_df["Project"] = stations_df["Project Id"].map(PROJECTS)
    
    # Add alerts to stations
    stations_df["Alert"] = None
    for idx, row in stations_df.iterrows():
        station_id = row["Remote Station Id"]
        station_name = row["Remote Station Name"]
        
        if station_name in DATA_SOURCES:
            with st.spinner(f"Checking alerts for {station_name}..."):
                try:
                    df = load_station_data(station_name)
                    alerts = get_station_alerts(station_id, df)
                    if alerts:
                        stations_df.at[idx, "Alert"] = ", ".join(alerts)
                except Exception as e:
                    st.error(f"Error processing station {station_name}: {str(e)}")
                    continue
    
    # Create the map
    fig = go.Figure()
    
    # Add normal stations
    normal_stations = stations_df[stations_df["Alert"].isnull()]
    if not normal_stations.empty:
        fig.add_trace(go.Scattermapbox(
            lat=normal_stations["Latitude"],
            lon=normal_stations["Longitude"],
            mode="markers",
            marker=dict(
                size=12,
                color="blue",
                opacity=0.7
            ),
            name="Normal",
            hovertext=normal_stations.apply(
                lambda row: f"<b>{row['Remote Station Name']}</b><br>"
                          f"ID: {row['Remote Station Id']}<br>"
                          f"Project: {row['Project']}<br>"
                          f"Status: Normal",
                axis=1
            ),
            hoverinfo="text"
        ))
    
    # Add stations with alerts - made more visible
    alert_stations = stations_df[stations_df["Alert"].notnull()]
    if not alert_stations.empty:
        fig.add_trace(go.Scattermapbox(
            lat=alert_stations["Latitude"],
            lon=alert_stations["Longitude"],
            mode="markers",
            marker=dict(
                size=20,  # Larger size for alerts
                color="red",
                symbol="circle",
                opacity=0.9
            ),
            name="ALERT",
            hovertext=alert_stations.apply(
                lambda row: f"<b>{row['Remote Station Name']}</b><br>"
                          f"ID: {row['Remote Station Id']}<br>"
                          f"Project: {row['Project']}<br>"
                          f"<span style='color:red'><b>ALERT: {row['Alert']}</b></span>",
                axis=1
            ),
            hoverinfo="text"
        ))
    
    # Configure map layout
    fig.update_layout(
        mapbox_style="carto-positron",
        mapbox_zoom=5.8,
        mapbox_center={"lat": 19.7515, "lon": 75.7139},
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
        height=650,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        title="<b>Water Monitoring Stations with Alerts</b>",
        title_x=0.05,
        title_font=dict(size=20)
    )
    
    # Add custom legend
    fig.add_annotation(
        x=0.05,
        y=0.05,
        xref="paper",
        yref="paper",
        text="<span style='color:red'>⬤</span> Alert Station &nbsp;&nbsp; <span style='color:blue'>⬤</span> Normal Station",
        showarrow=False,
        font=dict(size=14),
        bgcolor="white",
        bordercolor="gray",
        borderwidth=1,
        borderpad=4
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Display alerts table for visibility
    if not alert_stations.empty:
        st.markdown("### ⚠️ Active Alerts")
        alert_table = alert_stations[["Remote Station Name", "Project", "Alert"]].copy()
        alert_table.columns = ["Station Name", "Project", "Alert"]
        st.dataframe(alert_table.style.applymap(
            lambda x: "background-color: #ffcccc" if x else "", 
            subset=["Alert"]
        ), use_container_width=True)
    
    # Alert explanation
    st.info("""
        **Alert Indicators Explained:**  
        🔴 Red markers indicate stations with critical alerts.  
        Alerts include: 
        - Low Battery (<10.5V)
        - EPAN: Values 0-50 or 200+, Daily change >15mm, Same value for 4 days
        - GATE: Any gate open
        - RIVER/DAM: Water level change >1m
        - ARS/AWS: Rain >100mm, Sensor zero readings
    """)        
                                                                                                                                                                                  

def show_categories_tab():
    try:
        # Initialize session states
        if "load_state" not in st.session_state:
            st.session_state.load_state = False
        if "cached_data" not in st.session_state:
            st.session_state.cached_data = {}
        if "selected_date" not in st.session_state:
            st.session_state.selected_date = datetime.now().date()

        # Load master tables
        master_tables = fetch_master_tables()
        if master_tables is None:
            st.warning("Loading master tables...")
            return

        # Simplified categories mapping
        simplified_categories = {
            'ARS': [1, 7, 8, 11, 15, 16, 17, 18],  # All station types containing ARS
            'AWS': [6, 16],                         # All station types containing AWS
            'River': [2, 17],                       # All station types containing River
            'Dam': [3, 8, 13, 14, 15, 18],         # All station types containing Dam
            'Gate': [5, 9, 10, 11, 12, 13, 14, 18], # All station types containing Gate
            'EPAN': [4, 7, 10, 11, 12, 15, 16]      # All station types containing EPAN
        }

        # Date input
        st.session_state.selected_date = st.date_input(
            "Select Date", 
            value=st.session_state.selected_date,
            key="station_date_selector"
        )
        selected_date_str = st.session_state.selected_date.strftime("%Y-%m-%d")

        # Station category selection
        selected_category = st.selectbox(
            "Select Station Category",
            list(simplified_categories.keys()),
            key="category_select"
        )

        # Get relevant station type IDs for selected category
        relevant_station_type_ids = simplified_categories[selected_category]

        # Filter locations by station type
        filtered_locations = master_tables['locations'][
            master_tables['locations']['station_type_id'].isin(relevant_station_type_ids)
        ]

        # Project selection
        project_options = ["All Projects"] + master_tables['projects'][
            master_tables['projects']['mst_project_id'].isin(filtered_locations['project_id'].unique())
        ]['mst_project_name'].tolist()

        selected_project = st.selectbox(
            "Select Project", 
            project_options,
            key="project_select"
        )

        # Filter locations by project if needed
        if selected_project != "All Projects":
            project_id = master_tables['projects'][
                master_tables['projects']['mst_project_name'] == selected_project
            ]['mst_project_id'].values[0]
            filtered_locations = filtered_locations[filtered_locations['project_id'] == project_id]

        # Location selection
        location_options = ["All Locations"] + [
            f"{row['location_id']} ({row['location_name']})"
            for _, row in filtered_locations.iterrows()
        ]

        selected_location = st.selectbox(
            "Select Location",
            location_options,
            key="location_select"
        )

        # Load data button
        if st.button("Load Data", key="load_data_button"):
            with st.spinner(f"Loading {selected_category} data..."):
                # Determine location IDs to filter by
                location_ids = None
                if selected_location != "All Locations":
                    location_id = selected_location.split(' (')[0]
                    location_ids = [location_id]
                else:
                    location_ids = filtered_locations['location_id'].tolist()

                # Get the correct data table name
                data_table = get_data_table_name(selected_category)
                if not data_table:
                    st.error(f"No data table mapped for station type: {selected_category}")
                    return

                # Build the query
                engine = create_db_connection()
                if not engine:
                    return

                try:
                    query = f"""
                        SELECT * FROM {data_table}
                        WHERE location_id IN :location_ids
                        AND DATE(last_updated) = :selected_date
                    """
                    
                    params = {
                        'location_ids': tuple(location_ids),
                        'selected_date': selected_date_str
                    }

                    with engine.connect() as connection:
                        result = connection.execute(text(query), params)
                        df = pd.DataFrame(result.fetchall(), columns=result.keys())

                    if not df.empty:
                        st.success(f"Found {len(df)} records for {selected_date_str}")
                        
                        # Display data
                        columns_to_exclude = ['data_date', 'data_time', 'last_updated_dt']
                        display_df = df.drop(columns=[col for col in columns_to_exclude if col in df.columns])
                        
                        st.dataframe(
                            display_df,
                            use_container_width=True,
                            height=min(400, len(display_df) * 35 + 50)
                        )
                        
                        # Download button
                        csv = display_df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download Data",
                            data=csv,
                            file_name=f"{selected_category}_data_{selected_date_str.replace('-', '')}.csv",
                            mime='text/csv'
                        )
                        
                        # Alert detection
                        alert_rows = detect_alerts(selected_category, df)
                        
                        if alert_rows:
                            st.markdown("---")
                            st.subheader(f"⚠ Alerts for {selected_date_str}")
                            st.dataframe(
                                pd.DataFrame(alert_rows),
                                use_container_width=True,
                                height=min(400, len(alert_rows) * 35 + 50))
                        else:
                            st.success(f"✅ No alerts detected for {selected_date_str}")
                    else:
                        st.warning(f"No data found for the selected filters on {selected_date_str}")
                
                except Exception as e:
                    st.error(f"Error loading data: {str(e)}")
                finally:
                    if engine:
                        engine.dispose()

    except Exception as e:
        st.error(f"Error in categories tab: {str(e)}")
        st.stop()

def detect_alerts(station_type, data):
    """Detect alerts based on station type and data"""
    alert_rows = []
    
    for _, row in data.iterrows():
        alert_info = {}
        alert_detected = False
        
        # Common checks for all stations
        if 'batt_volt' in row and pd.notnull(row['batt_volt']):
            try:
                batt_volt = float(row['batt_volt'])
                if batt_volt < 10.5:
                    alert_info['alert_type'] = 'Low Battery (<10.5V)'
                    alert_info['batt_volt'] = batt_volt
                    alert_detected = True
            except:
                pass
        
        # Station-specific checks
        if station_type == 'Gate':
            gate_cols = [col for col in data.columns if re.match(r'^g\d+$', col)]
            for col in gate_cols:
                if col in row and pd.notnull(row[col]):
                    try:
                        if float(row[col]) > 0.00:
                            alert_info['alert_type'] = 'Gate Open (>0.00)'
                            alert_info[col] = row[col]
                            alert_detected = True
                            break
                    except:
                        continue
        
        elif station_type == 'EPAN' and 'epan_water_depth' in row:
            try:
                current_depth = float(row['epan_water_depth'])
                
                # Check for water depth thresholds
                if current_depth <= 50 or current_depth >= 200:
                    alert_info['alert_type'] = f'Water Depth {"≤50" if current_depth <=50 else "≥200"}'
                    alert_info['epan_water_depth'] = current_depth
                    alert_detected = True
            except:
                pass
        
        elif station_type == 'AWS':
            # Initialize alert type list
            alert_types = []
            
            # Check for zero values in critical measurements
            zero_value_cols = ['atmospheric_pressure', 'temperature', 'humidity', 'solar_radiation', 'wind_speed']
            for col in zero_value_cols:
                if col in row and pd.notnull(row[col]):
                    try:
                        if float(row[col]) == 0:
                            alert_types.append(f'{col} is 0')
                    except:
                        pass
            
            # Check for high rain values
            rain_cols = ['hourly_rain', 'daily_rain']
            for col in rain_cols:
                if col in row and pd.notnull(row[col]):
                    try:
                        if float(row[col]) > 100:
                            alert_types.append(f'{col} >100mm')
                    except:
                        pass
            
            # Check for high wind speed
            if 'wind_speed' in row and pd.notnull(row['wind_speed']):
                try:
                    if float(row['wind_speed']) > 30:
                        alert_types.append('Wind Speed >30')
                except:
                    pass
            
            # Check for high temperature
            if 'temperature' in row and pd.notnull(row['temperature']):
                try:
                    if float(row['temperature']) > 40:
                        alert_types.append('Temperature >40')
                except:
                    pass
            
            if alert_types:
                alert_info['alert_type'] = ', '.join(alert_types)
                alert_detected = True
        
        elif station_type in ['River', 'Dam'] and 'level_mtr' in row:
            try:
                current_level = float(row['level_mtr'])
                
                # Check for extreme levels
                if current_level <= 0 or current_level >= 100:
                    alert_info['alert_type'] = f'Level {"≤0" if current_level <=0 else "≥100"}m'
                    alert_info['level_mtr'] = current_level
                    alert_detected = True
            except:
                pass
        
        if alert_detected:
            alert_info.update(row.to_dict())
            alert_rows.append(alert_info)
    
    return alert_rows
            
            
            
            
            
            
            
            
            
            
            
            
def show_history_tab():
    try:
        st.subheader("Historical Data Explorer")
        
        # Load master tables
        master_tables = fetch_master_tables()
        if master_tables is None:
            st.warning("Loading master tables...")
            return
        
        current_date = datetime.now().date()
        
        # Date range selection
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", 
                                     value=current_date - timedelta(days=7),
                                     key="hist_start_date")
        with col2:
            end_date = st.date_input("End Date", 
                                   value=current_date,
                                   key="hist_end_date")

        date_range_option = st.radio(
            "Quick Date Range",
            options=["Last 7 Days", "Last 15 Days", "Last 30 Days", "Custom Range"],
            index=0,
            horizontal=True,
            key="hist_date_range"
        )

        # Calculate dates based on selection
        if date_range_option == "Last 7 Days":
            start_date = current_date - timedelta(days=6)
            end_date = current_date
        elif date_range_option == "Last 15 Days":
            start_date = current_date - timedelta(days=14)
            end_date = current_date
        elif date_range_option == "Last 30 Days":
            start_date = current_date - timedelta(days=29)
            end_date = current_date

        if start_date > end_date:
            st.error("End date must be after start date")
            return

        # Station type selection
        simplified_categories = ['ARS', 'AWS', 'River', 'Dam', 'Gate', 'EPAN']
        selected_category = st.selectbox(
            "Select Station Category", 
            simplified_categories, 
            key="hist_station_category"
        )

        # Get relevant station type IDs
        relevant_station_type_ids = [
            type_id for type_id, category in master_tables['simplified_categories'].items() 
            if category == selected_category
        ]

        # Project selection
        filtered_locations = master_tables['locations'][
            master_tables['locations']['station_type_id'].isin(relevant_station_type_ids)
        ]

        project_options = ["All Projects"] + master_tables['projects'][
            master_tables['projects']['mst_project_id'].isin(filtered_locations['project_id'].unique())
        ]['mst_project_name'].tolist()

        selected_project = st.selectbox(
            "Select Project", 
            project_options, 
            key="hist_project"
        )

        # Filter locations by project if needed
        if selected_project != "All Projects":
            project_id = master_tables['projects'][
                master_tables['projects']['mst_project_name'] == selected_project
            ]['mst_project_id'].values[0]
            filtered_locations = filtered_locations[filtered_locations['project_id'] == project_id]

        # Location selection
        location_options = ["All Locations"] + [
            f"{row['location_id']} ({row['location_name']})"
            for _, row in filtered_locations.iterrows()
        ]

        selected_location = st.selectbox(
            "Select Location",
            location_options,
            key="hist_location"
        )

        # Load data button
        if st.button("Load Data", key="hist_load_data"):
            with st.spinner(f"Loading {selected_category} data..."):
                location_ids = None
                if selected_location != "All Locations":
                    location_id = selected_location.split(' (')[0]
                    location_ids = [location_id]
                else:
                    location_ids = filtered_locations['location_id'].tolist()

                df = load_station_data(
                    selected_category,
                    location_ids=location_ids,
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d')
                )

                if not df.empty:
                    st.success(f"Found {len(df)} records")
                    
                    # Display data
                    st.dataframe(
                        df,
                        use_container_width=True,
                        height=min(400, len(df) * 35 + 50)
                    )
                    
                    # Download button
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="Download Data",
                        data=csv,
                        file_name=f"{selected_category}data{start_date.strftime('%Y%m%d')}to{end_date.strftime('%Y%m%d')}.csv",
                        mime='text/csv'
                    )
                else:
                    st.warning("No data found for selected filters")

    except Exception as e:
        st.error(f"Error loading history data: {str(e)}")
        st.stop()


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
                        full_station_df = fetch_master_tables(
                            table_name=table_name,
                            date_column='data_date'
                        )
                        
                        # Create a copy for the date filtering and display
                        filtered_df = full_station_df.copy()
                        
                        if not filtered_df.empty:
                            # Apply project filter
                            if selected_project != "All Projects" and 'project_name' in filtered_df.columns:
                                filtered_df = filtered_df[filtered_df['project_name'] == selected_project]
                                full_station_df = full_station_df[full_station_df['project_name'] == selected_project]
                            
                            # Apply location filter using location_id
                            if 'location_id' in filtered_df.columns:
                                filtered_df = filtered_df[filtered_df['location_id'] == selected_location]
                                full_station_df = full_station_df[full_station_df['location_id'] == selected_location]
                            
                            # Now handle date filtering based on table type
                            date_column = 'last_updated' if 'last_updated' in filtered_df.columns else 'data_date'
                            
                            if display_name == 'ARS':
                                # ARS table has proper DATETIME format
                                filtered_df['datetime_col'] = pd.to_datetime(filtered_df[date_column])
                                if start_date and end_date:
                                    start_dt = pd.to_datetime(start_date)
                                    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                                    filtered_df = filtered_df[
                                        (filtered_df['datetime_col'] >= start_dt) & 
                                        (filtered_df['datetime_col'] < end_dt)
                                    ]
                            else:
                                # Other tables have VARCHAR dates in 'dd/mm/yyyy HH:MM' format
                                filtered_df['datetime_col'] = pd.to_datetime(
                                    filtered_df[date_column], 
                                    format='%d/%m/%Y %H:%M', 
                                    errors='coerce'
                                )
                                filtered_df = filtered_df[filtered_df['datetime_col'].notna()]
                                
                                if start_date and end_date:
                                    start_dt = pd.to_datetime(start_date)
                                    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                                    filtered_df = filtered_df[
                                        (filtered_df['datetime_col'] >= start_dt) & 
                                        (filtered_df['datetime_col'] < end_dt)
                                    ]
                            
                            if not filtered_df.empty:
                                # Remove temporary columns before displaying
                                filtered_df = filtered_df.drop(columns=['datetime_col'], errors='ignore')
                                
                                # Initialize alerts list for this station
                                station_alerts = []
                                
                                # Check for alerts in the data
                                for _, row in filtered_df.iterrows():
                                    alert_detected = False
                                    alert_info = {
                                        'station': display_name,
                                        'location': selected_location,
                                        'project': selected_project if selected_project != "All Projects" else "All",
                                        'timestamp': row.get('last_updated', row.get('data_date', '')),
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
                                                current_date = pd.to_datetime(
                                                    row.get('last_updated', row.get('data_date', '')), 
                                                    format='%d/%m/%Y %H:%M', 
                                                    errors='coerce'
                                                )
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
                                                check_date = pd.to_datetime(
                                                    row.get('last_updated', row.get('data_date', '')), 
                                                    format='%d/%m/%Y %H:%M', 
                                                    errors='coerce'
                                                ) - timedelta(days=days_checked + 1)
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
                Showing all data where dates fall between {start_date.strftime('%d/%m/%Y')} 
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
                        
                        # Convert date to datetime for plotting
                        date_column = 'last_updated' if 'last_updated' in df.columns else 'data_date'
                        
                        if display_name == 'ARS':
                            df['plot_datetime'] = pd.to_datetime(df[date_column])
                        else:
                            df['plot_datetime'] = pd.to_datetime(
                                df[date_column], 
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
                    
                    # Convert date to datetime for plotting
                    date_column = 'last_updated' if 'last_updated' in epan_df.columns else 'data_date'
                    epan_df['plot_datetime'] = pd.to_datetime(
                        epan_df[date_column], 
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
                
                
                
def show_trends_tab():
    st.subheader("Advanced Graphical Analysis")
    
    # Initialize session state for date range and button states if not exists
    if 'start_date' not in st.session_state:
        st.session_state.start_date = None
        st.session_state.end_date = None
        st.session_state.active_date_button = 'custom'
    
    # Initialize visibility flags for all graphs
    visibility_flags = [
        'show_batt', 'show_epan', 'show_epan_diff', 'show_gate',
        'show_rain', 'show_ars_rain', 'show_aws_params', 'show_river_level', 'show_dam_level'
    ]
    for flag in visibility_flags:
        if flag not in st.session_state:
            st.session_state[flag] = True  # Default to visible

    # Initialize all graph and alert states if they don't exist
    graph_states = [
        'batt_fig', 'epan_fig', 'epan_diff_fig', 'gate_fig',
        'rain_fig', 'ars_rain_fig', 'aws_params_fig', 'river_level_fig', 'dam_level_fig'
    ]
    for state in graph_states:
        if state not in st.session_state:
            st.session_state[state] = None
    
    alert_states = [
        'batt_alerts', 'epan_low_alerts', 'epan_high_alerts', 'epan_diff_alerts',
        'epan_constant_alert', 'gate_alerts', 'rain_alerts', 'ars_rain_alerts',
        'aws_zero_alerts', 'river_alerts', 'dam_alerts'
    ]
    for state in alert_states:
        if state not in st.session_state:
            if state == 'epan_constant_alert':
                st.session_state[state] = None
            else:
                st.session_state[state] = pd.DataFrame()

    # --------------------------- COMMON FILTERS ---------------------------
    with st.form("trends_filters"):
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

        # First load all stations data to get all locations
        all_locations = []
        location_station_map = {}  # To map location IDs to their stations
        
        for st_name in DATA_SOURCES.keys():
            st_df = load_station_data(st_name)
            if not st_df.empty and 'location_id' in st_df.columns and 'location_name' in st_df.columns:
                locations = st_df[['location_id', 'location_name']].drop_duplicates()
                locations = locations[locations['location_id'].notna() & locations['location_name'].notna()]
                
                for _, row in locations.iterrows():
                    location_id = str(row['location_id'])
                    location_name = str(row['location_name'])
                    location_display = f"{location_id} ({location_name})"
                    
                    if location_display not in all_locations:
                        all_locations.append(location_display)
                    
                    if location_display not in location_station_map:
                        location_station_map[location_display] = []
                    if st_name not in location_station_map[location_display]:
                        location_station_map[location_display].append(st_name)
        
        all_locations = sorted(all_locations)
        
        # Load station data for the selected type
        station_data = load_station_data(station_type)
        
        projects = ["All Projects"] + (station_data['project_name'].unique().tolist() 
                if 'project_name' in station_data.columns and not station_data.empty else [])
        selected_project = st.selectbox(
            "Project Name",
            options=projects,
            index=0,
            help="Select project to analyze"
        )
        
        # Location selection
        selected_location_display = st.selectbox(
            "Select Location",
            options=all_locations,
            help="Select location to analyze"
        )
        
        selected_location_id = None
        if selected_location_display:
            selected_location_id = selected_location_display.split(' ')[0]

        # Add the generate button to the form
        generate_clicked = st.form_submit_button("Generate Analysis", type="primary")
    
    # --------------------------- ANALYSIS EXECUTION ---------------------------
    if generate_clicked:
        if not selected_location_display:
            st.warning("Please select a location")
        else:
            # Check if selected location exists in any station
            if selected_location_display not in location_station_map:
                st.error(f"⚠ The selected location '{selected_location_display}' doesn't exist in any station.")
                st.stop()
            
            # Check if selected location exists in the selected station type
            elif station_type not in location_station_map[selected_location_display]:
                valid_stations = ", ".join(location_station_map[selected_location_display])
                st.error(f"⚠ The selected location '{selected_location_display}' belongs to {valid_stations} station(s), not {station_type}. Please select a valid station-location combination.")
                st.stop()
            
            try:
                # Clear previous state
                for state in graph_states:
                    st.session_state[state] = None
                
                for state in alert_states:
                    if state == 'epan_constant_alert':
                        st.session_state[state] = None
                    else:
                        st.session_state[state] = pd.DataFrame()
                
                # Filter data
                df = station_data.copy()
                if selected_project != "All Projects":
                    df = df[df['project_name'] == selected_project]

                filtered_df = df[df['location_id'].astype(str) == selected_location_id].copy()

                if filtered_df.empty:
                    st.warning(f"No data found for Location ID {selected_location_id} in {station_type} stations.")
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
    if selected_location_display and generate_clicked:
        # Get the actual location details from the filtered data
        location_record = None
        if not filtered_df.empty:
            location_record = filtered_df.iloc[0] if not filtered_df.empty else None
        
        if location_record is not None:
            location_details = {
                "ID": location_record.get('location_id', 'N/A'),
                "Name": location_record.get('location_name', 'N/A'),
                "Latitude": location_record.get('latitude', 'N/A'),
                "Longitude": location_record.get('longitude', 'N/A'),
                "Project": selected_project if selected_project != "All Projects" else "Multiple Projects"
            }
            
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
        else:
            # Show basic info even if no data records exist
            location_id = selected_location_display.split(' (')[0]
            location_name = selected_location_display.split(' (')[1][:-1]  # Remove closing parenthesis
            
            st.subheader("📍 Location Information")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Location ID", location_id)
                st.metric("Latitude", "N/A")
            with col2:
                st.metric("Location Name", location_name)
                st.metric("Longitude", "N/A")
            with col3:
                st.metric("Project", selected_project if selected_project != "All Projects" else "Multiple Projects")
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
                
                
                
                
                






                
                
                
def show_status_tab():
    st.subheader("Station Status Dashboard")
    
    current_date = datetime.now().date()
    
    # Initialize session state for date range and button states if not exists
    if 'start_date' not in st.session_state:
        st.session_state.start_date = None
        st.session_state.end_date = None
        st.session_state.active_date_button = 'custom'
    
    # Wrap all filters in a form
    with st.form("status_filters"):
        # Date range selection
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=None, key="status_start_date")
        with col2:
            end_date = st.date_input("End Date", value=None, key="status_end_date")

        date_range_option = st.radio(
            "Quick Date Range",
            options=["Last 7 Days", "Last 15 Days", "Last 30 Days", "Custom Range"],
            index=3,  # Default to Custom Range
            horizontal=True,
            key="status_date_range_radio"
        )

        if date_range_option == "Last 7 Days":
            st.session_state.active_date_button = '7days'
        elif date_range_option == "Last 15 Days":
            st.session_state.active_date_button = '15days'
        elif date_range_option == "Last 30 Days":
            st.session_state.active_date_button = '30days'
        else:
            st.session_state.active_date_button = 'custom'

        if start_date and end_date and start_date > end_date:
            st.error("End date must be after start date")
            st.stop()
        
        form_submitted = st.form_submit_button("Load Data", type="primary")
    
    # Update date range based on active button when form is submitted
    if form_submitted:
        if st.session_state.active_date_button == '7days':
            st.session_state.start_date = current_date - timedelta(days=6)
            st.session_state.end_date = current_date
        elif st.session_state.active_date_button == '15days':
            st.session_state.start_date = current_date - timedelta(days=14)
            st.session_state.end_date = current_date
        elif st.session_state.active_date_button == '30days':
            st.session_state.start_date = current_date - timedelta(days=29)
            st.session_state.end_date = current_date
        else:  # Custom Range
            if start_date and end_date:
                st.session_state.start_date = start_date
                st.session_state.end_date = end_date
            else:
                st.error("Please select both start and end dates for custom range")
                st.stop()
    
    # Only proceed with data loading if we have valid dates in session state
    if (form_submitted or 'status_initial_load' not in st.session_state) and st.session_state.start_date and st.session_state.end_date:
        st.session_state.status_initial_load = True
        
        # Determine the time period text for display
        if st.session_state.active_date_button == '7days':
            period_text = "for the last 7 days"
            expected_days = 7
        elif st.session_state.active_date_button == '15days':
            period_text = "for the last 15 days"
            expected_days = 15
        elif st.session_state.active_date_button == '30days':
            period_text = "for the last 30 days"
            expected_days = 30
        else:  # Custom Range
            period_text = f"from {st.session_state.start_date} to {st.session_state.end_date}"
            expected_days = (st.session_state.end_date - st.session_state.start_date).days + 1

        try:
            with st.spinner(f"Loading data {period_text}..."):
                status_df = fetch_master_tables("nhpmh_data")
                
                if status_df.empty:
                    st.warning("No data found in nhpmh_data table")
                    return
                    
                # Convert datetime columns if they exist
                datetime_cols = ['last_updated', 'data_time']
                for col in datetime_cols:
                    if col in status_df.columns:
                        status_df[col] = pd.to_datetime(status_df[col], errors='coerce')
                
                # Add section identifier and majority_date column
                if 'last_updated' in status_df.columns and 'sr_no' in status_df.columns:
                    # Create sections based on sr_no == 1
                    status_df['section'] = (status_df['sr_no'] == 1).cumsum()
                    
                    # Calculate majority date for each section
                    def get_majority_date(group):
                        # Get the most common date in the section
                        date_counts = group['last_updated'].dt.date.value_counts()
                        if not date_counts.empty:
                            return date_counts.idxmax()
                        return group['last_updated'].iloc[0].date() if not group.empty else None
                    
                    majority_dates = status_df.groupby('section').apply(get_majority_date)
                    status_df['majority_date'] = status_df['section'].map(majority_dates)
                    
                    # Filter based on selected date range
                    filtered_df = status_df[
                        (status_df['majority_date'] >= st.session_state.start_date) & 
                        (status_df['majority_date'] <= st.session_state.end_date)
                    ]
                    
                    if filtered_df.empty:
                        st.warning(f"No data available {period_text}")
                        return
                    
                    # Calculate actual number of days with data for each location
                    unique_days_per_location = filtered_df.groupby(
                        ['project_name', 'location_name', 'location_id']
                    )['majority_date'].nunique().reset_index()
                    unique_days_per_location.columns = ['project_name', 'location_name', 'location_id', 'days_with_data']
                    
                    # Calculate total data_count per location
                    total_data_per_location = filtered_df.groupby(
                        ['project_name', 'location_name', 'location_id']
                    )['data_count'].sum().reset_index()
                    
                    # Merge the two dataframes
                    summary_df = pd.merge(
                        total_data_per_location, 
                        unique_days_per_location, 
                        on=['project_name', 'location_name', 'location_id']
                    )
                    
                    # Calculate expected data count
                    summary_df['expected_data_count'] = summary_df['days_with_data'] * 24
                    summary_df['percentage'] = (summary_df['data_count'] / summary_df['expected_data_count'] * 100).round(2)
                    
                    # Get the latest record for each location
                    latest_records = filtered_df.sort_values('last_updated').groupby(
                        ['project_name', 'location_name', 'location_id']
                    ).last().reset_index()
                    
                    # Merge with summary data
                    final_df = pd.merge(
                        summary_df,
                        latest_records[['project_name', 'location_name', 'location_id', 'location_type', 'problem_statement']],
                        on=['project_name', 'location_name', 'location_id'],
                        how='left'
                    )
                    
                    # Add date range information
                    final_df['date_range'] = period_text
                    
                    # Reorder columns
                    final_df = final_df[[
                        'project_name', 'location_name', 'location_id', 'location_type', 'date_range',
                        'data_count', 'expected_data_count', 'days_with_data', 'percentage',
                        'problem_statement'
                    ]]
                    
                    # Define conditional formatting for alerts
                    def highlight_alerts(row):
                        if row['percentage'] < 90:
                            return ['background-color: #ff0000; color: white; font-weight: bold'] * len(row)
                        return [''] * len(row)
                    
                    # Display the data
                    st.dataframe(
                        final_df.style.apply(highlight_alerts, axis=1),
                        use_container_width=True,
                        height=min(400, len(final_df) * 35 + 50)
                    )
                    # Create alert dataframe
                    alert_df = final_df[final_df['percentage'] < 90]
                    alert_count = len(alert_df)
                    
                    # Show alert summary
                    if alert_count > 0:
                        st.error(f"🚨 Alert: {alert_count} stations with data reception <90% {period_text}!")
                        
                        with st.expander("🔍 View All Alert Stations", expanded=False):
                            st.dataframe(
                                alert_df[['project_name', 'location_name', 'location_id', 'percentage', 
                                         'data_count', 'expected_data_count', 'problem_statement']],
                                use_container_width=True
                            )
                            
                            cols = st.columns(3)
                            cols[0].metric("Total Alerts", alert_count)
                            cols[1].metric("Avg Reception", f"{alert_df['percentage'].mean().round(2)}%")
                            cols[2].metric("Avg Data Count", alert_df['data_count'].mean().round(2))
                        
                        st.download_button(
                            label="📥 Download Alert Data",
                            data=alert_df.to_csv(index=False).encode('utf-8'),
                            file_name=f"alert_stations_{period_text.replace(' ', '_')}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.success(f"✅ All stations have good data reception (≥90%) {period_text}")
                    
                    # Statistics section
                    st.subheader("Data Reception Statistics")
                    
                    bins = [0, 30, 40, 50, 60, 70, 80, 90, 100]
                    labels = ["<30%", "30-39%", "40-49%", "50-59%", "60-69%", "70-79%", "80-89%", "90-100%"]
                    final_df['reception_range'] = pd.cut(
                        final_df['percentage'],
                        bins=bins,
                        labels=labels,
                        include_lowest=True
                    )
                    
                    range_counts = final_df['reception_range'].value_counts().reindex(labels, fill_value=0)
                    tabs = st.tabs([f"{label} ({count})" for label, count in range_counts.items()])
                    
                    for i, tab in enumerate(tabs):
                        with tab:
                            range_df = final_df[final_df['reception_range'] == labels[i]]
                            if not range_df.empty:
                                st.dataframe(
                                    range_df[['project_name', 'location_name', 'location_id', 'percentage']],
                                    use_container_width=True
                                )
                            else:
                                st.info(f"No stations in {labels[i]} range")
                    
                    # Project summary
                    st.subheader("Project-wise Summary")
                    
                    project_stats = final_df.groupby('project_name').agg({
                        'location_id': 'nunique',
                        'percentage': 'mean',
                        'data_count': 'sum',
                        'expected_data_count': 'sum'
                    }).reset_index()
                    project_stats.columns = ['Project', 'Stations', 'Avg Reception %', 'Total Data', 'Expected Data']
                    project_stats['Avg Reception %'] = project_stats['Avg Reception %'].round(2)
                    
                    tab1, tab2 = st.tabs(["Table", "Charts"])
                    
                    with tab1:
                        st.dataframe(project_stats, use_container_width=True)
                    
                    with tab2:
                        for project in project_stats['Project']:
                            st.write(f"### {project}")
                            proj_df = final_df[final_df['project_name'] == project]
                            
                            # Fix for pie chart
                            range_counts = proj_df['reception_range'].value_counts().reset_index()
                            range_counts.columns = ['Range', 'Count']
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if not range_counts.empty:
                                    fig1 = px.pie(
                                        range_counts,
                                        names='Range',
                                        values='Count',
                                        title=f"Reception Ranges - {project}"
                                    )
                                    st.plotly_chart(fig1, use_container_width=True)
                                else:
                                    st.info(f"No data for {project}")
                            
                            with col2:
                                alert_count = len(proj_df[proj_df['percentage'] < 90])
                                status_data = pd.DataFrame({
                                    'Status': ['Good (≥90%)', 'Alert (<90%)'],
                                    'Count': [len(proj_df) - alert_count, alert_count]
                                })
                                fig2 = px.pie(
                                    status_data,
                                    names='Status',
                                    values='Count',
                                    title=f"Status - {project}",
                                    color='Status',
                                    color_discrete_map={'Good (≥90%)': 'green', 'Alert (<90%)': 'red'}
                                )
                                st.plotly_chart(fig2, use_container_width=True)
                    
                    # Download all data
                    st.download_button(
                        label="📥 Download All Data",
                        data=final_df.to_csv(index=False).encode('utf-8'),
                        file_name=f"status_data_{period_text.replace(' ', '_')}.csv",
                        mime="text/csv"
                    )

        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
        
        
        
    
    
    
    
    
        
        
        
        
        
        
def main_app():
    # Initialize tab state
    if 'current_tab' not in st.session_state:
        st.session_state.current_tab = "🌐 Overview"
    
    try:
        # Render sidebar
        render_sidebar()
        
        # Main header
        st.markdown("""
            <div class="dashboard-header">
                <h1 class="dashboard-title">HydroAnalytics Pro</h1>
                <p class="dashboard-subtitle">Advanced Water Management Intelligence Platform</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Top metrics
        render_top_metrics()
        
        # Create tabs
        tabs = st.tabs(["🌐 Overview", "📡 Categories", "📜 History", "🔍 Custom Query", "📈 Trends", "📊 Status"])
        
        # Update current tab based on selection
        with tabs[0]:
            st.session_state.current_tab = "🌐 Overview"
            show_overview_tab()
        
        with tabs[1]:
            st.session_state.current_tab = "📡 Categories"
            show_categories_tab()
        
        with tabs[2]:
            st.session_state.current_tab = "📜 History"
            show_history_tab()

        with tabs[3]:
            st.session_state.current_tab = "🔍 Custom Query"
            show_custom_tab()

        with tabs[4]:
            st.session_state.current_tab = "📈 Trends"
            show_trends_tab()
        
        with tabs[5]:
            st.session_state.current_tab = "📊 Status"
            show_status_tab()
            
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        st.stop()

# --------------------------- CUSTOM CSS ---------------------------
st.markdown(r"""
        <style>
            /* ===== GLOBAL THEME ===== */
            :root {
                --primary: #333333;    /* Vibrant blue */
                --primary-dark: #2667cc;  /* Darker blue */
                --secondary: #6c757d;     /* Cool gray */
                --accent: #20c997;        /* Teal */
                --background: #f8f9fa;    /* Light gray */
                --card-bg: #f0f0f0;       /* Pure white */
                --text-primary: #212529;  /* Dark gray */
                --text-secondary: #495057;/* Medium gray */
                --success: #28a745;      /* Green */
                --warning: #ffc107;      /* Yellow */
                --danger: #dc3545;       /* Red */
                --dark: #343a40;         /* Dark */
            }

            /* ===== BASE STYLES ===== */
            html, body, .main {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background-color: var(--background);
                color: var(--text-primary);
                line-height: 1.6;
                margin: 0;
                padding: 0;
            }

            /* ===== MAIN CONTAINER ===== */
          

            /* ===== HEADER ===== */

            .dashboard-title {
                font-weight: 800;
                color: var(--primary);
                margin: 0;
                line-height: 1.2;
                letter-spacing: -0.5px;
            }

            .dashboard-subtitle {
                color: var(--secondary);
                font-weight: 400;
                opacity: 0.9;
            }

            /* ===== METRIC CARDS ===== */
            .metric-card {
                background: var(--card-bg);
                border-radius: 12px;
                padding: 1.75rem;
                margin: 1rem 0;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
                border: 1px solid rgba(0, 0, 0, 0.03);
                transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
                position: relative;
                overflow: hidden;
                height: 100%;
            }

            .metric-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.08);
                background: rgba(160, 164, 184, 1);
                border-color: rgba(0, 123, 255, 0.5); /* Bootstrap blue with 50% opacity */
            }

            .metric-card-icon {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                width: 56px;
                height: 56px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 1.25rem;
            }

            .metric-card-icon span {
                color: white;
                font-size: 1.75rem;
            }

            .metric-card-value {
                font-size: 2.25rem;
                font-weight: 700;
                color: var(--text-primary);
                margin: 0.25rem 0;
                line-height: 1.2;
            }

            .metric-card-label {
                font-size: 0.95rem;
                color: var(--text-secondary);
                opacity: 0.9;
            }

            /* ===== SIDEBAR ===== */
            [data-testid="stSidebar"] {
                background: linear-gradient(195deg, #1e293b 0%, #0f172a 100%);
                box-shadow: 5px 0 15px rgba(0, 0, 0, 0.1);
                padding: 1.5rem;
            }

            [data-testid="stSidebar"] .stButton button {
                background-color: rgba(255, 255, 255, 0.08);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.12);
                width: 100%;
                transition: all 0.2s;
                border-radius: 8px;
                padding: 0.75rem;
                font-weight: 500;
                margin-bottom: 0.75rem;
            }

            [data-testid="stSidebar"] .stButton button:hover {
                background-color: rgba(255, 255, 255, 0.15);
                transform: translateY(-1px);
                border-color: rgba(255, 255, 255, 0.2);
            }

            /* ===== TABS ===== */
            .stTabs [role="tablist"] {
                gap: 0.5rem;
                padding: 0.5rem;
                background: rgba(203, 213, 225, 0.1);
                border-radius: 12px;
                border: none;
            }

            .stTabs [role="tab"] {
                border-radius: 10px !important;
                padding: 0.75rem 1.5rem !important;
                background: rgba(203, 213, 225, 0.1) !important;
                border: none !important;
                color: var(--text-secondary) !important;
                transition: all 0.3s ease;
                font-weight: 500;
                margin: 0 !important;
            }

            .stTabs [role="tab"][aria-selected="true"] {
                background: var(--primary) !important;
                color: white !important;
                box-shadow: 0 2px 8px rgba(58, 134, 255, 0.2);
            }

            /* ===== BUTTONS ===== */
            .stButton > button {
                background-color: var(--primary);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0.75rem 1.75rem;
                font-weight: 500;
                transition: all 0.2s;
                box-shadow: 0 2px 5px rgba(58, 134, 255, 0.15);
            }

            .stButton > button:hover {
                background-color: var(--primary-dark);
                transform: translateY(-2px);
                box-shadow: 0 5px 12px rgba(58, 134, 255, 0.25);
            }

            /* ===== DATAFRAMES & TABLES ===== */
            .stDataFrame {
                border-radius: 12px !important;
                border: 1px solid rgba(0, 0, 0, 0.05) !important;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03) !important;
            }

            /* ===== RESPONSIVE DESIGN ===== */
            @media (max-width: 768px) {
                .dashboard-title {
                    font-size: 2.25rem;
                }
                
                .dashboard-subtitle {
                    font-size: 1rem;
                }
                
                .metric-card {
                    padding: 1.5rem !important;
                }
                
                .metric-card-icon {
                    width: 48px;
                    height: 48px;
                }
            }

            /* ===== ANIMATIONS ===== */
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .stApp > div {
                animation: fadeIn 0.4s ease-out;
            }
        </style>
    """, unsafe_allow_html=True)
            
# --------------------------- APP FLOW ---------------------------
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    login_page()
    st.stop()  # This will stop execution if not authenticated

# Only runs if authenticated
main_app()