import streamlit as st
import pandas as pd
from utils.db import (
    supabase, 
    get_all_projects, 
    get_all_tasks, 
    get_all_employees,
    create_profile,
    create_client_record,
    create_project,
    create_proposal,
    update_task,
    create_employee_record,
    create_task,
    get_all_clients,
    update_project
)
import uuid

def render(user):
    st.header("Manager Dashboard")
    
    tabs = st.tabs(["Client Onboarding", "Task Dispatcher", "Projects Overview", "Add Employee"])
    
    with tabs[0]:
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
                    # Generate a random login code
                    default_code = str(uuid.uuid4()).split('-')[0]
                    login_code = st.text_input("Access Code", value=default_code)
                    
                with col2:
                    st.write("**Project Details**")
                    project_title = st.text_input("Project Title")
                    proposal_file = st.file_uploader("Upload Initial Proposal (PDF)", type=["pdf"])
                    
                submitted = st.form_submit_button("Create Client & Project")
                
                if submitted:
                    if not (client_name and company_name and login_code and project_title):
                        st.error("Please fill in all text fields.")
                    else:
                        try:
                            # 1. Create Profile
                            profile = create_profile(client_name, "client", login_code)
                            
                            # 2. Create Client
                            client = create_client_record(profile["id"], company_name)
                            
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
                                
                            st.success(f"Successfully onboarded {company_name}! Their access code is: {login_code}")
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
                        
    with tabs[1]:
        st.subheader("Global Task Dispatcher")
        
        st.write("### Create Internal Task")
        all_projects = get_all_projects()
        if all_projects:
            with st.form("create_internal_task_form"):
                col1, col2 = st.columns(2)
                with col1:
                    proj_options = {f"{p['title']} ({p['clients']['company_name']})": p["id"] for p in all_projects}
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
                                supabase.storage.from_("documents").upload(
                                    file_name,
                                    new_task_file.getvalue(),
                                    {"content-type": new_task_file.type, "upsert": "true"}
                                )
                                file_url = supabase.storage.from_("documents").get_public_url(file_name)
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
        
        tasks = get_all_tasks()
        employees = get_all_employees()
        
        if not tasks:
            st.info("No tasks found.")
        else:
            # Map employees for selectbox
            emp_options = {"Unassigned": None}
            for e in employees:
                emp_name = e["profiles"]["full_name"]
                emp_options[f"{emp_name} ({e['designation']})"] = e["id"]
                
            for task in tasks:
                with st.expander(f"{task['title']} - {task['projects']['title']} ({task['status']})"):
                    st.write(f"**Description:** {task['description']}")
                    st.write(f"**Source:** {task['task_source']}")
                    
                    with st.form(f"dispatch_form_{task['id']}"):
                        col1, col2 = st.columns(2)
                        
                        # Find current assignee
                        current_assignee_name = "Unassigned"
                        if task["assigned_to"]:
                            for name, e_id in emp_options.items():
                                if e_id == task["assigned_to"]:
                                    current_assignee_name = name
                                    break
                                    
                        with col1:
                            assignee_name = st.selectbox(
                                "Assign To", 
                                options=list(emp_options.keys()), 
                                index=list(emp_options.keys()).index(current_assignee_name),
                                key=f"assign_{task['id']}"
                            )
                            is_visible = st.checkbox("Visible to Client Portal", value=task.get("is_visible_to_client", True), key=f"visible_{task['id']}")
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
                            updates = {
                                "assigned_to": emp_options[assignee_name],
                                "estimated_hours": est_hours,
                                "is_visible_to_client": is_visible
                            }
                            update_task(task["id"], updates)
                            st.success("Task updated.")
                            st.rerun()

    with tabs[2]:
        st.subheader("Projects Overview")
        projects = get_all_projects()
        
        if projects:
            df = pd.DataFrame(projects)
            df["company_name"] = df["clients"].apply(lambda x: x["company_name"])
            st.dataframe(df[["title", "company_name", "status", "created_at"]], hide_index=True)
            
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

    with tabs[3]:
        st.subheader("Add New Employee")
        st.write("Create a new employee profile to assign them tasks.")
        
        with st.form("add_employee_form"):
            col1, col2 = st.columns(2)
            with col1:
                emp_name = st.text_input("Full Name")
                # Generate a random login code
                emp_code = str(uuid.uuid4()).split('-')[0]
                emp_login_code = st.text_input("Access Code", value=emp_code)
                
            with col2:
                emp_dept = st.text_input("Department")
                emp_desig = st.text_input("Designation")
                
            submitted_emp = st.form_submit_button("Add Employee")
            
            if submitted_emp:
                if not (emp_name and emp_login_code and emp_dept and emp_desig):
                    st.error("Please fill in all fields.")
                else:
                    try:
                        # 1. Create Profile
                        emp_profile = create_profile(emp_name, "employee", emp_login_code)
                        
                        # 2. Create Employee record
                        create_employee_record(emp_profile["id"], emp_dept, emp_desig)
                        
                        st.success(f"Successfully added {emp_name}! Their access code is: {emp_login_code}")
                    except Exception as e:
                        st.error(f"Error adding employee: {str(e)}")

