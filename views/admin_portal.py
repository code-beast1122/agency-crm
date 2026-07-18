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
from views.meetings import render_meetings
from views.credentials import render_access_codes, show_credentials
from utils.theme import ACCENT, empty_state, entity_card, page_header, section
from utils.ai_provider import chat
import os

def render(user):
    page_header("Admin Portal", "Full system control and analytics")

    active_tab = st.radio("Admin Navigation", [
        "Overview", 
        "Team Management", 
        "Projects",
        "Meetings",
        "Announcements",
        "AI Assistant",
        "Weekly Reports"
    ], horizontal=True, label_visibility="collapsed")
    
    st.divider()
    
    if active_tab == "Overview":
        st.subheader("System KPIs")
        render_overview()
        
    elif active_tab == "Team Management":
        st.subheader("Manage Departments & Users")
        render_user_management()
        
    elif active_tab == "Projects":
        st.subheader("Project Progress")
        render_projects()
        
    elif active_tab == "Meetings":
        render_meetings(user)

    elif active_tab == "Announcements":
        st.subheader("Global Announcements")
        render_announcements(user)
        
    elif active_tab == "AI Assistant":
        st.subheader("AI Data Analyst")
        render_ai_assistant()
        
    elif active_tab == "Weekly Reports":
        st.subheader("Coordinator Weekly Reports")
        render_weekly_reports()

def render_overview():
    # One cached call, six counts fired concurrently.
    counts = get_role_counts()

    # Split into two bands rather than one undifferentiated row of six. People
    # and business are different questions, and a flat row implied they were the
    # same kind of number.
    section("Business", "What the agency is currently delivering")
    col1, col2, col3 = st.columns(3)
    col1.metric("Clients", counts["clients"])
    col2.metric("Projects", counts["projects"])
    headcount = counts["admins"] + counts["coordinators"] + counts["hods"] + counts["employees"]
    col3.metric("Total Headcount", headcount)

    st.write("")
    section("Team", "Everyone with a login, by role")

    roles = {
        "Admins": counts["admins"],
        "Coordinators": counts["coordinators"],
        "HODs": counts["hods"],
        "Employees": counts["employees"],
    }
    col_stats, col_chart = st.columns([1, 1])

    with col_stats:
        top, bottom = st.columns(2), st.columns(2)
        for cell, (label, value) in zip(list(top) + list(bottom), roles.items()):
            cell.metric(label, value)

    with col_chart:
        # A chart of four numbers is not analysis, but it answers "is the shape
        # of this team sane?" at a glance, which the numbers alone do not.
        if headcount:
            st.bar_chart(
                pd.DataFrame({"Role": list(roles.keys()), "People": list(roles.values())})
                .set_index("Role"),
                color=ACCENT,
                height=220
            )
        else:
            empty_state("No team members yet", "Create a user under Team Management.")


def render_user_management():
    tab_users, tab_codes = st.tabs(["Departments & Roles", "Access Codes"])

    with tab_codes:
        render_access_codes()

    with tab_users:
        render_roles_and_departments()


def render_roles_and_departments():
    col1, col2 = st.columns([1, 2])

    with col1:
        section("Add Department")
        with st.form("add_dept_form"):
            dept_name = st.text_input("Department Name")
            if st.form_submit_button("Create Department", type="primary"):
                if dept_name:
                    res = supabase.table("departments").insert({"name": dept_name}).execute()
                    if res.data:
                        _invalidate_reads()
                        st.success(f"Department '{dept_name}' created!")
                        st.rerun()
                else:
                    st.error("Please enter a name.")

        depts = supabase.table("departments").select("*").execute().data
        section("Existing Departments", f"{len(depts)} in total" if depts else None)
        if depts:
            for d in depts:
                entity_card(d["name"])
        else:
            empty_state("No departments yet", "Create one above to start assigning HODs.")
            
        st.markdown("---")
        st.markdown("### Create New User Profile")
        st.info("Create a raw profile first, then assign it a role on the right.")
        with st.form("create_new_profile_form"):
            new_user_name = st.text_input("Full Name")
            if st.form_submit_button("Create Profile"):
                if new_user_name:
                    # role is NOT NULL, so a raw profile needs something in it.
                    # Assigning a role below overwrites this placeholder.
                    profile = create_profile(new_user_name, "employee")
                    st.success(f"Profile created for {new_user_name}!")
                    show_credentials(profile)
                else:
                    st.error("Please enter a name.")
            
    with col2:
        st.markdown("### Role Assignment")
        
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
                                st.success(f"{cal['message']} They must accept it to get reminders.")
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
    st.markdown("### Client Onboarding & Projects")
    
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
                            
                        st.success(f"Successfully onboarded {company_name}!")
                        show_credentials(profile)
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
    st.markdown("### Post a Global Announcement")
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
                
    st.markdown("### Active Announcements")
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
            st.markdown(f"**Goals Hit This Week:**\n{rep['goals_hit']}")
            st.divider()
            st.markdown(f"**Blockers & Issues:**\n{rep['blockers']}")
            st.divider()
            st.markdown(f"**Additional Notes:**\n{rep['notes']}")
    
# Every table PostgREST exposes, with the columns handed to the assistant.
#
# Columns are listed explicitly, never "*". This payload leaves our
# infrastructure for Groq, so every field here is a deliberate decision and a
# new column is invisible until someone adds it on purpose.
#
# Credentials ARE included at the user's explicit request, so the admin can ask
# the assistant for someone's login -- there is no forgot-password flow.
# profiles.session_token is the ONE deliberate omission: it is a live key to the
# account, and unlike a password there is no reason to ever read one back.
#
# Foreign keys are resolved to names inline (profiles(full_name), projects(title))
# rather than left as bare ids. An id alone forces the model to join across
# tables to name anyone, and when it cannot it invents a name -- which is exactly
# what the prompt below forbids. Giving it the name directly removes the need.
AI_CONTEXT_TABLES = {
    "profiles": "id, full_name, role, login_code, password, created_at",
    "departments": "id, name, created_at",
    "clients": "id, profile_id, company_name, created_at, profiles(full_name)",
    "projects": "id, client_id, title, status, created_at, clients(company_name)",
    "proposals": "id, project_id, file_url, version, status, created_at, projects(title)",
    "meetings": (
        "id, project_id, title, agenda, scheduled_at, duration_minutes, join_url, "
        "status, raw_notes, transcript, summary, created_by, show_meeting_to_client, "
        "show_summary_to_client, created_at, projects(title)"
    ),
    "tasks": (
        "id, project_id, assigned_to, title, description, task_source, status, "
        "estimated_hours, actual_hours, image_url, deadline, is_visible_to_client, "
        "employee_image_url, submission_notes, task_type, created_at, "
        "projects(title), profiles!tasks_assigned_to_fkey(full_name)"
    ),
    "time_logs": "id, task_id, employee_id, start_time, end_time, created_at, tasks(title)",
    "announcements": "id, message, created_by, is_active, created_at",
    "weekly_reports": "id, coordinator_id, goals_hit, blockers, notes, created_at",
    "activity_logs": "id, actor_profile_id, action, details, created_at",
    "admins": "id, profile_id, created_at, profiles(full_name)",
    "coordinators": "id, profile_id, email, calendar_id, created_at, profiles(full_name)",
    "hods": (
        "id, profile_id, department_id, email, calendar_id, created_at, "
        "profiles(full_name), departments(name)"
    ),
    "employees": (
        "id, profile_id, designation, department_id, email, calendar_id, created_at, "
        "profiles(full_name), departments(name)"
    ),
}

# Never hand this to the model. Asserted in the tests, not just documented.
AI_CONTEXT_FORBIDDEN = ("session_token",)


def build_db_dump():
    """Read every table for the assistant's context.

    A table that errors is reported rather than silently dropped: an assistant
    answering "no meetings exist" because the query failed is worse than one
    saying it could not read them.
    """
    dump = {}
    for table, columns in AI_CONTEXT_TABLES.items():
        try:
            dump[table] = supabase.table(table).select(columns).execute().data
        except Exception as e:
            dump[table] = {"error": "could not read {}: {}".format(table, e)}
    return dump


def render_ai_assistant():
    st.markdown("### CRM Data Analyst")
    st.info("Ask me anything about the agency's progress, departments, or projects.")
    
    # Initialize chat history
    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = [
            {"role": "assistant", "content": "Hello! I am your AI Data Analyst. How can I help you today?"}
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

        with st.chat_message("assistant"):
            # Fetch database context for the model.
            try:
                import json
                db_dump = build_db_dump()
                stats_str = "FULL DATABASE CONTEXT (JSON):\n" + json.dumps(db_dump, default=str)
            except Exception as e:
                stats_str = "Could not load current DB stats: {}".format(e)

            sys_prompt = f"You are a helpful CRM Data Analyst for an agency. You analyze departments, projects, and employees. " \
                         f"Do NOT invent or hallucinate names. ONLY use the names provided in the context. " \
                         f"Also dont include information like id. instead of mentioning id mention name " \
                         f"Use the following real-time data to answer the user's questions:\n{stats_str}"

            messages = [{"role": "system", "content": sys_prompt}]
            messages.extend(st.session_state.ai_messages)

            with st.spinner("Thinking..."):
                result = chat(messages)

            if result["status"] != "success":
                st.error("The assistant could not answer: {}".format(result["message"]))
            else:
                answer = result["content"]
                st.markdown(answer)
                if result["fell_back"]:
                    # Say so rather than quietly serving the backup: the admin
                    # should know which model answered, and that NIM needs a look.
                    st.caption(
                        "Answered by {} ({}) — the preferred model was unavailable: {}".format(
                            result["provider"], result["model"], "; ".join(result["errors"])
                        )
                    )
                st.session_state.ai_messages.append({"role": "assistant", "content": answer})
