import streamlit as st
from utils.db import get_profile_by_code

# We will import views dynamically or ensure they are present
import views.client_portal as client_portal
import views.manager_dashboard as manager_dashboard
import views.employee_dashboard as employee_dashboard

st.set_page_config(page_title="Agency CRM", page_icon="🏢", layout="wide")


def login():
    # Inject CSS strictly for the login page
    st.markdown("""
    <style>
        /* Center the login container */
        .block-container {
            max-width: 100%;
            padding-top: 5rem;
        }
        
        /* The Card */
        [data-testid="stForm"] {
            background-color: #1a1c23;
            border: none;
            border-radius: 30px;
            padding: 40px;
            box-shadow: 0 20px 40px -10px rgba(0,0,0,0.5), 0 0 40px rgba(14, 165, 233, 0.15);
        }
        
        /* Input Field Styling */
        [data-testid="stTextInput"] input {
            border-radius: 9999px;
            background-color: #262932;
            border: 1px solid #333842;
            color: white;
            padding: 15px 20px;
            font-size: 1rem;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
        }
        [data-testid="stTextInput"] input:focus {
            border-color: #0ea5e9;
            box-shadow: 0 0 10px rgba(14, 165, 233, 0.3), inset 0 2px 4px rgba(0,0,0,0.1);
        }
        
        /* Button Styling */
        [data-testid="stFormSubmitButton"] button {
            border-radius: 9999px;
            background: linear-gradient(135deg, #0284c7 0%, #0ea5e9 100%);
            border: none;
            color: white !important;
            font-weight: 700;
            font-size: 1.1rem;
            padding: 10px 0;
            box-shadow: 0 10px 20px -5px rgba(14, 165, 233, 0.5);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        [data-testid="stFormSubmitButton"] button:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 25px -5px rgba(14, 165, 233, 0.6);
        }
        [data-testid="stFormSubmitButton"] button p {
            color: white !important;
        }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form", clear_on_submit=False):
            st.markdown("<h1 style='text-align: center; color: #0ea5e9; font-size: 2.8rem; font-weight: 800; margin-bottom: 0;'>Sign In</h1>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: #94a3b8; margin-bottom: 2rem;'>Enter your Access Code</p>", unsafe_allow_html=True)
            
            access_code = st.text_input("Access Code", type="password", label_visibility="collapsed", placeholder="Access Code")
            
            # Spacing
            st.write("")
            st.write("")
            
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            
            # Dummy links
            st.markdown("<div style='text-align: center; margin-top: 1rem;'><a href='#' style='color: #0ea5e9; font-size: 0.85rem; text-decoration: none;'>Forgot Password?</a></div>", unsafe_allow_html=True)
            
            if submitted:
                if access_code:
                    profile = get_profile_by_code(access_code)
                    if profile:
                        st.session_state["user"] = profile
                        st.rerun()
                    else:
                        st.error("Invalid Access Code. Please try again.")
                else:
                    st.warning("Please enter an Access Code.")

def main():
    if "user" not in st.session_state:
        login()
    else:
        user = st.session_state["user"]
        role = user.get("role")
        
        # Inject custom CSS for a beautiful sidebar
        st.markdown("""
        <style>
            /* Make the sidebar background distinct and match dark mode */
            [data-testid="stSidebar"] {
                background-color: #1f1f1f;
                border-right: 1px solid #333333;
            }
            
            /* Profile Card Container */
            .sidebar-profile {
                text-align: center;
                padding-bottom: 1.5rem;
                margin-bottom: 1.5rem;
                border-bottom: 1px solid #333333;
            }
            
            /* Circular Avatar */
            .sidebar-profile img {
                width: 90px;
                height: 90px;
                border-radius: 50%;
                margin-bottom: 1rem;
                border: 3px solid #333333;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.18);
            }
            
            /* User Name */
            .sidebar-name {
                font-family: 'Inter', sans-serif;
                font-size: 1.25rem;
                font-weight: 700;
                color: #ffffff;
                margin-bottom: 0.25rem;
            }
            
            /* User Role Badge */
            .sidebar-role {
                font-family: 'Inter', sans-serif;
                font-size: 0.75rem;
                font-weight: 700;
                color: #60a5fa;
                background-color: rgba(59, 130, 246, 0.15);
                border: 1px solid rgba(59, 130, 246, 0.3);
                padding: 0.25rem 0.75rem;
                border-radius: 9999px;
                display: inline-block;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                box-shadow: 0 0 10px rgba(59, 130, 246, 0.1);
            }
            
            /* Adjust the main content to breathe a bit more */
            .block-container {
                padding-top: 2rem;
            }
        </style>
        """, unsafe_allow_html=True)
        
        # Build the avatar URL (fallback to initials via ui-avatars.com)
        safe_name = user.get('full_name', 'User').replace(' ', '+')
        avatar_url = f"https://ui-avatars.com/api/?name={safe_name}&background=eff6ff&color=3b82f6&size=200&bold=true"
        
        # Render the profile card
        st.sidebar.markdown(f"""
        <div class="sidebar-profile">
            <img src="{avatar_url}" alt="Profile Picture">
            <div class="sidebar-name">{user.get('full_name')}</div>
            <div class="sidebar-role">{role}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # Spacing before logout
        st.sidebar.write("")
        st.sidebar.write("")
        
        # A full-width, clean logout button
        if st.sidebar.button("Logout", use_container_width=True, type="primary"):
            del st.session_state["user"]
            st.rerun()
            
        if role == "client":
            client_portal.render(user)
        elif role in ["manager", "hr", "supervisor"]:
            manager_dashboard.render(user)
        elif role == "employee":
            employee_dashboard.render(user)
        else:
            st.error(f"Unknown role: {role}")

if __name__ == "__main__":
    main()
