# --------------------------- IMPORTS ---------------------------
import streamlit as st
from database import fetch_master_tables, DATA_SOURCES, create_db_connection, load_station_data, fetch_data
from history import show_history_tab
from overview import show_overview_tab
from categories import show_categories_tab
from custom import show_custom_tab
from status import show_status_tab
from trends import show_trends_tab
from css import apply_custom_css
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
from psycopg2 import sql
from sqlalchemy import text
import geopandas as gpd

# --------------------------- PAGE CONFIG (MUST BE FIRST STREAMLIT COMMAND) ---------------------------

# --------------------------- REST OF YOUR CODE ---------------------------
from streamlit import config as _config
_config.set_option("theme.base", "light")         
            
# --------------------------- AUTHENTICATION ---------------------------
def login_page():
    """Render the login page and handle authentication"""
    st.markdown("""
        <style>
            div[data-testid="stVerticalBlock"] {
                min-width: 100% !important;
            }
            div[data-testid="stHorizontalBlock"] {
                min-width: 100% !important;
            }
        </style>
    """, unsafe_allow_html=True)
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
                        <div style='color: white; font-size: 1.4em'>886</div>
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
                <div class="metric-card-value">886</div>
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

                                                                                                                                                                                  
        
def main_app():
    # Apply custom CSS
    apply_custom_css()
    
    # Create columns with appropriate spacing (20% for sidebar, 80% for main content)
    sidebar_col, main_col = st.columns([0.08, 0.8], gap="large")
    
    with sidebar_col:
        render_sidebar()
        
    with main_col:
        # Main content container with proper spacing
        st.markdown("""
            <style>
                .dashboard-container {
                    padding-left: 2rem;
                    padding-right: 1rem;
                }
                .dashboard-header {
                    margin-bottom: 1.5rem;
                }
            </style>
            <div class="dashboard-container">
        """, unsafe_allow_html=True)
        
        # Dashboard header
        st.markdown("""
            <div class="dashboard-header">
                <h1 class="dashboard-title">HydroAnalytics Pro</h1>
                <p class="dashboard-subtitle">Advanced Water Management Intelligence Platform</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Top metrics section
        render_top_metrics()
        
        # Create tabs with consistent spacing
        tabs = st.tabs(["🌐 Overview", "📡 Categories", "📜 History", "🔍 Custom Query", "📈 Trends", "📊 Status"])
        
        # Tab content sections
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
            
        st.markdown("</div>", unsafe_allow_html=True)  # Close dashboard-container

    # Add JavaScript to maintain layout on resize
    st.components.v1.html("""
    <script>
        function maintainLayout() {
            const sidebar = document.querySelector('[data-testid="stSidebar"]');
            const mainContent = document.querySelector('.dashboard-container');
            if (sidebar && mainContent) {
                const sidebarWidth = sidebar.offsetWidth;
                mainContent.style.marginLeft = ${sidebarWidth + 32}px;
            }
        }
        window.addEventListener('resize', maintainLayout);
        document.addEventListener('DOMContentLoaded', maintainLayout);
    </script>
    """)



# --------------------------- APP FLOW ---------------------------
if __name__ == "__main__":
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        login_page()
        st.stop()  # This will stop execution if not authenticated

    # Only runs if authenticated
    main_app()
    
    # Add a small JavaScript to ensure proper rendering
    st.components.v1.html("""
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            window.dispatchEvent(new Event('resize'));
        }, 100);
    });
    </script>
    """, height=0)
    
    st.components.v1.html("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
""", height=0)