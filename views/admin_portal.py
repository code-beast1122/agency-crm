import streamlit as st
import pandas as pd
from utils.db import (
    supabase,
    create_profile,
    get_all_projects,
    get_all_clients,
    create_client_record,
    create_project,
    create_proposal,
    get_role_counts,
    get_user_roles,
    sync_profile_role,
    provision_calendar,
    ROLE_TABLES_WITH_CALENDARS,
    _invalidate_reads
)
import os
from groq import Groq

def render(user):
    st.title("👑 Admin Portal")
    st.markdown("Full System Control and Analytics.")
    
    active_tab = st.radio("Admin Navigation", [
        "📊 Overview", 
        "👥 Team Management", 
        "📁 Projects", 
        "📢 Announcements", 
        "🤖 AI Assistant",
        "📝 Weekly Reports"
    ], horizontal=True, label_visibility="collapsed")
    
    st.divider()
    
    if active_tab == "📊 Overview":
        st.subheader("System KPIs")
        render_overview()
        
    elif active_tab == "👥 Team Management":
        st.subheader("Manage Departments & Users")
        render_user_management()
        
    elif active_tab == "📁 Projects":
        st.subheader("Project Progress")
        render_projects()
        
    elif active_tab == "📢 Announcements":
        st.subheader("Global Announcements")
        render_announcements(user)
        
    elif active_tab == "🤖 AI Assistant":
        st.subheader("AI Data Analyst")
        render_ai_assistant()
        
    elif active_tab == "📝 Weekly Reports":
        st.subheader("Coordinator Weekly Reports")
        render_weekly_reports()

def render_overview():
    # One cached call, six counts fired concurrently.
    counts = get_role_counts()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Admins", counts["admins"])
    col2.metric("Coordinators", counts["coordinators"])
    col3.metric("HODs", counts["hods"])
    col4.metric("Employees", counts["employees"])
    col5.metric("Projects", counts["projects"])
    col6.metric("Clients", counts["clients"])
    
def render_user_management():
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### 🏢 Add Department")
        with st.form("add_dept_form"):
            dept_name = st.text_input("Department Name")
            if st.form_submit_button("Create Department"):
                if dept_name:
                    res = supabase.table("departments").insert({"name": dept_name}).execute()
                    if res.data:
                        _invalidate_reads()
                        st.success(f"Department '{dept_name}' created!")
                        st.rerun()
                else:
                    st.error("Please enter a name.")
                    
        st.markdown("### 📋 Existing Departments")
        depts = supabase.table("departments").select("*").execute().data
        if depts:
            for d in depts:
                st.markdown(f"- **{d['name']}**")
        else:
            st.info("No departments yet.")
            
        st.markdown("---")
        st.markdown("### 👤 Create New User Profile")
        st.info("Create a raw profile first, then assign it a role on the right.")
        with st.form("create_new_profile_form"):
            new_user_name = st.text_input("Full Name")
            if st.form_submit_button("Create Profile"):
                if new_user_name:
                    # role is NOT NULL, so a raw profile needs something in it.
                    # Assigning a role below overwrites this placeholder.
                    profile = create_profile(new_user_name, "employee")
                    st.success(f"Profile created! Login Code: {profile['login_code']}")
                    st.rerun()
                else:
                    st.error("Please enter a name.")
            
    with col2:
        st.markdown("### 👥 Role Assignment")
        
        profiles = supabase.table("profiles").select("id, full_name").execute().data
        depts = supabase.table("departments").select("id, name").execute().data
        
        if profiles:
            user_map = {p['id']: f"{p['full_name']}" for p in profiles}
            selected_profile_id = st.selectbox("Select User", options=list(user_map.keys()), format_func=lambda x: user_map[x])
            
            selected_role = st.selectbox("Select Role to Assign", ["admin", "coordinator", "hod", "employee", "client"])
            
            selected_dept_id = None
            if selected_role in ["hod", "employee"]:
                if depts:
                    dept_map = {d['id']: d['name'] for d in depts}
                    selected_dept_id = st.selectbox("Select Department", options=list(dept_map.keys()), format_func=lambda x: dept_map[x])
                else:
                    st.warning("Please create a department first.")
            
            # Their Google email: this is what the calendar invite is sent to.
            user_email = st.text_input("Google Email Address (Required for Calendar Invites)")
            st.caption("They get their own deadline calendar and an invite email — they only see their own tasks.")

            if st.button("Assign Role"):
                table_name = selected_role + "s"
                data = {"profile_id": selected_profile_id}
                if user_email:
                    data["email"] = user_email
                if selected_role in ["hod", "employee"]:
                    data["department_id"] = selected_dept_id

                try:
                    res = supabase.table(table_name).insert(data).execute()
                    if res.data:
                        _invalidate_reads()
                        sync_profile_role(selected_profile_id)
                        st.success(f"Assigned {selected_role.capitalize()} role to {user_map[selected_profile_id]}")

                        if user_email and table_name in ROLE_TABLES_WITH_CALENDARS:
                            cal = provision_calendar(
                                selected_profile_id, user_map[selected_profile_id],
                                user_email, table_name
                            )
                            if cal.get("status") == "success":
                                st.success(f"📅 {cal['message']} They must accept it to get reminders.")
                            else:
                                st.warning(f"Role assigned, but the calendar invite failed: {cal.get('message')}")
                        elif not user_email:
                            st.warning("No email given, so no calendar invite was sent. "
                                       "They will not get deadline reminders.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error assigning role (They might already have it): {str(e)}")

            st.divider()
            st.markdown(f"#### Active Roles for {user_map[selected_profile_id]}")

            # get_user_roles fires these concurrently and caches them, instead of
            # five serial round-trips every time this panel redraws.
            active_roles = get_user_roles(selected_profile_id)
            roles_found = bool(active_roles)

            for r_name in active_roles:
                    t_name = r_name + "s"
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.info(f"**{r_name.capitalize()}**")
                    with col_b:
                        if st.button("Revoke", key=f"revoke_{r_name}_{selected_profile_id}"):
                            try:
                                supabase.table(t_name).delete().eq("profile_id", selected_profile_id).execute()
                                _invalidate_reads()
                                sync_profile_role(selected_profile_id)
                                st.success(f"Revoked {r_name.capitalize()} role!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Cannot revoke {r_name} role. They might have data (like tasks or logs) tied to them. Error: {str(e)}")
            
            if not roles_found:
                st.caption("No roles assigned yet.")
        else:
            st.info("No users found in the system.")
    
def render_projects():
    st.markdown("### 🚀 Client Onboarding & Projects")
    
    tab_new, tab_list = st.tabs(["Onboard New Client", "Active Projects"])
    
    with tab_new:
        with st.form("admin_onboard_client"):
            col1, col2 = st.columns(2)
            with col1:
                client_name = st.text_input("Client Representative Name")
                company_name = st.text_input("Company Name")
            with col2:
                project_title = st.text_input("Initial Project Title")
                proposal_file = st.file_uploader("Upload Initial Proposal (PDF)", type=["pdf"])
                
            if st.form_submit_button("Create Client & Project"):
                if not (client_name and company_name and project_title):
                    st.error("Please fill in all text fields.")
                else:
                    try:
                        profile = create_profile(client_name, "client")
                        client = create_client_record(profile["id"], company_name)
                        # The role tables are the source of truth for the label.
                        sync_profile_role(profile["id"])
                        project = create_project(client["id"], project_title)
                        
                        if proposal_file:
                            file_ext = proposal_file.name.split('.')[-1]
                            file_name = f"proposal_{project['id']}.{file_ext}"
                            supabase.storage.from_("documents").upload(
                                file_name,
                                proposal_file.getvalue(),
                                {"content-type": proposal_file.type, "upsert": "true"}
                            )
                            public_url = supabase.storage.from_("documents").get_public_url(file_name)
                            create_proposal(project["id"], public_url)
                            
                        st.success(f"Successfully onboarded {company_name}! Their access code is: {profile['login_code']}")
                    except Exception as e:
                        st.error(f"Error during onboarding: {str(e)}")
                        
    with tab_list:
        projects = get_all_projects()
        if projects:
            for p in projects:
                with st.expander(f"**{p['title']}** - {p['clients']['company_name']} ({p['status'].upper()})"):
                    st.write(f"**Created:** {p['created_at'][:10]}")
        else:
            st.info("No active projects found.")
    
def render_announcements(user):
    st.markdown("### 📢 Post a Global Announcement")
    st.info("Announcements posted here will appear on the dashboards of all Coordinators, HODs, and Employees.")
    
    with st.form("post_announcement_form"):
        message = st.text_area("Announcement Message", height=100)
        if st.form_submit_button("Post Announcement"):
            if message:
                admin_rec = supabase.table("admins").select("id").eq("profile_id", user['id']).execute().data
                if admin_rec:
                    admin_id = admin_rec[0]['id']
                    res = supabase.table("announcements").insert({
                        "message": message,
                        "created_by": admin_id,
                        "is_active": True
                    }).execute()
                    if res.data:
                        st.success("Announcement posted successfully!")
                        st.rerun()
                else:
                    st.error("You must be assigned to the admins table to post announcements.")
            else:
                st.error("Please enter a message.")
                
    st.markdown("### 📋 Active Announcements")
    announcements = supabase.table("announcements").select("*, admins(profiles(full_name))").eq("is_active", True).order("created_at", desc=True).execute().data
    
    if announcements:
        for ann in announcements:
            with st.container():
                st.markdown(f"**{ann['message']}**")
                # Handle nested join safely
                creator = "Admin"
                if ann.get('admins') and ann['admins'].get('profiles'):
                    creator = ann['admins']['profiles'].get('full_name', 'Admin')
                
                st.caption(f"Posted by {creator} on {ann['created_at'][:10]}")
                if st.button("Deactivate", key=f"deactivate_{ann['id']}"):
                    supabase.table("announcements").update({"is_active": False}).eq("id", ann['id']).execute()
                    st.rerun()
                st.divider()
    else:
        st.info("No active announcements.")

def render_weekly_reports():
    reports = supabase.table("weekly_reports").select("*, coordinators(profiles(full_name))").order("created_at", desc=True).execute().data
    
    if not reports:
        st.info("No weekly reports submitted yet.")
        return
        
    for rep in reports:
        coord_name = "Unknown Coordinator"
        if rep.get("coordinators") and rep["coordinators"].get("profiles"):
            coord_name = rep["coordinators"]["profiles"]["full_name"]
            
        date_str = rep["created_at"][:10]
        
        with st.expander(f"Report from {coord_name} ({date_str})"):
            st.markdown(f"**🎯 Goals Hit This Week:**\n{rep['goals_hit']}")
            st.divider()
            st.markdown(f"**🚧 Blockers & Issues:**\n{rep['blockers']}")
            st.divider()
            st.markdown(f"**📝 Additional Notes:**\n{rep['notes']}")
    
def render_ai_assistant():
    st.markdown("### 🤖 CRM Data Analyst")
    st.info("Ask me anything about the agency's progress, departments, or projects.")
    
    # Initialize chat history
    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = [
            {"role": "assistant", "content": "Hello! I am your AI Data Analyst powered by Groq. How can I help you today?"}
        ]
        
    # Display chat messages
    for msg in st.session_state.ai_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    # Chat input
    if prompt := st.chat_input("E.g., How many active projects do we have?"):
        # Display user message
        st.session_state.ai_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        # Get Groq API Key
        groq_api_key = os.environ.get("GROQ_API_KEY")
        
        with st.chat_message("assistant"):
            if not groq_api_key:
                st.error("Missing GROQ_API_KEY. Please add it to your .env file.")
            else:
                try:
                    client = Groq(api_key=groq_api_key)
                    
                    # Fetch database context for the model (Llama 3.1 8B has a 128k context window).
                    # Columns are listed explicitly, never "*": this payload leaves our
                    # infrastructure, and profiles.login_code IS the user's password.
                    try:
                        import json
                        db_dump = {
                            "profiles": supabase.table("profiles").select("full_name, role, login_code, created_at").execute().data,
                            "departments": supabase.table("departments").select("name").execute().data,
                            "projects": supabase.table("projects").select("id, client_id, title, status, created_at").execute().data,
                            "tasks": supabase.table("tasks").select("id, project_id, assigned_to, title, description, task_source, status, estimated_hours, actual_hours, task_type, deadline, created_at").execute().data,
                            "clients": supabase.table("clients").select("id, profile_id, company_name, created_at").execute().data,
                            "time_logs": supabase.table("time_logs").select("id, task_id, employee_id, start_time, end_time").execute().data,
                            "roles_mapping": {
                                "admins": supabase.table("admins").select("id, profiles(full_name)").execute().data,
                                "coordinators": supabase.table("coordinators").select("id, profiles(full_name)").execute().data,
                                "hods": supabase.table("hods").select("id, departments(name), profiles(full_name)").execute().data,
                                "employees": supabase.table("employees").select("id, designation, departments(name), profiles(full_name)").execute().data
                            }
                        }
                        
                        stats_str = "FULL DATABASE CONTEXT (JSON):\n" + json.dumps(db_dump, default=str)
                    except Exception:
                        stats_str = "Could not load current DB stats."
                        
                    sys_prompt = f"You are a helpful CRM Data Analyst for an agency. You analyze departments, projects, and employees. " \
                                 f"Do NOT invent or hallucinate names. ONLY use the names provided in the context. Also dont include information like id. instead of mentioning id mention name " \
                                 f"Use the following real-time data to answer the user's questions:\n{stats_str}"
                    
                    messages = [{"role": "system", "content": sys_prompt}]
                    messages.extend(st.session_state.ai_messages)
                    
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=messages,
                        temperature=0.3,
                        max_tokens=1024
                    )
                    
                    answer = response.choices[0].message.content
                    st.markdown(answer)
                    st.session_state.ai_messages.append({"role": "assistant", "content": answer})
                    
                except Exception as e:
                    st.error(f"Groq API Error: {str(e)}")
