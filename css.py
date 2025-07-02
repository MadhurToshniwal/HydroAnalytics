import streamlit as st

def apply_custom_css():
    # --------------------------- CUSTOM CSS ---------------------------
    st.markdown("""
        <style>
            /* Add this new rule */
            .main .block-container {
                padding-left: 2rem !important;
                padding-right: 2rem !important;
                margin-left: 18rem !important;  /* Adjust this value based on your sidebar width */
            }
            
            /* Ensure sidebar has proper width */
            [data-testid="stSidebar"] {
                width: 16rem !important;
            }
            /* Force full width on all containers */
            .stApp, .main, .block-container, .stAppViewContainer {
                max-width: 100% !important;
                padding: 0 !important;
                margin: 0 !important;
            }
            
            /* Fix for login page */
            .stApp > div:first-child {
                width: 100% !important;
                max-width: 100% !important;
            }
            
            /* Ensure main content stays full width */
            .main .block-container {
                padding: 2rem 1rem 10rem;
                max-width: 100% !important;
            }
            
            /* Prevent any container from shrinking */
            div[data-testid="stHorizontalBlock"] {
                min-width: 100% !important;
            }
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

            /* ===== FIXES FOR RELOAD ISSUE ===== */
            html, body, #root, .stApp {
                width: 100% !important;
                min-width: 100% !important;
                overflow-x: hidden !important;
                padding: 0 !important;
                margin: 0 !important;
            }
            
            
            
            div[data-testid="stAppViewContainer"] {
                padding: 0 !important;
                margin: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
            }

            .main .block-container {
                padding: 2rem 1rem 10rem !important;
                max-width: 100% !important;
                width: 100% !important;
            }

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
                border-color: rgba(0, 123, 255, 0.5);
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
            /* Add this to your CSS */
            .stApp {
                min-width: 100% !important;
                padding: 0 !important;
                margin: 0 !important;
            }

            .stApp > div {
                max-width: 100% !important;
                padding: 0 !important;
            }

            .main .block-container {
                max-width: 100% !important;
                padding: 2rem 1rem 10rem !important;
            }

            .stApp > div {
                animation: fadeIn 0.4s ease-out;
            }

            /* Fix for main content area */
            .main .block-container {
                padding: 2rem 1rem 10rem;
                max-width: 100%;
            }

            /* Ensure proper width */
            .stApp {
                min-width: 100%;
            }
        </style>
    """, unsafe_allow_html=True)