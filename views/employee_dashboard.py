import streamlit as st
import pandas as pd
from utils.db import (
    supabase, 
    update_task, 
    start_task_timer, 
    stop_task_timer, 
    get_active_timer, 
    get_total_time_logged
)
def render(user):
    st.header("Employee Dashboard")
    
    # We need the employee's ID to fetch their tasks.
    # The user dictionary is their profile, so we need to get the employee record.
    employee_res = supabase.table("employees").select("id").eq("profile_id", user["id"]).execute()
    
    if not employee_res.data:
        st.error("Employee record not found for this profile.")
        return
        
    employee_id = employee_res.data[0]["id"]
    
    # Fetch tasks assigned to this employee
    tasks_res = supabase.table("tasks").select("*, projects(title)").eq("assigned_to", employee_id).execute()
    tasks = tasks_res.data
    
    if not tasks:
        st.info("No tasks assigned to you currently.")
        return
        
    st.write("### Your Assigned Tasks")
    
    for task in tasks:
        with st.expander(f"{task['title']} - {task['projects']['title']} ({task['status']})"):
            st.write(f"**Description:** {task['description']}")
            st.write(f"**Estimated Hours:** {task['estimated_hours']}")
            if task.get('image_url'):
                st.markdown(f"**Manager Attachment:** [View/Download File]({task['image_url']})")
            if task.get('employee_image_url'):
                st.markdown(f"**Your Attachment:** [View/Download File]({task['employee_image_url']})")
            
            # Time Tracking UI
            active_timer = get_active_timer(task['id'], employee_id)
            total_logged = get_total_time_logged(task['id'])
            
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.write(f"**Total Tracked Time:** {total_logged:.2f} hrs")
            with col_t2:
                if active_timer:
                    if st.button("Stop Work", key=f"stop_{task['id']}", type="primary"):
                        stop_task_timer(active_timer['id'])
                        new_total = get_total_time_logged(task['id'])
                        update_task(task['id'], {"actual_hours": new_total})
                        st.rerun()
                else:
                    if st.button("Start Work", key=f"start_{task['id']}"):
                        start_task_timer(task['id'], employee_id)
                        st.rerun()
            
            st.write("---")
            
            with st.form(f"update_task_form_{task['id']}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    new_status = st.selectbox("Status", ["todo", "in_progress", "review", "done"], index=["todo", "in_progress", "review", "done"].index(task['status']))
                    
                with col2:
                    task_file = st.file_uploader("Upload Progress File", type=["png", "jpg", "jpeg", "pdf", "doc", "docx", "zip", "txt", "csv", "xlsx"])
                    
                submitted = st.form_submit_button("Update Task")
                
                if submitted:
                    updates = {
                        "status": new_status,
                        "actual_hours": total_logged
                    }
                    
                    if task_file:
                        try:
                            # Upload to Supabase Storage
                            file_ext = task_file.name.split('.')[-1]
                            file_name = f"task_{task['id']}_emp.{file_ext}"
                            
                            # Upload file. Use upsert so it overwrites if an image already exists.
                            res = supabase.storage.from_("task_images").upload(
                                file_name, 
                                task_file.getvalue(), 
                                {"content-type": task_file.type, "upsert": "true"}
                            )
                            
                            # Get public URL
                            public_url = supabase.storage.from_("task_images").get_public_url(file_name)
                            updates["employee_image_url"] = public_url
                        except Exception as e:
                            st.error(f"Failed to upload file: {str(e)}")
                            
                    update_task(task['id'], updates)
                    st.success("Task updated successfully!")
                    st.rerun()
