"""Staff-side meetings: schedule, record, summarize, and decide what the client sees.

Shared by the admin and coordinator portals -- both need exactly this screen,
so it lives here once rather than twice.

The join link is pasted, not generated. The CRM's Google service account has no
Domain-Wide Delegation, so it cannot host a Meet; a conference it created would
have no host and leave the client stuck in a waiting room. Whoever creates the
call in their own account stays the host, and the client joins from their
portal rather than a calendar invite.
"""
from datetime import datetime, time

import streamlit as st

from utils.ai_summary import AUDIO_TYPES, summarize_meeting, transcribe_recording
from utils.api_integrations import create_meeting_event
from utils.db import (
    MEETING_CANCELLED,
    MEETING_COMPLETED,
    MEETING_SCHEDULED,
    create_meeting,
    get_all_projects,
    get_calendar_target,
    get_hods_with_departments,
    get_meeting_hod_ids,
    get_meetings_bulk,
    set_meeting_hods,
    update_meeting
)

MEETING_STATUSES = [MEETING_SCHEDULED, MEETING_COMPLETED, MEETING_CANCELLED]

# Shared with every portal that shows a meeting's status as a badge (client, HOD).
MEETING_STATUS_COLORS = {
    MEETING_SCHEDULED: ("#0ea5e9", "rgba(14, 165, 233, 0.15)"),
    MEETING_COMPLETED: ("#22c55e", "rgba(34, 197, 94, 0.15)"),
    MEETING_CANCELLED: ("#ef4444", "rgba(239, 68, 68, 0.15)"),
}


def meeting_time(meeting):
    """Parse scheduled_at, or None if it is unreadable.

    Postgres hands back timestamptz with an offset, so the result is usually
    timezone-aware -- never compare it to a naive now(). Returns None rather
    than raising: a meeting with an odd timestamp should still render.

    Shared by every portal that shows meetings (client, HOD) so "what counts as
    upcoming" is defined in exactly one place.
    """
    raw = meeting.get("scheduled_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_upcoming(meeting):
    """Is this meeting still ahead of us and not cancelled?"""
    if meeting.get("status") == "cancelled":
        return False
    when = meeting_time(meeting)
    if when is None:
        return False
    now = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
    return when >= now


def _hod_label_map():
    """profile_id -> "Name (Department)", for the multiselect and for display."""
    hods = get_hods_with_departments()
    return {
        h["profile_id"]: "{} ({})".format(h["profiles"]["full_name"], h["departments"]["name"])
        for h in hods
        if h.get("profiles") and h.get("departments")
    }


def render_meetings(user):
    st.markdown("### Client Meetings")

    projects = get_all_projects()
    if not projects:
        st.info("No projects yet. A meeting is scheduled against a project, so create one first.")
        return

    project_label = {
        p["id"]: f"{p['title']} — {(p.get('clients') or {}).get('company_name', 'No client')}"
        for p in projects
    }
    hod_label = _hod_label_map()

    render_schedule_form(user, projects, project_label, hod_label)

    st.write("---")
    st.markdown("### Scheduled & Past Meetings")

    meetings_by_project = get_meetings_bulk([p["id"] for p in projects])
    all_meetings = [m for meetings in meetings_by_project.values() for m in meetings]

    if not all_meetings:
        st.info("No meetings yet. Use the form above to schedule the first one.")
        return

    # get_meetings_bulk sorts within a project; this list spans projects.
    all_meetings.sort(key=lambda m: m["scheduled_at"], reverse=True)

    for meeting in all_meetings:
        render_meeting(meeting, project_label, hod_label)


def render_schedule_form(user, projects, project_label, hod_label):
    with st.form("schedule_meeting_form"):
        st.markdown("#### Schedule a Meeting")
        st.caption(
            "Create the Google Meet or Zoom call in your own account, then paste the link here. "
            "You stay the host, and the client joins from their portal."
        )

        col1, col2 = st.columns(2)
        with col1:
            project_id = st.selectbox(
                "Project",
                options=[p["id"] for p in projects],
                format_func=lambda pid: project_label[pid]
            )
            title = st.text_input("Meeting Title")
            agenda = st.text_area("Agenda (Optional)")
        with col2:
            meet_date = st.date_input("Date")
            meet_time = st.time_input("Time", value=time(10, 0))
            duration = st.number_input("Duration (minutes)", min_value=15, step=15, value=30)
            join_url = st.text_input("Join Link (Meet / Zoom)")

        show_to_client = st.checkbox(
            "Show this meeting to the client",
            value=False,
            help="Off by default. When on, the client sees it in their portal with a Join button."
        )

        selected_hods = []
        if hod_label:
            selected_hods = st.multiselect(
                "Notify HODs (optional)",
                options=list(hod_label.keys()),
                format_func=lambda pid: hod_label[pid],
                help="Tagged HODs see this meeting on their own portal, with the agenda and join link."
            )
        else:
            st.caption("No HODs yet — assign the HOD role under Team Management to be able to notify one.")

        if st.form_submit_button("Schedule Meeting"):
            if not title:
                st.error("Meeting title is required.")
            elif show_to_client and not join_url:
                st.error("Add the join link before showing this meeting to the client — they would have no way in.")
            else:
                scheduled_at = datetime.combine(meet_date, meet_time).isoformat()
                meeting = create_meeting(
                    project_id=project_id,
                    title=title,
                    scheduled_at=scheduled_at,
                    agenda=agenda or None,
                    duration_minutes=int(duration),
                    join_url=join_url or None,
                    created_by=user["id"],
                    show_meeting_to_client=show_to_client
                )
                if selected_hods:
                    set_meeting_hods(meeting["id"], selected_hods)
                st.success("Meeting scheduled!")
                sync_to_organiser_calendar(user, title, scheduled_at, int(duration), agenda, join_url)
                st.rerun()


def sync_to_organiser_calendar(user, title, scheduled_at, duration, agenda, join_url):
    """Best-effort reminder on the organiser's own CRM calendar.

    Never raises: the meeting is already saved by this point, and a calendar
    hiccup must not read as the scheduling having failed.
    """
    target = get_calendar_target(user["id"])
    if not target:
        st.caption("No calendar on file for you, so no reminder was added.")
        return

    result = create_meeting_event(
        title, scheduled_at, duration,
        calendar_id=target.get("calendar_id"), agenda=agenda, join_url=join_url
    )
    if result.get("status") == "success":
        st.caption("Added to your calendar with a 15-minute reminder.")
    else:
        st.caption(f"Meeting saved, but the calendar reminder failed: {result.get('message')}")


def render_meeting(meeting, project_label, hod_label):
    when = str(meeting["scheduled_at"]).replace("T", " ")[:16]
    shared = "shared" if meeting.get("show_meeting_to_client") else "internal"
    header = f"{when} — {meeting['title']} ({meeting['status']}, {shared})"

    with st.expander(header):
        st.caption(project_label.get(meeting["project_id"], "Unknown project"))
        if meeting.get("agenda"):
            st.write(f"**Agenda:** {meeting['agenda']}")
        if meeting.get("join_url"):
            st.markdown(f"**Join link:** {meeting['join_url']}")
        else:
            st.caption("No join link on this meeting yet.")

        tagged_ids = get_meeting_hod_ids(meeting["id"])
        if tagged_ids:
            names = [hod_label[pid] for pid in tagged_ids if pid in hod_label]
            st.caption("Notified HODs: " + ", ".join(names) if names else "Notified HODs: (removed from the system)")

        st.write("---")
        render_summary_tools(meeting)
        st.write("---")
        render_meeting_form(meeting, hod_label, tagged_ids)


def render_summary_tools(meeting):
    """Notes/recording in, structured summary out.

    Kept outside the form below because a file uploader inside an st.form
    cannot trigger the work until submit, and this needs its own spinner.
    """
    st.markdown("**AI Summary**")

    notes = st.text_area(
        "Rough notes",
        value=meeting.get("raw_notes") or "",
        key=f"notes_{meeting['id']}",
        height=120,
        placeholder="Jot down what was said — messy bullets are fine, the model cleans them up."
    )
    recording = st.file_uploader(
        "Recording (optional)",
        type=AUDIO_TYPES,
        key=f"audio_{meeting['id']}",
        help="If you recorded the call, upload it and the summary is built from what was actually said. Max 25MB."
    )

    if st.button("Generate Summary", key=f"gen_{meeting['id']}"):
        if not notes.strip() and not recording:
            st.error("Add some notes or a recording first.")
            return

        updates = {"raw_notes": notes or None}
        transcript = meeting.get("transcript")

        if recording:
            with st.spinner("Transcribing the recording..."):
                result = transcribe_recording(recording.getvalue(), recording.name)
            if result["status"] != "success":
                st.error(result["message"])
                return
            transcript = result["transcript"]
            updates["transcript"] = transcript

        with st.spinner("Writing the summary..."):
            result = summarize_meeting(raw_notes=notes, transcript=transcript)
        if result["status"] != "success":
            st.error(result["message"])
            return

        updates["summary"] = result["summary"]
        update_meeting(meeting["id"], updates)
        st.success("Summary generated. Read it over and edit anything wrong before sharing it.")
        st.rerun()

    if meeting.get("transcript"):
        with st.expander("View transcript"):
            st.write(meeting["transcript"])


def render_meeting_form(meeting, hod_label, tagged_ids):
    with st.form(f"meeting_form_{meeting['id']}"):
        col1, col2 = st.columns(2)
        with col1:
            status = st.selectbox(
                "Status",
                MEETING_STATUSES,
                index=MEETING_STATUSES.index(meeting["status"])
                if meeting["status"] in MEETING_STATUSES else 0,
                key=f"status_{meeting['id']}"
            )
            join_url = st.text_input(
                "Join Link", value=meeting.get("join_url") or "", key=f"url_{meeting['id']}"
            )
        with col2:
            show_meeting = st.checkbox(
                "Show meeting to client",
                value=bool(meeting.get("show_meeting_to_client")),
                key=f"showmeet_{meeting['id']}"
            )
            show_summary = st.checkbox(
                "Show summary to client",
                value=bool(meeting.get("show_summary_to_client")),
                key=f"showsum_{meeting['id']}",
                help="Separate from the toggle above: you can invite the client to the call and still keep the notes internal."
            )

        if hod_label:
            selected_hods = st.multiselect(
                "Notify HODs",
                options=list(hod_label.keys()),
                default=[pid for pid in tagged_ids if pid in hod_label],
                format_func=lambda pid: hod_label[pid],
                key=f"hods_{meeting['id']}",
                help="Tagged HODs see this meeting on their own portal, with the agenda and join link."
            )
        else:
            selected_hods = []

        # The summary is a draft until a human signs off on it -- an LLM writing
        # a record the client may read has to stay editable.
        summary = st.text_area(
            "Summary (editable)",
            value=meeting.get("summary") or "",
            key=f"sum_{meeting['id']}",
            height=200
        )

        if st.form_submit_button("Save Changes", key=f"save_{meeting['id']}"):
            if show_summary and not summary.strip():
                st.error("There is no summary to show the client yet.")
            elif show_meeting and not join_url.strip():
                st.error("Add the join link before showing this meeting to the client — they would have no way in.")
            else:
                update_meeting(meeting["id"], {
                    "status": status,
                    "join_url": join_url or None,
                    "show_meeting_to_client": show_meeting,
                    "show_summary_to_client": show_summary,
                    "summary": summary or None,
                })
                if hod_label:
                    set_meeting_hods(meeting["id"], selected_hods)
                st.success("Saved!")
                st.rerun()
