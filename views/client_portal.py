import streamlit as st
import pandas as pd
from utils.db import (
    get_client_by_profile_id,
    get_projects_for_client,
    get_tasks_for_projects_bulk,
    get_proposals_bulk,
    update_proposal_status,
    create_task,
    supabase
)

# Values of the proposal_status enum in Postgres. Writing anything outside this
# set raises 22P02, so never inline these as bare strings.
PROPOSAL_DRAFT = "draft"
PROPOSAL_SENT = "sent"
PROPOSAL_APPROVED = "approved"
PROPOSAL_REJECTED = "rejected"

# A proposal the client has already decided on is final -- no flip-flopping.
PROPOSAL_DECIDED = (PROPOSAL_APPROVED, PROPOSAL_REJECTED)

PROJECT_STATUS_COLORS = {
    "pitching": ("#f59e0b", "rgba(245, 158, 11, 0.15)"),
    "active": ("#22c55e", "rgba(34, 197, 94, 0.15)"),
    "on_hold": ("#94a3b8", "rgba(148, 163, 184, 0.15)"),
    "completed": ("#0ea5e9", "rgba(14, 165, 233, 0.15)"),
    "cancelled": ("#ef4444", "rgba(239, 68, 68, 0.15)"),
}

TASK_STATUS_COLORS = {
    "todo": ("#94a3b8", "rgba(148, 163, 184, 0.15)"),
    "in_progress": ("#f59e0b", "rgba(245, 158, 11, 0.15)"),
    "review": ("#a855f7", "rgba(168, 85, 247, 0.15)"),
    "done": ("#22c55e", "rgba(34, 197, 94, 0.15)"),
}

PROPOSAL_STATUS_COLORS = {
    PROPOSAL_DRAFT: ("#94a3b8", "rgba(148, 163, 184, 0.15)"),
    PROPOSAL_SENT: ("#0ea5e9", "rgba(14, 165, 233, 0.15)"),
    PROPOSAL_APPROVED: ("#22c55e", "rgba(34, 197, 94, 0.15)"),
    PROPOSAL_REJECTED: ("#ef4444", "rgba(239, 68, 68, 0.15)"),
}


def badge(label, colors):
    """Render a status pill. Mirrors the role badge styling in app.py."""
    fg, bg = colors.get(str(label).lower(), ("#94a3b8", "rgba(148, 163, 184, 0.15)"))
    text = str(label).replace("_", " ").upper()
    st.markdown(
        f"""<span style="
            font-size: 0.7rem; font-weight: 700; color: {fg};
            background-color: {bg}; border: 1px solid {fg}55;
            padding: 0.2rem 0.7rem; border-radius: 9999px;
            display: inline-block; letter-spacing: 0.05em;
        ">{text}</span>""",
        unsafe_allow_html=True
    )


def visible_proposals(proposals):
    """A draft is staff work-in-progress -- the client only sees it once sent."""
    return [p for p in proposals if p.get("status") != PROPOSAL_DRAFT]


def visible_tasks(all_tasks):
    """STRICT LOCKDOWN: Clients ONLY see tasks they created, and a
    coordinator can hide even those via is_visible_to_client.
    Internal tasks are never shown regardless of that flag.
    """
    return [
        t for t in all_tasks
        if t.get("task_source") == "client_request"
        and t.get("is_visible_to_client", True)
    ]


def render(user):
    client = get_client_by_profile_id(user["id"])
    company = client["company_name"] if client else user.get("full_name", "there")

    st.header(f"👋 Welcome, {company}")

    projects = get_projects_for_client(user["id"])

    if not projects:
        st.info("No projects found for your account.")
        st.caption("Once your account manager sets up a project, it will appear here.")
        return

    # Fetch everything once up front: the summary row and the per-project tabs
    # below both read from these, so nothing is queried twice.
    project_ids = [p["id"] for p in projects]
    raw_tasks = get_tasks_for_projects_bulk(project_ids)
    tasks_by_project = {pid: visible_tasks(tasks) for pid, tasks in raw_tasks.items()}
    raw_proposals = get_proposals_bulk(project_ids)
    proposals_by_project = {pid: visible_proposals(props) for pid, props in raw_proposals.items()}

    all_tasks = [t for tasks in tasks_by_project.values() for t in tasks]
    all_proposals = [pr for props in proposals_by_project.values() for pr in props]

    done_tasks = [t for t in all_tasks if t.get("status") == "done"]
    pending_proposals = [pr for pr in all_proposals if pr.get("status") not in PROPOSAL_DECIDED]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Projects", len(projects))
    col2.metric("Active Requests", len(all_tasks) - len(done_tasks))
    col3.metric("Completed", len(done_tasks))
    col4.metric("Awaiting Your Review", len(pending_proposals))

    if pending_proposals:
        st.info(f"You have {len(pending_proposals)} proposal(s) awaiting your decision. See the Overview tab of each project.")

    st.divider()

    tabs = st.tabs([p["title"] for p in projects])

    for i, tab in enumerate(tabs):
        with tab:
            project = projects[i]
            render_project(
                project,
                tasks_by_project[project["id"]],
                proposals_by_project.get(project["id"], [])
            )


def render_project(project, tasks, proposals):
    col_title, col_status = st.columns([3, 1])
    with col_title:
        st.subheader(project["title"])
    with col_status:
        badge(project["status"], PROJECT_STATUS_COLORS)

    inner_tabs = st.tabs(["Overview", "Tasks"])

    with inner_tabs[0]:
        render_overview(project, tasks, proposals)

    with inner_tabs[1]:
        render_tasks(project, tasks)


def render_overview(project, tasks, proposals):
    st.write("#### Proposals")

    if not proposals:
        st.caption("No proposals have been shared with you for this project yet.")
    else:
        for prop in proposals:
            with st.container(border=True):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**Version {prop['version']}**")
                    st.markdown(f"[📄 View / Download Proposal]({prop['file_url']})")
                with col_b:
                    badge(prop["status"], PROPOSAL_STATUS_COLORS)

                if prop.get("status") not in PROPOSAL_DECIDED:
                    st.write("")
                    st.caption("Review the document, then let us know your decision.")
                    col_accept, col_reject, _ = st.columns([1, 1, 3])
                    with col_accept:
                        if st.button("✅ Accept", key=f"accept_{prop['id']}", type="primary", use_container_width=True):
                            update_proposal_status(prop["id"], PROPOSAL_APPROVED)
                            st.rerun()
                    with col_reject:
                        if st.button("❌ Reject", key=f"reject_{prop['id']}", use_container_width=True):
                            update_proposal_status(prop["id"], PROPOSAL_REJECTED)
                            st.rerun()
                elif prop["status"] == PROPOSAL_APPROVED:
                    st.caption("You accepted this proposal. Your account manager has been notified.")
                else:
                    st.caption("You rejected this proposal. Your account manager will follow up.")

    st.write("")
    st.write("#### Project Summary")

    done_count = len([t for t in tasks if t.get("status") == "done"])
    col1, col2, col3 = st.columns(3)
    col1.metric("Your Requests", len(tasks))
    col2.metric("Completed", done_count)
    col3.metric("Started", project["created_at"][:10])


def render_tasks(project, tasks):
    if tasks:
        done_tasks = len([t for t in tasks if t["status"] == "done"])
        completion = done_tasks / len(tasks)

        st.write("### Progress")
        st.progress(completion)
        st.write(f"{done_tasks} / {len(tasks)} requests completed ({int(completion * 100)}%)")

        st.write("### Your Requests")
        for task in tasks:
            with st.expander(f"{task['title']}"):
                badge(task["status"], TASK_STATUS_COLORS)
                st.write("")
                st.write(f"**Description:** {task['description']}")
                if task.get("deadline"):
                    st.write(f"**Deadline:** {task['deadline']}")
                if task.get("estimated_hours"):
                    st.write(f"**Estimated Hours:** {task['estimated_hours']}")

                if task.get("image_url"):
                    st.markdown(f"**Your Attachment:** [View/Download File]({task['image_url']})")
                if task.get("employee_image_url"):
                    st.markdown(f"**Progress Update:** [View/Download File]({task['employee_image_url']})")
                elif task["status"] != "done":
                    st.caption("No progress update shared yet.")
    else:
        st.info("You have not requested anything for this project yet.")
        st.caption("Use the form below to send your first request to the team.")

    # Form to request new tasks
    st.write("---")
    st.write("### Request New Task")

    if project.get("status") in ["cancelled", "completed"]:
        st.info(f"This project is currently marked as **{project.get('status')}**. You cannot request new tasks for it.")
        return

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
