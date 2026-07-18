import streamlit as st
import pandas as pd
from utils.db import (
    supabase,
    create_profile,
    create_employee_record,
    create_task,
    get_all_projects,
    get_team_tasks,
    get_total_time_logged_bulk,
    get_hod_department,
    get_tasks_assigned_to,
    get_department_employees,
    get_meetings_for_hod,
    normalize_join_url,
    provision_calendar,
    sync_profile_role
)
from views.credentials import show_credentials
from views.meetings import MEETING_STATUS_COLORS, is_upcoming, meeting_time
from utils.theme import badge, empty_state, entity_card, page_header, section
import uuid

def render(user):
    # Looked up before the masthead so the department can name it: "HOD Portal"
    # alone doesn't tell someone which desk they are sitting at.
    hod_rec = get_hod_department(user['id'])
    if not hod_rec:
        page_header("Head of Department")
        st.error("You are not assigned to a department.")
        return

    dept_id = hod_rec['department_id']
    dept_name = hod_rec['departments']['name']

    page_header("Head of Department", f"{dept_name} department")

    active_tab = st.radio("HOD Navigation", [
        "My Tasks (From Coordinator)",
        "Dispatch to Team",
        "Team Tasks",
        "My Team",
        "Meetings"
    ], horizontal=True, label_visibility="collapsed")

    st.divider()

    if active_tab == "Meetings":
        render_hod_meetings(user)

    elif active_tab == "My Tasks (From Coordinator)":
        st.markdown("### Tasks Assigned to Me (From Coordinator)")
        
        # Fetch tasks assigned to the HOD's profile ID
        my_tasks = get_tasks_assigned_to(user['id'])
        
        if not my_tasks:
            st.info("No tasks assigned to you currently.")
        else:
            for task in my_tasks:
                with st.expander(f"{task['title']} - {task.get('projects', {}).get('title', 'No Project')} ({task['status']})"):
                    st.write(f"**Description:** {task['description']}")
                    st.write(f"**Estimated Hours:** {task.get('estimated_hours', 0.0)}")
                    if task.get('image_url'):
                        st.markdown(f"**Coordinator Attachment:** [View/Download File]({task['image_url']})")
                    if task.get('employee_image_url'):
                        st.markdown(f"**Your Submission:** [View/Download File]({task['employee_image_url']})")
                    if task.get('submission_notes'):
                        st.markdown(f"**Submission Notes:** {task['submission_notes']}")
                        
                    st.write("---")
                    
                    if task['status'] != 'done':
                        with st.form(f"hod_update_task_form_{task['id']}"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                statuses = ["todo", "in_progress", "review", "done"]
                                current = task.get('status')
                                new_status = st.selectbox(
                                    "Status",
                                    statuses,
                                    index=statuses.index(current) if current in statuses else 0
                                )
                                sub_notes = st.text_area("Submission Notes / Links", value=task.get("submission_notes") or "")
                                
                            with col2:
                                task_file = st.file_uploader("Upload Deliverable", type=["png", "jpg", "jpeg", "pdf", "doc", "docx", "zip", "txt", "csv", "xlsx"])
                                
                            submitted = st.form_submit_button("Submit & Update Task")
                            
                            if submitted:
                                updates = {
                                    "status": new_status,
                                    "submission_notes": sub_notes
                                }
                                
                                if task_file:
                                    import uuid
                                    file_ext = task_file.name.split('.')[-1]
                                    file_name = f"hod_task_{uuid.uuid4().hex}.{file_ext}"
                                    try:
                                        supabase.storage.from_("task_images").upload(
                                            file_name,
                                            task_file.getvalue(),
                                            {"content-type": task_file.type, "upsert": "true"}
                                        )
                                        file_url = supabase.storage.from_("task_images").get_public_url(file_name)
                                        updates["employee_image_url"] = file_url
                                    except Exception as e:
                                        st.error(f"Failed to upload file: {e}")
                                        
                                from utils.db import update_task
                                update_task(task["id"], updates)
                                st.success("Task updated successfully!")
                                st.rerun()
        
    elif active_tab == "Dispatch to Team":
        st.markdown("### Dispatch Tasks to Employees")
        emps = get_department_employees(dept_id)
        projects = get_all_projects()
        
        if emps and projects:
            with st.form("hod_dispatch_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    task_title = st.text_input("Task Title")
                    task_desc = st.text_area("Description")
                    proj_options = {f"{p['title']}": p['id'] for p in projects}
                    selected_proj_id = st.selectbox("Project", options=list(proj_options.keys()), format_func=lambda x: x)
                    selected_proj_id = proj_options[selected_proj_id]
                    
                with col2:
                    emp_options = {e['profile_id']: e['profiles']['full_name'] for e in emps}
                    selected_emp = st.selectbox("Assign To", options=list(emp_options.keys()), format_func=lambda x: emp_options[x])
                    task_type = st.selectbox("Task Type", ["daily", "weekly", "one-off"])
                    deadline = st.date_input("Deadline")
                    est_hours = st.number_input("Estimated Hours", min_value=0.0, step=0.5)
                    new_task_file = st.file_uploader("Attach File (Optional)", type=["png", "jpg", "jpeg", "pdf", "doc", "docx", "zip", "txt", "csv", "xlsx"], key="hod_dispatch_file")
                    
                if st.form_submit_button("Dispatch Task"):
                    if task_title:
                        # Find the selected employee's email
                        emp_email = None
                        for e in emps:
                            if e['profile_id'] == selected_emp:
                                emp_email = e.get('email')
                                break
                                
                        file_url = None
                        if new_task_file:
                            import uuid
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
                                
                        res = create_task(
                            project_id=selected_proj_id,
                            title=task_title,
                            description=task_desc,
                            source="internal",
                            deadline=deadline.isoformat(),
                            estimated_hours=est_hours,
                            task_type=task_type,
                            assigned_to=selected_emp,
                            assignee_email=emp_email,
                            image_url=file_url
                        )
                        st.success("Task dispatched!")
                    else:
                        st.error("Title is required.")
        else:
            st.info("You need both Employees in your department and active Projects to dispatch tasks.")
        
    elif active_tab == "Team Tasks":
        st.markdown("### Work I Dispatched to My Team")
        st.caption("Everything assigned to employees in this department, and what they have submitted back.")

        team_tasks = get_team_tasks(dept_id)

        if not team_tasks:
            st.info("You have not dispatched any tasks to your team yet.")
        else:
            done_count = len([t for t in team_tasks if t.get("status") == "done"])
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Dispatched", len(team_tasks))
            col2.metric("Completed", done_count)
            col3.metric("In Progress", len(team_tasks) - done_count)

            st.write("---")

            tracked_by_task = get_total_time_logged_bulk([t["id"] for t in team_tasks])

            for task in team_tasks:
                assignee = (task.get("profiles") or {}).get("full_name", "Unassigned")
                project_title = (task.get("projects") or {}).get("title", "No Project")

                with st.expander(f"{task['title']} — {assignee} ({task['status']})"):
                    st.write(f"**Project:** {project_title}")
                    st.write(f"**Description:** {task['description']}")
                    st.write(f"**Estimated:** {task.get('estimated_hours', 0.0)} hrs  |  **Tracked:** {tracked_by_task.get(task['id'], 0.0):.2f} hrs")
                    if task.get("deadline"):
                        st.write(f"**Deadline:** {task['deadline']}")

                    if task.get("image_url"):
                        st.markdown(f"**Your Attachment:** [View/Download File]({task['image_url']})")

                    st.write("---")

                    if task.get("employee_image_url"):
                        st.markdown(f"**Employee Submission:** [View/Download File]({task['employee_image_url']})")
                    if task.get("submission_notes"):
                        st.markdown(f"**Submission Notes:** {task['submission_notes']}")
                    if not task.get("employee_image_url") and not task.get("submission_notes"):
                        st.caption("Nothing submitted yet.")

    elif active_tab == "My Team":
        st.markdown("### Add New Employee")
        with st.form("add_dept_employee_form"):
            col1, col2 = st.columns(2)
            with col1:
                emp_name = st.text_input("Full Name")
                emp_email = st.text_input("Email (For Calendar Invites)")
            with col2:
                emp_desig = st.text_input("Designation (e.g., Junior Dev)")
                
            if st.form_submit_button("Add Employee"):
                if not (emp_name and emp_desig and emp_email):
                    st.error("Please fill in all fields.")
                else:
                    try:
                        # Create Profile
                        emp_profile = create_profile(emp_name, "employee")
                        # Add to employees table with department and email
                        create_employee_record(emp_profile["id"], dept_id, emp_desig, emp_email)
                        # The role tables are the source of truth for the label.
                        sync_profile_role(emp_profile["id"])
                        st.success(f"Added {emp_name} to {dept_name}!")
                        show_credentials(emp_profile)

                        cal = provision_calendar(emp_profile["id"], emp_name, emp_email, "employees")
                        if cal.get("status") == "success":
                            st.success(f"{cal['message']} They must accept it to get reminders.")
                        else:
                            st.warning(f"Employee added, but the calendar invite failed: {cal.get('message')}")
                    except Exception as e:
                        st.error(f"Error adding employee: {str(e)}")
                        
        st.write("---")
        emps = get_department_employees(dept_id)
        section("Current Team Members", f"{len(emps)} in {dept_name}" if emps else None)
        if emps:
            for emp in emps:
                entity_card(emp["profiles"]["full_name"], meta=emp["designation"])
        else:
            empty_state(
                "No employees in this department yet",
                "Add your first team member above."
            )


def render_hod_meetings(user):
    """Meetings a coordinator or admin has tagged this HOD to attend.

    Read-only by design: scheduling, editing, and the AI summary tools live in
    views/meetings.py for the admin/coordinator who own the meeting. An HOD is
    an attendee, not an organiser, so this only ever shows what is already
    there -- there is nothing here for them to break.
    """
    meetings = get_meetings_for_hod(user["id"])

    if not meetings:
        empty_state(
            "No meetings yet",
            "When a coordinator or admin tags you on a meeting, it appears here."
        )
        return

    upcoming = [m for m in meetings if is_upcoming(m)]
    past = [m for m in meetings if not is_upcoming(m)]

    if upcoming:
        section("Upcoming", f"{len(upcoming)} scheduled")
        for meeting in upcoming:
            render_hod_meeting_card(meeting)

    if past:
        section("Past Meetings", f"{len(past)} held")
        for meeting in past:
            render_hod_meeting_card(meeting)


def render_hod_meeting_card(meeting):
    project = meeting.get("projects") or {}
    client_name = (project.get("clients") or {}).get("company_name")

    with st.container(border=True):
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown(f"**{meeting['title']}**")
            sub = project.get("title", "Unknown project")
            if client_name:
                sub += f" — {client_name}"
            st.caption(sub)
            when = meeting_time(meeting)
            if when:
                st.caption(when.strftime("%d %b %Y at %H:%M") + f" · {meeting.get('duration_minutes', 30)} min")
        with col_b:
            badge(meeting["status"], MEETING_STATUS_COLORS)

        if meeting.get("agenda"):
            st.write(meeting["agenda"])

        # An HOD is internal staff, not a client -- unlike the client portal,
        # there is no visibility toggle to check here. If they were tagged,
        # they see everything about the meeting, including the summary.
        join_url = normalize_join_url(meeting.get("join_url"))
        if join_url:
            st.link_button("Join Meeting", join_url, type="primary")

        if meeting.get("summary"):
            with st.expander("Meeting Summary"):
                st.markdown(meeting["summary"])
