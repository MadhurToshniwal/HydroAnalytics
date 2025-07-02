import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data
from css import apply_custom_css

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
