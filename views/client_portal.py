import streamlit as st
import pandas as pd

from utils.db import (
    get_client_by_profile_id,
    get_projects_for_client,
    get_tasks_for_projects_bulk,
    get_proposals_bulk,
    get_meetings_bulk,
    normalize_join_url,
    update_proposal_status,
    create_task,
    supabase
)
from utils.theme import badge, empty_state, page_header, section
from views.meetings import MEETING_STATUS_COLORS, is_upcoming, meeting_time

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


def visible_meetings(meetings):
    """Meetings staff have explicitly shared.

    Unlike visible_tasks, this flag is the ONLY gate -- there is no task_source
    equivalent narrowing the set first, so this one condition is the whole
    difference between an internal meeting and a client-facing one. It is
    deliberately fail-CLOSED: anything but a true value stays hidden.
    """
    return [m for m in meetings if m.get("show_meeting_to_client") is True]


def render(user):
    client = get_client_by_profile_id(user["id"])
    company = client["company_name"] if client else user.get("full_name", "there")

    page_header(f"Welcome, {company}", "Your projects, requests and meetings")

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
    raw_meetings = get_meetings_bulk(project_ids)
    meetings_by_project = {pid: visible_meetings(ms) for pid, ms in raw_meetings.items()}

    all_tasks = [t for tasks in tasks_by_project.values() for t in tasks]
    all_proposals = [pr for props in proposals_by_project.values() for pr in props]
    all_meetings = [m for ms in meetings_by_project.values() for m in ms]

    done_tasks = [t for t in all_tasks if t.get("status") == "done"]
    pending_proposals = [pr for pr in all_proposals if pr.get("status") not in PROPOSAL_DECIDED]
    upcoming = [m for m in all_meetings if is_upcoming(m)]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Projects", len(projects))
    col2.metric("Active Requests", len(all_tasks) - len(done_tasks))
    col3.metric("Completed", len(done_tasks))
    col4.metric("Awaiting Your Review", len(pending_proposals))
    col5.metric("Upcoming Meetings", len(upcoming))

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
                proposals_by_project.get(project["id"], []),
                meetings_by_project.get(project["id"], [])
            )


def render_project(project, tasks, proposals, meetings):
    col_title, col_status = st.columns([3, 1])
    with col_title:
        st.subheader(project["title"])
    with col_status:
        badge(project["status"], PROJECT_STATUS_COLORS)

    # Progress belongs at the top of the project, not buried in the Tasks tab:
    # "how far along are we" is the question a client opens this page to ask.
    if tasks:
        done = len([t for t in tasks if t.get("status") == "done"])
        st.progress(done / len(tasks))
        st.caption(f"{done} of {len(tasks)} requests completed ({int(done / len(tasks) * 100)}%)")

    inner_tabs = st.tabs(["Overview", "Tasks", "Meetings"])

    with inner_tabs[0]:
        render_overview(project, tasks, proposals)

    with inner_tabs[1]:
        render_tasks(project, tasks)

    with inner_tabs[2]:
        render_meetings(project, meetings)


def render_meetings(project, meetings):
    """Meetings staff have shared with this client.

    Everything here has already passed visible_meetings; the only extra gate is
    show_summary_to_client, which is separate on purpose -- the client can be
    invited to the call without seeing the notes taken about it.
    """
    if not meetings:
        empty_state(
            "No meetings scheduled yet",
            "When your account manager schedules one, it appears here with a join link."
        )
        return

    upcoming = [m for m in meetings if is_upcoming(m)]
    past = [m for m in meetings if not is_upcoming(m)]

    if upcoming:
        section("Upcoming", f"{len(upcoming)} scheduled")
        for meeting in upcoming:
            render_meeting_card(meeting, joinable=True)

    if past:
        section("Past Meetings", f"{len(past)} held")
        for meeting in past:
            render_meeting_card(meeting, joinable=False)


def render_meeting_card(meeting, joinable):
    with st.container(border=True):
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown(f"**{meeting['title']}**")
            when = meeting_time(meeting)
            if when:
                st.caption(when.strftime("%d %b %Y at %H:%M") + f" · {meeting.get('duration_minutes', 30)} min")
        with col_b:
            badge(meeting["status"], MEETING_STATUS_COLORS)

        if meeting.get("agenda"):
            st.write(meeting["agenda"])

        # Normalized again at render: rows saved before the write path did this
        # still hold scheme-less links, which resolve against the CRM's domain.
        join_url = normalize_join_url(meeting.get("join_url"))
        if joinable and join_url:
            st.link_button("Join Meeting", join_url, type="primary")

        if meeting.get("show_summary_to_client") and meeting.get("summary"):
            with st.expander("Meeting Summary"):
                st.markdown(meeting["summary"])


def render_overview(project, tasks, proposals):
    section("Proposals", "Documents shared with you for review")

    if not proposals:
        empty_state(
            "No proposals shared yet",
            "When your account manager sends one, you can accept or reject it here."
        )
    else:
        for prop in proposals:
            with st.container(border=True):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**Version {prop['version']}**")
                    st.markdown(f"[View / Download Proposal]({prop['file_url']})")
                with col_b:
                    badge(prop["status"], PROPOSAL_STATUS_COLORS)

                if prop.get("status") not in PROPOSAL_DECIDED:
                    st.write("")
                    st.caption("Review the document, then let us know your decision.")
                    col_accept, col_reject, _ = st.columns([1, 1, 3])
                    with col_accept:
                        if st.button("Accept", key=f"accept_{prop['id']}", type="primary", width="stretch"):
                            update_proposal_status(prop["id"], PROPOSAL_APPROVED)
                            st.rerun()
                    with col_reject:
                        if st.button("Reject", key=f"reject_{prop['id']}", width="stretch"):
                            update_proposal_status(prop["id"], PROPOSAL_REJECTED)
                            st.rerun()
                elif prop["status"] == PROPOSAL_APPROVED:
                    st.caption("You accepted this proposal. Your account manager has been notified.")
                else:
                    st.caption("You rejected this proposal. Your account manager will follow up.")

    st.write("")
    section("Project Summary")

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
