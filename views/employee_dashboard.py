import streamlit as st
import pandas as pd
from utils.db import (
    supabase,
    update_task,
    start_task_timer,
    stop_task_timer,
    get_active_timers_bulk,
    get_total_time_logged,
    get_total_time_logged_bulk,
    get_employee_by_profile_id,
    get_tasks_assigned_to
)
from utils.theme import page_header

def render(user):
    page_header("My Workspace", f"Signed in as {user.get('full_name', 'employee')}")

    # We fetch tasks directly assigned to this user's profile ID
    profile_id = user["id"]
    
    # We still need employee_id for time logging
    employee = get_employee_by_profile_id(profile_id)
    employee_id = employee["id"] if employee else None

    # Fetch tasks assigned to this profile
    tasks = get_tasks_assigned_to(profile_id)
    
    if not tasks:
        st.info("No tasks assigned to you currently.")
        return
        
    active_tab = st.radio("Employee Navigation", [
        "Active Tasks", 
        "Completed Tasks"
    ], horizontal=True, label_visibility="collapsed")
    
    st.divider()
    
    active_tasks = [t for t in tasks if t.get('status') != 'done']
    completed_tasks = [t for t in tasks if t.get('status') == 'done']

    task_ids = [t["id"] for t in tasks]
    tracked_by_task = get_total_time_logged_bulk(task_ids)
    timers_by_task = get_active_timers_bulk(task_ids, employee_id)

    if active_tab == "Active Tasks":
        if not active_tasks:
            st.info("No active tasks assigned to you.")
        else:
            for task in active_tasks:
                render_task(task, employee_id, tracked_by_task.get(task['id'], 0.0), timers_by_task.get(task['id']))

    elif active_tab == "Completed Tasks":
        if not completed_tasks:
            st.info("No completed tasks.")
        else:
            for task in completed_tasks:
                render_task(task, employee_id, tracked_by_task.get(task['id'], 0.0), timers_by_task.get(task['id']))

def render_task(task, employee_id, total_logged, active_timer):
        with st.expander(f"{task['title']} - {task.get('projects', {}).get('title', 'No Project')} ({task['status']})"):
            st.write(f"**Description:** {task['description']}")
            st.write(f"**Estimated Hours:** {task.get('estimated_hours', 0.0)}")
            if task.get('image_url'):
                st.markdown(f"**Manager Attachment:** [View/Download File]({task['image_url']})")
            if task.get('employee_image_url'):
                st.markdown(f"**Your Attachment:** [View/Download File]({task['employee_image_url']})")
            
            # Time Tracking UI (the running timer is fetched in bulk by the caller)
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
                    statuses = ["todo", "in_progress", "review", "done"]
                    current = task.get('status')
                    new_status = st.selectbox(
                        "Status",
                        statuses,
                        index=statuses.index(current) if current in statuses else 0
                    )

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
