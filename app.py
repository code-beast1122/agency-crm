import streamlit as st
import re
from utils.db import (
    authenticate,
    end_session,
    get_profile_by_session_token,
    get_user_roles,
    start_session,
)
from utils.theme import inject_theme
from streamlit_cookies_controller import CookieController
import views.coordinator_portal as coordinator_portal
import views.employee_dashboard as employee_dashboard
import views.client_portal as client_portal
import views.admin_portal as admin_portal
import views.hod_portal as hod_portal

controller = CookieController()
def handle_login():
    access_code = st.session_state.get("access_code_input")
    password = st.session_state.get("password_input")

    if not access_code or not password:
        st.session_state["login_error"] = "Enter both your access code and password."
        return

    if not re.match(r"^cs-\d{6}-\d{3}$", access_code):
        st.session_state["login_error"] = "Invalid Format. Must be cs-XXXXXX-YYY"
        return

    profile = authenticate(access_code, password)
    if not profile:
        # One message for both failures on purpose: saying which half was wrong
        # tells someone walking the thousand-value code space when they have
        # found a real account.
        st.session_state["login_error"] = "Invalid access code or password."
        return

    st.session_state["user"] = profile
    # The cookie carries this token, never the credentials.
    st.session_state["just_logged_in"] = start_session(profile["id"])

def handle_logout():
    if "user" in st.session_state:
        end_session(st.session_state["user"].get("id"))
        del st.session_state["user"]
    st.session_state["just_logged_out"] = True

st.set_page_config(page_title="ClixoSoft CRM", page_icon="🏢", layout="wide")
inject_theme()


def login():
    # Only what is specific to the login screen: the shared stylesheet already
    # dresses the form, its inputs and the submit button.
    st.markdown("""
    <style>
        /* No sidebar on the login page.
           Logging out reruns the script and renders nothing into the sidebar,
           but Streamlit keeps the container mounted for the life of the browser
           session -- the rerun empties its contents without unmounting the
           shell, so an empty panel sat next to the login form until a full
           refresh rebuilt the page. Hiding it here fixes the logout path and
           the first-visit path with one rule, since neither should ever show
           one. */
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsed"] { display: none !important; }

        .block-container { padding-top: 6rem; }
        [data-testid="stForm"] {
            margin: 0 auto;
            max-width: 430px;
            padding: 2.5rem;
            box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.6),
                        0 0 60px -20px rgba(14, 165, 233, 0.25);
        }
        .login-brand {
            text-align: center;
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.22em;
            color: #64748b; text-transform: uppercase;
            margin-bottom: 0.5rem;
        }
        .login-title {
            text-align: center; font-size: 2.2rem; font-weight: 800;
            color: #e6edf6; margin: 0;
        }
        .login-sub {
            text-align: center; color: #94a3b8;
            font-size: 0.9rem; margin-bottom: 1.75rem;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        st.markdown("<div class='login-brand'>ClixoSoft CRM</div>", unsafe_allow_html=True)
        st.markdown("<h1 class='login-title'>Sign In</h1>", unsafe_allow_html=True)
        st.markdown("<p class='login-sub'>Enter your access code and password</p>", unsafe_allow_html=True)

        # The code is a username, not a secret -- showing it lets people check
        # what they typed. The password is what is actually being protected.
        st.text_input("Access Code", key="access_code_input", label_visibility="collapsed", placeholder="Access Code (cs-XXXXXX-YYY)")
        st.text_input("Password", type="password", key="password_input", label_visibility="collapsed", placeholder="Password")

        # Spacing
        st.write("")
        st.write("")
        
        st.form_submit_button("Sign In", width="stretch", on_click=handle_login)
        
        if "login_error" in st.session_state:
            st.error(st.session_state["login_error"])
            del st.session_state["login_error"]

def forget_login_cookie():
    """Drop the saved login cookie, tolerating one the controller never saw.

    CookieController.remove() tells the browser to delete the cookie and THEN
    pops it from its own dict, unguarded. That dict only knows about cookies the
    controller itself set this session -- but an auto-login reads the code
    straight from st.context.cookies, so on that path the name was never
    registered and logging out raised KeyError. The browser-side removal has
    already been dispatched by the time it throws, so swallowing this is safe.
    """
    try:
        controller.remove("login_code")
    except KeyError:
        pass


def main():
    if "user" not in st.session_state and not st.session_state.get("just_logged_out"):
        saved_token = st.context.cookies.get("login_code")
        if saved_token:
            profile = get_profile_by_session_token(saved_token)
            if profile:
                st.session_state["user"] = profile

    if "user" not in st.session_state:
        if st.session_state.get("just_logged_out"):
            forget_login_cookie()
            del st.session_state["just_logged_out"]
        login()
    else:
        if st.session_state.get("just_logged_in"):
            code = st.session_state["just_logged_in"]
            controller.set("login_code", code, max_age=86400 * 30)
            del st.session_state["just_logged_in"]
            
        # Main application logic for logged in user
        user = st.session_state["user"]
        
        roles = get_user_roles(user["id"])
        if not roles:
            # Fallback to legacy enum role if not migrated yet
            roles = [user.get("role")]
            
        # Role selection if multiple roles
        if len(roles) > 1:
            st.sidebar.markdown("### Switch Portal")
            active_role = st.sidebar.radio("Select your role dashboard:", roles, format_func=lambda x: str(x).capitalize())
        else:
            active_role = roles[0] if roles else "Unknown"
            
        role_display = str(active_role).capitalize() if active_role else "Unknown"
        
        # The sidebar profile card is styled in utils/theme.py alongside every
        # other surface, so the whole app moves together when a colour changes.

        # Build the avatar URL (fallback to initials via ui-avatars.com)
        safe_name = user.get('full_name', 'User').replace(' ', '+')
        avatar_url = f"https://ui-avatars.com/api/?name={safe_name}&background=0ea5e9&color=0f1117&size=200&bold=true"
        
        # Render the profile card
        st.sidebar.markdown(f"""
        <div class="sidebar-profile">
            <img src="{avatar_url}" alt="Profile Picture">
            <div class="sidebar-name">{user.get('full_name')}</div>
            <div class="sidebar-role">{role_display}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # Spacing before logout
        st.sidebar.write("")
        st.sidebar.write("")
        
        # A full-width, clean logout button
        st.sidebar.button("Logout", width="stretch", type="primary", on_click=handle_logout)
            
        if active_role == "client":
            client_portal.render(user)
        elif active_role in ["coordinator", "manager", "hr", "supervisor"]:
            coordinator_portal.render(user)
        elif active_role == "employee":
            employee_dashboard.render(user)
        elif active_role == "admin":
            admin_portal.render(user)
        elif active_role == "hod":
            hod_portal.render(user)
        else:
            st.error(f"Unknown role: {active_role}")

if __name__ == "__main__":
    main()
