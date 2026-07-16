import os
import requests
import streamlit as st
from datetime import datetime

# Every outbound call MUST be bounded. These run inside a ThreadPoolExecutor
# whose shutdown waits on its workers, so an unbounded request does not just
# slow a sync down -- it hangs task creation for as long as the socket stays
# open. (connect, read) seconds.
HTTP_TIMEOUT = (5, 15)

# ==========================================
# CLOCKIFY API INTEGRATION
# ==========================================
def sync_task_to_clockify(task_title: str, project_name: str):
    """
    Creates a task in the specified Clockify project.

    Idempotent: a task that is already in the project is left alone and
    reported as success, so re-syncing the same title is not an error.
    """
    clockify_api_key = os.environ.get("CLOCKIFY_API_KEY")
    workspace_id = os.environ.get("CLOCKIFY_WORKSPACE_ID")

    if not clockify_api_key or not workspace_id:
        return {"status": "error", "message": "Clockify credentials missing in .env"}

    headers = {
        "X-Api-Key": clockify_api_key,
        "Content-Type": "application/json"
    }

    base_url = f"https://api.clockify.me/api/v1/workspaces/{workspace_id}"

    try:
        # 1. Fetch projects to see if the project exists
        res_projects = requests.get(f"{base_url}/projects", headers=headers, timeout=HTTP_TIMEOUT)
        res_projects.raise_for_status()
        projects = res_projects.json()

        target_project_id = None
        for p in projects:
            if p.get("name") == project_name:
                target_project_id = p.get("id")
                break

        # 2. If project doesn't exist, create it
        if not target_project_id:
            res_create_proj = requests.post(
                f"{base_url}/projects",
                headers=headers,
                json={"name": project_name},
                timeout=HTTP_TIMEOUT
            )
            res_create_proj.raise_for_status()
            target_project_id = res_create_proj.json().get("id")
        else:
            # Clockify rejects a duplicate task name with a 400. Two tasks can
            # legitimately share a title in this CRM, so treat an existing task
            # as done rather than showing the user an API error.
            res_tasks = requests.get(
                f"{base_url}/projects/{target_project_id}/tasks",
                headers=headers,
                timeout=HTTP_TIMEOUT
            )
            res_tasks.raise_for_status()
            if any(t.get("name") == task_title for t in res_tasks.json()):
                return {
                    "status": "success",
                    "message": f"Task '{task_title}' already in Clockify."
                }

        # 3. Create the task in the project
        res_create_task = requests.post(
            f"{base_url}/projects/{target_project_id}/tasks",
            headers=headers,
            json={"name": task_title},
            timeout=HTTP_TIMEOUT
        )
        res_create_task.raise_for_status()

        return {"status": "success", "message": f"Task '{task_title}' synced to Clockify."}

    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Clockify API Error: {str(e)}"}

# ==========================================
# GOOGLE CALENDAR API INTEGRATION
# ==========================================
# Creating and sharing calendars needs the full scope, not just .events.
CALENDAR_SCOPES = ['https://www.googleapis.com/auth/calendar']

# Fire the reminder the morning the deadline lands (all-day events count
# minutes back from midnight, so 540 = 9am).
REMINDER_MINUTES = 540


def _calendar_service():
    """Build a timeout-bounded Calendar client, or (None, error_dict)."""
    try:
        import httplib2
        import google_auth_httplib2
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None, {"status": "error", "message": "Google libraries not installed."}

    if not os.path.exists("credentials.json"):
        return None, {"status": "error", "message": "credentials.json not found in project root."}

    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=CALENDAR_SCOPES)
        # googleapiclient has no timeout by default. Same reasoning as
        # HTTP_TIMEOUT above: an unbounded call here hangs task creation.
        authed_http = google_auth_httplib2.AuthorizedHttp(
            creds, http=httplib2.Http(timeout=sum(HTTP_TIMEOUT))
        )
        return build('calendar', 'v3', http=authed_http, cache_discovery=False), None
    except Exception as e:
        return None, {"status": "error", "message": f"Google Calendar auth error: {str(e)}"}


def provision_user_calendar(full_name: str, email: str):
    """Create a private calendar for one person and share it with them.

    Sharing is what actually emails them the invite. Each person gets their own
    calendar so they are reminded of their OWN deadlines only -- a service
    account cannot invite attendees to a shared calendar without Domain-Wide
    Delegation, which needs Google Workspace.

    Returns {"status": "success", "calendar_id": ...} or an error dict.
    """
    if not email:
        return {"status": "error", "message": "No email on file, cannot send a calendar invite."}

    service, err = _calendar_service()
    if err:
        return err

    try:
        calendar = service.calendars().insert(body={
            "summary": f"CRM Deadlines — {full_name}",
            "description": "Your task deadlines from the ClixoSoft CRM.",
        }).execute()
        calendar_id = calendar["id"]

        # sendNotifications=True is the invite email.
        service.acl().insert(
            calendarId=calendar_id,
            sendNotifications=True,
            body={"role": "reader", "scope": {"type": "user", "value": email}},
        ).execute()

        return {
            "status": "success",
            "calendar_id": calendar_id,
            "message": f"Calendar invite sent to {email}.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Google Calendar API Error: {str(e)}"}


def create_calendar_event(task_title: str, deadline_date: str, assignee_email: str = None,
                          assignee_name: str = None, calendar_id: str = None):
    """
    Creates an all-day deadline event on the assignee's own calendar.

    calendar_id is the assignee's personal CRM calendar (see
    provision_user_calendar). Without one there is nowhere meaningful to write:
    the service account's "primary" is its own calendar, which no human can see,
    so this refuses rather than silently black-holing the deadline.
    """
    calendar_id = calendar_id or os.environ.get("GOOGLE_CALENDAR_ID")
    if not calendar_id:
        return {
            "status": "error",
            "message": "No calendar for this assignee -- add their email in the "
                       "portal so they get a calendar invite, then re-save the task.",
        }

    service, err = _calendar_service()
    if err:
        return err

    try:
        summary = f"Deadline: {task_title}"
        if assignee_name:
            summary += f" — {assignee_name}"

        details = []
        if assignee_name:
            details.append(f"Assigned to: {assignee_name}")
        if assignee_email:
            details.append(f"Contact: {assignee_email}")

        event = {
            'summary': summary,
            'description': "\n".join(details) or None,
            'start': {'date': deadline_date},
            'end': {'date': deadline_date},
            'reminders': {
                'useDefault': False,
                'overrides': [{'method': 'popup', 'minutes': REMINDER_MINUTES}],
            },
        }

        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()

        return {"status": "success", "message": f"Deadline added: {created_event.get('htmlLink')}"}
    except Exception as e:
        return {"status": "error", "message": f"Google Calendar API Error: {str(e)}"}
