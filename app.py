import streamlit as st
from utils.db import get_profile_by_code

# We will import views dynamically or ensure they are present
import views.client_portal as client_portal
import views.manager_dashboard as manager_dashboard
import views.employee_dashboard as employee_dashboard

st.set_page_config(page_title="Agency CRM", page_icon="🏢", layout="wide")

hide_st_style = """
<style>
    /* 1. Hide the entire Streamlit header */
    [data-testid="stHeader"] {display: none !important;}
    header {display: none !important;}
    
    /* 2. Hide the Streamlit footer */
    footer {display: none !important;}
    
    /* 3. Hide the Main Menu */
    #MainMenu {display: none !important;}
    [data-testid="stToolbar"] {display: none !important;}
    
    /* 4. Hide the "Hosted with Streamlit" Badge */
    a[href^="https://streamlit.io/cloud"] {display: none !important;}
    .viewerBadge_container__1QSob {display: none !important;}
    
    /* 5. Hide the Deploy Button specifically */
    [data-testid="stAppDeployButton"] {display: none !important;}
    .stAppDeployButton {display: none !important;}
    
    /* 6. Catch-all for any other Streamlit floating buttons in the bottom right */
    [data-testid="manage-app-button"] {display: none !important;}
    
    /* 7. Hide status widgets (running/stopping) if they appear */
    [data-testid="stStatusWidget"] {display: none !important;}
</style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

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
        
        st.sidebar.title(f"Welcome, {user.get('full_name')}")
        st.sidebar.write(f"Role: **{role.capitalize()}**")
        
        if st.sidebar.button("Logout"):
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
