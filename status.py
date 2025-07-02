import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, px, DATA_SOURCES, re, go, io, fetch_data
from css import apply_custom_css


import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, px, DATA_SOURCES, re, go, io, fetch_data
from css import apply_custom_css


import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import fetch_master_tables, load_station_data, px, DATA_SOURCES, re, go, io, fetch_data
from css import apply_custom_css


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
                status_df = fetch_data("nhpmh_data")
                
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
                    
                    # MODIFIED: Get the maximum data_count per location per day
                    daily_max_data = filtered_df.groupby(
                        ['project_name', 'location_name', 'location_id', 'majority_date']
                    )['data_count'].max().reset_index()
                    
                    # Calculate actual number of days with data for each location
                    unique_days_per_location = daily_max_data.groupby(
                        ['project_name', 'location_name', 'location_id']
                    )['majority_date'].nunique().reset_index()
                    unique_days_per_location.columns = ['project_name', 'location_name', 'location_id', 'days_with_data']
                    
                    # Calculate total data_count per location (using the max values we just calculated)
                    total_data_per_location = daily_max_data.groupby(
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
                    
                    # Create bins and labels for percentage ranges
                    bins = [0, 30, 40, 50, 60, 70, 80, 90, 100]
                    labels = ["<30%", "30-39%", "40-49%", "50-59%", "60-69%", "70-79%", "80-89%", "90-100%"]
                    
                    # Add reception_range column to final_df
                    final_df['reception_range'] = pd.cut(
                        final_df['percentage'],
                        bins=bins,
                        labels=labels,
                        include_lowest=True
                    )
                    
                    # Create pivot table with counts for each project and range
                    project_range_counts = final_df.groupby(['project_name', 'reception_range']).size().unstack(fill_value=0)
                    
                    # Ensure all ranges are present (even if count is 0)
                    for label in labels:
                        if label not in project_range_counts.columns:
                            project_range_counts[label] = 0
                    
                    # Reorder columns to match the desired order
                    project_range_counts = project_range_counts[labels]
                    
                    # Reset index to make project_name a column
                    project_range_counts = project_range_counts.reset_index()
                    
                    # Add total stations column
                    project_range_counts['Total Stations'] = project_range_counts[labels].sum(axis=1)
                    
                    # Create tabs for table and charts
                    tab1, tab2 = st.tabs(["Table", "Charts"])
                    
                    with tab1:
                        # Display the table
                        st.dataframe(
                            project_range_counts,
                            use_container_width=True,
                            hide_index=True
                        )
                    
                    with tab2:
                        for project in project_range_counts['project_name']:
                            st.write(f"### {project}")
                            proj_df = final_df[final_df['project_name'] == project]
                            
                            # Fix for pie chart
                            range_counts = proj_df['reception_range'].value_counts().reset_index()
                            range_counts.columns = ['Range', 'Count']
                            
                            # Sort the ranges in descending order (90-100% to <30%)
                            ordered_labels = ["90-100%", "80-89%", "70-79%", "60-69%", "50-59%", "40-49%", "30-39%", "<30%"]
                            range_counts['Range'] = pd.Categorical(
                                range_counts['Range'],
                                categories=ordered_labels,
                                ordered=True
                            )
                            range_counts = range_counts.sort_values('Range')
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if not range_counts.empty:
                                    fig1 = px.pie(
                                        range_counts,
                                        names='Range',
                                        values='Count',
                                        title=f"Reception Ranges - {project}",
                                        category_orders={"Range": ordered_labels}
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