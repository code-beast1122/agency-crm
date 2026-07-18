"""Showing people their login details, and letting the admin look them up.

Both halves exist for the same reason: this CRM has no forgot-password email,
so a password nobody can read back is a person locked out. The admin table is
the lookup of record -- direct, exact, and it never leaves the app.
"""
import pandas as pd
import streamlit as st

from utils.db import get_user_roles, reset_password, supabase, _invalidate_reads


def show_credentials(profile, note=None):
    """Show a new user's code and password together.

    Both are needed to log in, so showing one without the other just means a
    second trip to the admin.
    """
    with st.container(border=True):
        st.markdown(f"#### Login details for {profile['full_name']}")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Access Code", value=profile["login_code"], disabled=True,
                          key=f"cred_code_{profile['id']}")
        with col2:
            st.text_input("Password", value=profile.get("password") or "—", disabled=True,
                          key=f"cred_pw_{profile['id']}")
        st.caption(note or "Send these to the user. You can look them up again under Team Management → Access Codes.")


def render_access_codes():
    """The admin's lookup table: who is who, and what their login is."""
    st.markdown("### Access Codes")
    st.caption(
        "Every user's login details. Anyone who loses theirs can be given them again from here, "
        "or issued a new password with Reset."
    )

    profiles = supabase.table("profiles") \
        .select("id, full_name, role, login_code, password, session_token") \
        .order("created_at") \
        .execute().data

    if not profiles:
        st.info("No users yet.")
        return

    search = st.text_input("Search by name", placeholder="Start typing a name...")
    if search:
        needle = search.strip().lower()
        profiles = [p for p in profiles if needle in (p["full_name"] or "").lower()]
        if not profiles:
            st.info(f"Nobody matches '{search}'.")
            return

    st.dataframe(
        pd.DataFrame([{
            "Name": p["full_name"],
            "Role": p["role"],
            "Access Code": p["login_code"],
            "Password": p.get("password") or "— not set —",
            "Signed in": "yes" if p.get("session_token") else "no",
        } for p in profiles]),
        width="stretch",
        hide_index=True
    )

    st.write("---")
    st.markdown("#### Reset a Password")
    st.caption("Issues a new password and signs the user out everywhere. Their old one stops working immediately.")

    name_of = {p["id"]: f"{p['full_name']} ({p['login_code']})" for p in profiles}
    target = st.selectbox("User", options=list(name_of.keys()), format_func=lambda i: name_of[i])

    if st.button("Reset Password", key="reset_pw_btn"):
        new_password = reset_password(target)
        st.success(f"New password for {name_of[target]}: **{new_password}**")
        st.caption("Copy it now, then send it to them. It also appears in the table above after a refresh.")
