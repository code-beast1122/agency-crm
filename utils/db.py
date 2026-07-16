import os
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

try:
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SERVICE_ROLE_KEY")
except Exception:
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials. Make sure SUPABASE_URL and SERVICE_ROLE_KEY are set in .env or Streamlit secrets")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------
# CACHING
#
# Streamlit re-executes this whole script on every interaction -- every click,
# tab switch and form submit. Each Supabase call is a separate HTTPS round-trip
# (~400ms), so an uncached portal re-pays its entire query bill every rerun.
#
# Reads below are cached for CACHE_TTL; every write calls _invalidate_reads(),
# so the TTL is only a backstop against changes made outside this process
# (another user's session, or the Supabase dashboard).
# ---------------------------------------------------------------

CACHE_TTL = 60  # seconds


def _invalidate_reads():
    """Drop cached reads after a write so the next render sees fresh data.

    Blunt on purpose: this data set is small, and a stale portal is a much
    worse bug than a few extra queries after a write.
    """
    st.cache_data.clear()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_profile_by_code(login_code: str):
    """Fetch user profile based on unique login code.

    Cached: app.py calls this on every rerun to restore the session from cookie.
    """
    response = supabase.table("profiles").select("*").eq("login_code", login_code).execute()
    if response.data:
        return response.data[0]
    return None

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_user_roles(profile_id: str):
    """Fetch all roles a user holds by checking the role mapping tables.

    One query per role table, but fired concurrently rather than in sequence --
    this runs on every rerun, so five serial round-trips cost ~2.9s of dead time
    before any portal renders. Cached on top of that.
    """
    role_tables = ["admin", "coordinator", "hod", "employee", "client"]

    def holds_role(role):
        return bool(
            supabase.table(role + "s").select("id").eq("profile_id", profile_id).execute().data
        )

    with ThreadPoolExecutor(max_workers=len(role_tables)) as pool:
        held = list(pool.map(holds_role, role_tables))

    return [role for role, has_it in zip(role_tables, held) if has_it]

def sync_profile_role(profile_id: str):
    """Point profiles.role at the role the person actually holds.

    The role tables are the source of truth; profiles.role is a label that has
    to be told. Nothing told it before, so everyone kept the "employee"
    placeholder they were created with.

    Someone holding several roles gets the most senior one, since a single
    column cannot say "coordinator and employee" -- get_user_roles already
    returns them in that order. No roles left means we leave the label alone:
    the column is NOT NULL, and a stale label beats a failed revoke.
    """
    get_user_roles.clear()
    roles = get_user_roles(profile_id)
    if not roles:
        return None

    response = supabase.table("profiles").update({"role": roles[0]}).eq("id", profile_id).execute()
    _invalidate_reads()
    return roles[0]

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_projects_for_client(client_profile_id: str):
    """Fetch projects associated with a specific client's profile ID."""
    # First get the client ID
    client_response = supabase.table("clients").select("id").eq("profile_id", client_profile_id).execute()
    if not client_response.data:
        return []

    client_id = client_response.data[0]["id"]
    projects_response = supabase.table("projects").select("*").eq("client_id", client_id).execute()
    return projects_response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_client_by_profile_id(profile_id: str):
    """Fetch the client record for a profile, or None if they are not a client."""
    response = supabase.table("clients").select("id, company_name").eq("profile_id", profile_id).execute()
    if response.data:
        return response.data[0]
    return None

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_tasks_for_project(project_id: str):
    """Fetch tasks for a specific project."""
    response = supabase.table("tasks").select("*").eq("project_id", project_id).execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_tasks_assigned_to(profile_id: str):
    """Tasks sitting in one person's inbox, whatever their tier."""
    response = supabase.table("tasks").select("*, projects(title)").eq("assigned_to", profile_id).execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_hod_department(profile_id: str):
    """The department an HOD heads, or None if they head none."""
    response = supabase.table("hods").select("department_id, departments(name)").eq("profile_id", profile_id).execute()
    if response.data:
        return response.data[0]
    return None

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_employee_by_profile_id(profile_id: str):
    """The employee record for a profile, or None if they are not an employee."""
    response = supabase.table("employees").select("id, department_id, designation").eq("profile_id", profile_id).execute()
    if response.data:
        return response.data[0]
    return None

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_department_employees(department_id: str):
    """Employees in one department, with their profile names."""
    response = supabase.table("employees").select("id, profile_id, email, designation, profiles(full_name)").eq("department_id", department_id).execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_tasks_for_projects_bulk(project_ids):
    """Tasks for many projects in one query.

    Returns {project_id: [tasks]}, with an empty list for projects that have none.
    Use this instead of calling get_tasks_for_project in a loop.
    """
    grouped = {project_id: [] for project_id in project_ids}
    if not project_ids:
        return grouped

    response = supabase.table("tasks").select("*").in_("project_id", list(project_ids)).execute()
    for task in response.data:
        grouped.setdefault(task["project_id"], []).append(task)

    return grouped

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_proposals_bulk(project_ids):
    """Proposals for many projects in one query, newest version first per project.

    Returns {project_id: [proposals]}, with an empty list for projects that have none.
    """
    grouped = {project_id: [] for project_id in project_ids}
    if not project_ids:
        return grouped

    response = supabase.table("proposals") \
        .select("*") \
        .in_("project_id", list(project_ids)) \
        .order("version", desc=True) \
        .execute()

    for prop in response.data:
        grouped.setdefault(prop["project_id"], []).append(prop)

    return grouped

def update_proposal_status(proposal_id: str, status: str):
    """Update a proposal's status (e.g. the client accepting or rejecting it)."""
    response = supabase.table("proposals").update({"status": status}).eq("id", proposal_id).execute()
    _invalidate_reads()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_employees():
    """Fetch all employee profiles with their employee record."""
    response = supabase.table("employees").select("id, profile_id, department_id, designation, profiles(full_name), email").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_coordinators():
    """Fetch all coordinators."""
    response = supabase.table("coordinators").select("id, profile_id, profiles(full_name), email").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_hods():
    """Fetch all HODs."""
    response = supabase.table("hods").select("id, profile_id, department_id, profiles(full_name), email").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_hods_with_departments():
    """All HODs with the name of the department they head."""
    response = supabase.table("hods").select("id, profile_id, profiles(full_name), departments(name)").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_projects():
    """Fetch all projects (for manager)."""
    response = supabase.table("projects").select("*, clients(company_name)").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_clients():
    """Fetch all clients (for manager)."""
    response = supabase.table("clients").select("id, company_name, profile_id, profiles(full_name)").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_tasks():
    """Fetch all tasks (for manager/dispatcher)."""
    response = supabase.table("tasks").select("*, projects(title), profiles!tasks_assigned_to_fkey(full_name)").execute()
    return response.data

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_role_counts():
    """Counts for the admin KPI row, fired concurrently instead of one by one."""
    tables = ["admins", "coordinators", "hods", "employees", "projects", "clients"]

    def count_rows(table):
        return supabase.table(table).select("id", count="exact").execute().count or 0

    with ThreadPoolExecutor(max_workers=len(tables)) as pool:
        counts = list(pool.map(count_rows, tables))

    return dict(zip(tables, counts))

# ---------------------------------------------------------------
# TASK HIERARCHY: Coordinator -> HOD -> Employee
#
# A task carries no level of its own; its level is implied by who it is
# assigned to. These helpers derive that, so each portal sees only its own
# tier: the coordinator tracks the HOD, and the HOD tracks the employee.
# ---------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_hod_profile_ids():
    """Profile IDs of everyone holding the HOD role."""
    response = supabase.table("hods").select("profile_id").execute()
    return {h["profile_id"] for h in response.data}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_department_employee_profile_ids(department_id: str):
    """Profile IDs of the employees in one department."""
    response = supabase.table("employees").select("profile_id").eq("department_id", department_id).execute()
    return {e["profile_id"] for e in response.data}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_coordinator_level_tasks():
    """Tasks the coordinator is responsible for: unassigned, or sitting with an HOD.

    Work an HOD has dispatched down to their own employees belongs to that
    HOD's team view, not here.
    """
    hod_ids = get_hod_profile_ids()
    return [
        t for t in get_all_tasks()
        if not t.get("assigned_to") or t["assigned_to"] in hod_ids
    ]

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_team_tasks(department_id: str):
    """Tasks dispatched to the employees of one department, newest first."""
    emp_ids = get_department_employee_profile_ids(department_id)
    if not emp_ids:
        return []

    response = supabase.table("tasks") \
        .select("*, projects(title), profiles!tasks_assigned_to_fkey(full_name)") \
        .in_("assigned_to", list(emp_ids)) \
        .order("created_at", desc=True) \
        .execute()
    return response.data

def update_task(task_id: str, updates: dict):
    """Update a specific task."""
    response = supabase.table("tasks").update(updates).eq("id", task_id).execute()
    _invalidate_reads()
    return response.data

def create_client_record(profile_id: str, company_name: str, email: str = None):
    """Create a client record."""
    payload = {
        "profile_id": profile_id,
        "company_name": company_name
    }
    if email:
        payload["email"] = email
    response = supabase.table("clients").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def create_employee_record(profile_id: str, department_id: str, designation: str, email: str = None):
    """Create an employee record."""
    payload = {
        "profile_id": profile_id,
        "department_id": department_id,
        "designation": designation
    }
    if email:
        payload["email"] = email

    response = supabase.table("employees").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def create_project(client_id: str, title: str):
    """Create a project."""
    response = supabase.table("projects").insert({
        "client_id": client_id,
        "title": title
    }).execute()
    _invalidate_reads()
    return response.data[0]

def create_coordinator_record(profile_id: str, email: str = None):
    """Create a coordinator record."""
    payload = {"profile_id": profile_id}
    if email:
        payload["email"] = email
    response = supabase.table("coordinators").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def create_hod_record(profile_id: str, department_id: str, email: str = None):
    """Create a HOD record."""
    payload = {
        "profile_id": profile_id,
        "department_id": department_id
    }
    if email:
        payload["email"] = email
    response = supabase.table("hods").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def update_project(project_id: str, updates: dict):
    """Update a specific project."""
    response = supabase.table("projects").update(updates).eq("id", project_id).execute()
    _invalidate_reads()
    return response.data

def create_proposal(project_id: str, file_url: str):
    """Create a proposal."""
    response = supabase.table("proposals").insert({
        "project_id": project_id,
        "file_url": file_url
    }).execute()
    _invalidate_reads()
    return response.data[0]

def create_profile(full_name: str, role: str, login_code: str = None):
    """Create a profile."""
    payload = {
        "full_name": full_name,
        "role": role,
    }
    if login_code:
        payload["login_code"] = login_code

    response = supabase.table("profiles").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def create_task(project_id: str, title: str, description: str, source: str = "internal", deadline: str = None, image_url: str = None, estimated_hours: float = 0.0, task_type: str = "one-off", assigned_to: str = None, assignee_email: str = None):
    """Create a task."""
    payload = {
        "project_id": project_id,
        "title": title,
        "description": description,
        "task_source": source,
        "estimated_hours": estimated_hours,
        "task_type": task_type
    }
    if deadline:
        payload["deadline"] = deadline
    if image_url:
        payload["image_url"] = image_url
    if assigned_to:
        payload["assigned_to"] = assigned_to
        
    response = supabase.table("tasks").insert(payload).execute()
    _invalidate_reads()

    target = get_calendar_target(assigned_to) or {}
    _sync_task_integrations(
        project_id, title, deadline,
        assignee_email or target.get("email"),
        assignee_name=_assignee_name(assigned_to),
        calendar_id=target.get("calendar_id"),
    )

    return response.data[0]

def _assignee_name(profile_id: str):
    """Full name for a profile id, or None. Never raises -- this only decorates
    a calendar event and must not fail task creation."""
    if not profile_id:
        return None
    try:
        res = supabase.table("profiles").select("full_name").eq("id", profile_id).execute()
        return res.data[0]["full_name"] if res.data else None
    except Exception:
        return None


ROLE_TABLES_WITH_CALENDARS = ("employees", "hods", "coordinators")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_calendar_target(profile_id: str):
    """Where this person's deadlines go: {"calendar_id", "email"} or None.

    One person may hold several roles; any of them carries the same human, so
    the first calendar found is theirs.
    """
    if not profile_id:
        return None
    for table in ROLE_TABLES_WITH_CALENDARS:
        try:
            res = supabase.table(table).select("calendar_id, email").eq("profile_id", profile_id).execute()
        except Exception:
            continue  # calendar_id column not added yet
        for row in res.data:
            if row.get("calendar_id"):
                return {"calendar_id": row["calendar_id"], "email": row.get("email")}
    return None


def provision_calendar(profile_id: str, full_name: str, email: str, table: str):
    """Give one person their own deadline calendar and email them the invite.

    Idempotent: someone who already has a calendar keeps it, so re-saving a
    role does not spam them with invites or strand their existing events.
    """
    try:
        existing = supabase.table(table).select("id, calendar_id").eq("profile_id", profile_id).execute().data
    except Exception:
        return {
            "status": "error",
            "message": "The calendar_id column is missing. Run this once in the Supabase "
                       "SQL editor: alter table coordinators add column if not exists "
                       "calendar_id text; alter table hods add column if not exists "
                       "calendar_id text; alter table employees add column if not exists "
                       "calendar_id text;",
        }
    if not existing:
        return {"status": "error", "message": f"No {table} record for this profile."}
    if existing[0].get("calendar_id"):
        return {"status": "success", "message": "Calendar already set up for this user.",
                "calendar_id": existing[0]["calendar_id"]}

    from utils.api_integrations import provision_user_calendar
    result = provision_user_calendar(full_name, email)
    if result.get("status") != "success":
        return result

    supabase.table(table).update({"calendar_id": result["calendar_id"]}) \
        .eq("profile_id", profile_id).execute()
    _invalidate_reads()
    return result


def sync_task_deadline(task_id: str):
    """Put a task's deadline on the shared calendar for whoever now owns it.

    Task creation already syncs, but assignment happens later via update_task
    (coordinator -> HOD), which is how those deadlines used to reach nobody.
    """
    try:
        res = supabase.table("tasks").select("title, deadline, assigned_to").eq("id", task_id).execute()
        if not res.data:
            return
        task = res.data[0]
        if not task.get("deadline"):
            return

        target = get_calendar_target(task.get("assigned_to")) or {}
        from utils.api_integrations import create_calendar_event
        result = create_calendar_event(
            task["title"],
            task["deadline"],
            assignee_email=target.get("email"),
            assignee_name=_assignee_name(task.get("assigned_to")),
            calendar_id=target.get("calendar_id"),
        )
        if result and result.get("status") != "success":
            st.warning(f"Google Calendar: {result.get('message', 'sync failed')}")
    except Exception as e:
        st.warning(f"Google Calendar sync failed: {str(e)}")


def _sync_task_integrations(project_id: str, title: str, deadline: str = None, assignee_email: str = None, timeout: int = 20, assignee_name: str = None, calendar_id: str = None):
    """Push a newly created task to Clockify and Google Calendar.

    Both calls run concurrently. A sync failure must never fail task creation --
    the task is already committed -- but it must not vanish silently either, so
    each result is checked and reported.
    """
    try:
        from utils.api_integrations import sync_task_to_clockify, create_calendar_event

        jobs = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            proj_res = supabase.table("projects").select("title").eq("id", project_id).execute()
            if proj_res.data:
                jobs["Clockify"] = pool.submit(sync_task_to_clockify, title, proj_res.data[0]["title"])
            if deadline:
                jobs["Google Calendar"] = pool.submit(
                    create_calendar_event, title, deadline, assignee_email,
                    assignee_name, calendar_id
                )

            for name, future in jobs.items():
                try:
                    res = future.result(timeout=timeout)
                    if res and res.get("status") != "success":
                        st.warning(f"{name}: {res.get('message', 'sync failed')}")
                except Exception as e:
                    st.warning(f"{name} sync failed: {str(e)}")
    except Exception as e:
        st.warning(f"Task created, but integration sync failed: {str(e)}")

def start_task_timer(task_id: str, employee_id: str):
    """Start a timer for a task."""
    response = supabase.table("time_logs").insert({
        "task_id": task_id,
        "employee_id": employee_id
    }).execute()
    _invalidate_reads()
    return response.data[0] if response.data else None

def stop_task_timer(time_log_id: str):
    """Stop a timer by ID."""
    now = datetime.now(timezone.utc).isoformat()
    response = supabase.table("time_logs").update({"end_time": now}).eq("id", time_log_id).execute()
    _invalidate_reads()
    return response.data[0] if response.data else None

def get_active_timer(task_id: str, employee_id: str):
    """Get active timer for an employee on a task."""
    response = supabase.table("time_logs").select("*").eq("task_id", task_id).eq("employee_id", employee_id).is_("end_time", "null").execute()
    if response.data:
        return response.data[0]
    return None

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_active_timers_bulk(task_ids, employee_id: str):
    """The employee's open timer per task, for many tasks in one query.

    Returns {task_id: timer_row}, omitting tasks with no running timer.
    Use this instead of calling get_active_timer once per rendered task.
    """
    if not task_ids or not employee_id:
        return {}

    response = supabase.table("time_logs").select("*") \
        .in_("task_id", list(task_ids)) \
        .eq("employee_id", employee_id) \
        .is_("end_time", "null") \
        .execute()

    return {log["task_id"]: log for log in response.data}

def _sum_log_hours(logs):
    """Sum closed time_log rows into hours, skipping any with unparseable dates."""
    total_hours = 0.0
    for log in logs:
        try:
            start = datetime.fromisoformat(log["start_time"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(log["end_time"].replace("Z", "+00:00"))
            total_hours += (end - start).total_seconds() / 3600.0
        except Exception:
            pass # Skip invalid dates
    return total_hours

def get_total_time_logged(task_id: str):
    """Calculate total duration logged for a task in hours."""
    response = supabase.table("time_logs").select("*").eq("task_id", task_id).not_.is_("end_time", "null").execute()
    return _sum_log_hours(response.data)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_total_time_logged_bulk(task_ids):
    """Total hours logged per task, for many tasks in one query.

    Use this instead of get_total_time_logged when rendering a list of tasks.
    Returns {task_id: hours}, with 0.0 for tasks that have no closed logs.
    """
    totals = {task_id: 0.0 for task_id in task_ids}
    if not task_ids:
        return totals

    response = supabase.table("time_logs").select("*").in_("task_id", list(task_ids)).not_.is_("end_time", "null").execute()

    logs_by_task = {}
    for log in response.data:
        logs_by_task.setdefault(log["task_id"], []).append(log)

    for task_id, logs in logs_by_task.items():
        totals[task_id] = _sum_log_hours(logs)

    return totals
