import streamlit as st
import pandas as pd
from utils.db import get_projects_for_client, get_tasks_for_project, create_task, supabase

def render(user):
    st.header(f"Client Portal")
    
    projects = get_projects_for_client(user["id"])
    
    if not projects:
        st.info("No projects found for your account.")
        return
        
    # Create tabs for projects
    project_titles = [p["title"] for p in projects]
    tabs = st.tabs(project_titles)
    
    for i, tab in enumerate(tabs):
        with tab:
            project = projects[i]
            st.subheader(project["title"])
            inner_tabs = st.tabs(["Overview", "Tasks"])
            
            with inner_tabs[0]:
                st.write(f"Status: **{project['status'].capitalize()}**")
                
                # Fetch proposals for this project
                proposals_response = supabase.table("proposals").select("*").eq("project_id", project["id"]).execute()
                if proposals_response.data:
                    st.write("### Proposals")
                    for prop in proposals_response.data:
                        st.write(f"- Version {prop['version']} ({prop['status']}): [View Proposal]({prop['file_url']})")
                        
            with inner_tabs[1]:
                # Fetch tasks to calculate completion
                all_tasks = get_tasks_for_project(project["id"])
                tasks = [t for t in all_tasks if t.get("is_visible_to_client", True)]
                if tasks:
                    total_tasks = len(tasks)
                    done_tasks = len([t for t in tasks if t["status"] == "done"])
                    completion = done_tasks / total_tasks
                    
                    st.write("### Progress")
                    st.progress(completion)
                    st.write(f"{done_tasks} / {total_tasks} tasks completed ({int(completion * 100)}%)")
                    
                    # Show tasks
                    st.write("### Task Details")
                    for task in tasks:
                        with st.expander(f"{task['title']} ({task['status']})"):
                            st.write(f"**Description:** {task['description']}")
                            st.write(f"**Source:** {task['task_source']}")
                            if task.get('estimated_hours'):
                                st.write(f"**Estimated Hours:** {task['estimated_hours']}")
                            if task.get('deadline'):
                                st.write(f"**Deadline:** {task['deadline']}")
                                
                            if task.get('image_url'):
                                st.markdown(f"**Initial Attachment:** [View/Download File]({task['image_url']})")
                            if task.get('employee_image_url'):
                                st.markdown(f"**Progress Update:** [View/Download File]({task['employee_image_url']})")
                else:
                    st.write("No tasks found for this project yet.")
                
                # Form to request new tasks
                st.write("---")
                st.write("### Request New Task")
                
                if project.get("status") in ["cancelled", "completed"]:
                    st.info(f"This project is currently marked as **{project.get('status')}**. You cannot request new tasks for it.")
                else:
                    with st.form(f"request_task_form_{project['id']}"):
                        task_title = st.text_input("Task Title")
                        task_description = st.text_area("Description")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            task_deadline = st.date_input("Deadline Date", value=None)
                        with col2:
                            task_file = st.file_uploader("Attach File (Optional)", type=["png", "jpg", "jpeg", "pdf", "doc", "docx", "zip", "txt", "csv", "xlsx"])
                            
                        submitted = st.form_submit_button("Submit Request")
                        
                        if submitted:
                            if task_title:
                                file_url = None
                                if task_file:
                                    import uuid
                                    file_ext = task_file.name.split('.')[-1]
                                    file_name = f"client_task_{uuid.uuid4().hex}.{file_ext}"
                                    
                                    try:
                                        supabase.storage.from_("task_images").upload(
                                            file_name,
                                            task_file.getvalue(),
                                            {"content-type": task_file.type, "upsert": "true"}
                                        )
                                        file_url = supabase.storage.from_("task_images").get_public_url(file_name)
                                    except Exception as e:
                                        st.error(f"Failed to upload file: {e}")
                                        
                                deadline_str = task_deadline.isoformat() if task_deadline else None
                                
                                create_task(
                                    project_id=project["id"],
                                    title=task_title,
                                    description=task_description,
                                    source="client_request",
                                    deadline=deadline_str,
                                    image_url=file_url
                                )
                                st.success("Task requested successfully!")
                                st.rerun()
                            else:
                                st.error("Task title is required.")
