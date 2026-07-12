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
