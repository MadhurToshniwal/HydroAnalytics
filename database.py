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
from css import apply_custom_css


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
        password = "mariobot@123"
        connection_string = f"mysql+mysqlconnector://Mariobot:mariobot%40123@103.224.245.53:3307/may_2025_data"
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

# @st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_data(table_name, start_date=None, end_date=None, date_column=None):
    """Fetch data from MySQL database using SQLAlchemy with caching"""
    engine = create_db_connection()
    if engine is None:
        return pd.DataFrame()
    
    try:
        query = f"SELECT * FROM {table_name}"
        if start_date and end_date and date_column:
            query += f" WHERE {date_column} BETWEEN '{start_date}' AND '{end_date}'"
        
        df = pd.read_sql(query, engine)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Error as e:
        st.error(f"Error fetching data from {table_name}: {e}")
        return pd.DataFrame()
    finally:
        if engine:
            engine.dispose()
