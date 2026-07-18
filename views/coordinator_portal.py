import streamlit as st
import pandas as pd
from utils.db import (
    supabase,
    get_all_projects,
    get_coordinator_level_tasks,
    get_all_hods,
    create_profile,
    create_client_record,
    create_project,
    create_proposal,
    update_task,
    create_employee_record,
    create_task,
    get_all_clients,
    update_project,
    get_total_time_logged_bulk,
    get_proposals_bulk,
    get_hods_with_departments,
    sync_task_deadline,
    sync_profile_role
)
from views.meetings import render_meetings
from views.credentials import show_credentials
from utils.theme import empty_state, entity_card, page_header, section
import uuid

def render(user):
    page_header("Coordinator Portal", "Clients, dispatch and delivery")

    active_tab = st.radio("Coordinator Navigation", [
        "Client Onboarding", 
        "Task Dispatcher", 
        "Projects Overview",
        "Meetings",
        "Team Management",
        "Weekly Report",
        "AI Assistant"
    ], horizontal=True, label_visibility="collapsed")
    
    st.divider()
    
    if active_tab == "Client Onboarding":
        st.subheader("Client Management")
        
        onboarding_tabs = st.tabs(["Onboard New Client", "Add Project for Existing Client"])
        
        with onboarding_tabs[0]:
            st.write("Create a new client profile, project, and initial proposal in one step.")
            
            with st.form("onboarding_form"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Client Details**")
                    client_name = st.text_input("Contact Full Name")
                    company_name = st.text_input("Company Name")
                with col2:
                    st.write("**Project Details**")
                    project_title = st.text_input("Project Title")
                    proposal_file = st.file_uploader("Upload Initial Proposal (PDF)", type=["pdf"])
                    
                submitted = st.form_submit_button("Create Client & Project")
                
                if submitted:
                    if not (client_name and company_name and project_title):
                        st.error("Please fill in all text fields.")
                    else:
                        try:
                            # 1. Create Profile
                            profile = create_profile(client_name, "client")
                            
                            # 2. Create Client
                            client = create_client_record(profile["id"], company_name)
                            # The role tables are the source of truth for the label.
                            sync_profile_role(profile["id"])
                            
                            # 3. Create Project
                            project = create_project(client["id"], project_title)
                            
                            # 4. Upload Proposal & Create Record
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
                            
        with onboarding_tabs[1]:
            st.write("Create a new project for an existing client.")
            clients = get_all_clients()
            if clients:
                with st.form("new_project_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        client_options = {f"{c['company_name']} ({c['profiles']['full_name']})": c["id"] for c in clients}
                        selected_client = st.selectbox("Select Client", list(client_options.keys()))
                    with col2:
                        new_proj_title = st.text_input("Project Title")
                        new_proposal_file = st.file_uploader("Upload Initial Proposal (PDF)", type=["pdf"])
                        
                    submitted_new_proj = st.form_submit_button("Create Project")
                    
                    if submitted_new_proj:
                        if new_proj_title:
                            try:
                                client_id = client_options[selected_client]
                                project = create_project(client_id, new_proj_title)
                                
                                if new_proposal_file:
                                    file_ext = new_proposal_file.name.split('.')[-1]
                                    file_name = f"proposal_{project['id']}.{file_ext}"
                                    
                                    supabase.storage.from_("documents").upload(
                                        file_name,
                                        new_proposal_file.getvalue(),
                                        {"content-type": new_proposal_file.type, "upsert": "true"}
                                    )
                                    
                                    public_url = supabase.storage.from_("documents").get_public_url(file_name)
                                    create_proposal(project["id"], public_url)
                                    
                                st.success(f"Successfully created project '{new_proj_title}'!")
                            except Exception as e:
                                st.error(f"Error creating project: {str(e)}")
                        else:
                            st.error("Project Title is required.")
            else:
                st.info("No clients exist yet. Please onboard a client first.")
                        
    elif active_tab == "Task Dispatcher":
        st.subheader("Global Task Dispatcher")
        
        st.write("### Create Internal Task")
        all_projects = get_all_projects()
        active_projects = [p for p in all_projects if p.get("status") not in ["cancelled", "completed"]] if all_projects else []
        
        if active_projects:
            with st.form("create_internal_task_form"):
                col1, col2 = st.columns(2)
                with col1:
                    proj_options = {f"{p['title']} ({p['clients']['company_name']})": p["id"] for p in active_projects}
                    selected_proj_title = st.selectbox("Select Project", list(proj_options.keys()))
                    new_task_title = st.text_input("Task Title")
                    new_task_desc = st.text_area("Description")
                with col2:
                    new_task_deadline = st.date_input("Deadline (Optional)", value=None)
                    new_task_est_hours = st.number_input("Estimated Hours", min_value=0.0, step=0.5)
                    new_task_file = st.file_uploader("Attach File (Optional)", type=["png", "jpg", "jpeg", "pdf", "doc", "docx", "zip", "txt", "csv", "xlsx"], key="manager_task_file")
                    
                submitted_new_task = st.form_submit_button("Create Task")
                
                if submitted_new_task:
                    if new_task_title:
                        file_url = None
                        if new_task_file:
                            file_ext = new_task_file.name.split('.')[-1]
                            file_name = f"manager_task_{uuid.uuid4().hex}.{file_ext}"
                            try:
                                supabase.storage.from_("task_images").upload(
                                    file_name,
                                    new_task_file.getvalue(),
                                    {"content-type": new_task_file.type, "upsert": "true"}
                                )
                                file_url = supabase.storage.from_("task_images").get_public_url(file_name)
                            except Exception as e:
                                st.error(f"Failed to upload file: {e}")
                                
                        create_task(
                            project_id=proj_options[selected_proj_title],
                            title=new_task_title,
                            description=new_task_desc,
                            source="internal",
                            deadline=new_task_deadline.isoformat() if new_task_deadline else None,
                            image_url=file_url,
                            estimated_hours=new_task_est_hours
                        )
                        st.success("Internal task created successfully!")
                        st.rerun()
                    else:
                        st.error("Task title is required.")
        else:
            st.info("You need to create a project before you can create tasks.")
            
        st.write("---")
        st.write("### Assign Existing Tasks")
        st.caption("Unassigned work and tasks sitting with an HOD. Work an HOD has passed down to their team is tracked by that HOD.")

        tasks = get_coordinator_level_tasks()
        hods = get_all_hods()

        if not tasks:
            st.info("No tasks at your level right now.")
        else:
            # Map HODs for selectbox
            hod_options = {"Unassigned": None}
            for h in hods:
                hod_name = h["profiles"]["full_name"]
                hod_options[f"HOD: {hod_name}"] = h["profile_id"]

            tracked_by_task = get_total_time_logged_bulk([t["id"] for t in tasks])

            for task in tasks:
                with st.expander(f"{task['title']} - {task['projects']['title']} ({task['status']})"):
                    total_tracked = tracked_by_task.get(task['id'], 0.0)
                    st.write(f"**Description:** {task['description']}")
                    st.write(f"**Source:** {task['task_source']}")
                    st.write(f"**Tracked Time:** {total_tracked:.2f} hrs (Manually Logged: {task.get('actual_hours', 0)} hrs)")
                    if task.get('image_url'):
                        st.markdown(f"**Your Attachment:** [View/Download File]({task['image_url']})")
                    if task.get('employee_image_url'):
                        st.markdown(f"**Employee Attachment:** [View/Download File]({task['employee_image_url']})")
                    with st.form(f"dispatch_form_{task['id']}"):
                        col1, col2 = st.columns(2)
                        
                        # Find current assignee in HODs
                        current_assignee_name = "Unassigned"
                        if task["assigned_to"]:
                            for name, p_id in hod_options.items():
                                if p_id == task["assigned_to"]:
                                    current_assignee_name = name
                                    break
                                    
                        with col1:
                            assignee_name = st.selectbox(
                                "Assign To HOD", 
                                options=list(hod_options.keys()), 
                                index=list(hod_options.keys()).index(current_assignee_name),
                                key=f"assign_{task['id']}"
                            )
                            # Only client requests can ever reach the client portal,
                            # so the toggle would be a no-op on an internal task.
                            if task.get("task_source") == "client_request":
                                is_visible = st.checkbox(
                                    "Visible to Client Portal",
                                    value=task.get("is_visible_to_client", True),
                                    key=f"visible_{task['id']}"
                                )
                            else:
                                is_visible = task.get("is_visible_to_client", True)
                                st.caption("Internal task — never shown in the client portal.")
                        with col2:
                            est_hours = st.number_input(
                                "Estimated Hours", 
                                min_value=0.0, 
                                value=float(task.get('estimated_hours', 0.0) or 0.0), 
                                step=0.5,
                                key=f"est_{task['id']}"
                            )
                            
                        submitted = st.form_submit_button("Update Task & Save Changes")
                        
                        if submitted:
                            new_assignee_id = hod_options[assignee_name]
                            updates = {
                                "assigned_to": new_assignee_id,
                                "estimated_hours": est_hours,
                                "is_visible_to_client": is_visible
                            }
                            update_task(task["id"], updates)

                            # Assignment happens here, not at creation, so this is
                            # where a client-requested task's deadline first gets
                            # an owner worth putting on the calendar.
                            if new_assignee_id and new_assignee_id != task.get("assigned_to"):
                                sync_task_deadline(task["id"])

                            st.success("Task updated.")
                            st.rerun()

    elif active_tab == "Projects Overview":
        st.subheader("Projects Overview")
        projects = get_all_projects()
        
        if projects:
            df = pd.DataFrame(projects)
            df["company_name"] = df["clients"].apply(lambda x: x["company_name"])

            # Surface the client's accept/reject decision -- otherwise it is
            # invisible work: the client acts and nobody on staff ever sees it.
            proposals_by_project = get_proposals_bulk([p["id"] for p in projects])
            df["latest_proposal"] = df["id"].apply(
                lambda pid: proposals_by_project[pid][0]["status"] if proposals_by_project.get(pid) else "none"
            )

            st.dataframe(df[["title", "company_name", "status", "latest_proposal", "created_at"]], hide_index=True)
            
            st.write("---")
            st.write("### Update Project Status")
            
            col1, col2 = st.columns(2)
            with col1:
                proj_options = {f"{p['title']} ({p['clients']['company_name']})": p for p in projects}
                selected_proj_key = st.selectbox("Select Project", list(proj_options.keys()), key="proj_status_select")
            with col2:
                selected_proj = proj_options[selected_proj_key]
                current_status = selected_proj["status"]
                
                valid_statuses = ["pitching", "active", "completed", "on_hold", "cancelled"]
                idx = valid_statuses.index(current_status) if current_status in valid_statuses else 0
                
                new_status = st.selectbox(
                    "New Status", 
                    valid_statuses, 
                    index=idx,
                    key="new_status_select"
                )
            
            if st.button("Update Status", key="btn_update_proj_status"):
                if new_status != current_status:
                    update_project(selected_proj["id"], {"status": new_status})
                    st.success(f"Project status updated to {new_status}!")
                    st.rerun()
                else:
                    st.info(f"Status is already '{current_status}'.")
        else:
            st.info("No projects yet.")

    elif active_tab == "Meetings":
        render_meetings(user)

    elif active_tab == "Team Management":
        hods = get_hods_with_departments()
        section(
            "Heads of Department",
            f"{len(hods)} HODs you can dispatch work to" if hods else "Who you can dispatch work to"
        )
        if hods:
            for hod in hods:
                entity_card(
                    hod["profiles"]["full_name"],
                    subtitle=f"HOD of {hod['departments']['name']}",
                    meta=hod["departments"]["name"]
                )
        else:
            empty_state(
                "No HODs assigned yet",
                "An admin assigns the HOD role under Team Management."
            )
            
    elif active_tab == "Weekly Report":
        st.subheader("Weekly Report")
        with st.form("weekly_report_form"):
            goals = st.text_area("Goals Hit This Week")
            blockers = st.text_area("Blockers & Issues")
            notes = st.text_area("Additional Notes")
            
            if st.form_submit_button("Submit Report to Admin"):
                coord_rec = supabase.table("coordinators").select("id").eq("profile_id", user['id']).execute().data
                if coord_rec:
                    res = supabase.table("weekly_reports").insert({
                        "coordinator_id": coord_rec[0]['id'],
                        "goals_hit": goals,
                        "blockers": blockers,
                        "notes": notes
                    }).execute()
                    if res.data:
                        st.success("Weekly Report submitted successfully!")
                else:
                    st.error("You are not registered in the coordinators table.")
                    
    elif active_tab == "AI Assistant":
        st.subheader("AI Data Analyst")
        st.info("AI Chat coming soon to Coordinator Portal.")

