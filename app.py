import streamlit as st
from utils.db import get_profile_by_code

# We will import views dynamically or ensure they are present
import views.client_portal as client_portal
import views.manager_dashboard as manager_dashboard
import views.employee_dashboard as employee_dashboard

st.set_page_config(page_title="Agency CRM", page_icon="🏢", layout="wide")


def login():
    st.title("Agency CRM Login")
    st.write("Please enter your Access Code to continue.")
    
    with st.form("login_form"):
        access_code = st.text_input("Access Code", type="password")
        submitted = st.form_submit_button("Login")
        
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
