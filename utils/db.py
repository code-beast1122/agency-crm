import os
import re
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone
import threading
from concurrent.futures import ThreadPoolExecutor

from utils.auth import generate_password, generate_session_token, passwords_match

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
# CONCURRENT READS
#
# A Supabase client is NOT safe to share across threads. postgrest hardcodes
# http2=True, so one client means one HTTP/2 connection, and httpcore encodes
# request headers (mutating the shared HPACK dynamic table) outside its write
# lock. Two threads encoding at once corrupt that table and the server kills the
# connection: RemoteProtocolError ConnectionTerminated, error_code 9
# (COMPRESSION_ERROR) or 1 (PROTOCOL_ERROR). It is a race, so it fires
# intermittently and takes the whole connection down with it, not just one query.
#
# Fix: fan-out reads get a client of their own per thread -- a separate
# connection, and therefore separate HPACK state. Sharing is the bug; the
# threads are not.
#
# Serialising instead was measured and rejected: the fan-out is latency-bound at
# ~230ms per round-trip, so five serial reads cost ~1.14s against ~0.25s
# concurrent, on every rerun.
#
# The pool is module-level ON PURPOSE. Its threads are reused, so each thread
# builds its client (and pays its TLS handshake) once rather than per call.
# ---------------------------------------------------------------

_thread_local = threading.local()

# Sized to the widest fan-out below (get_role_counts, 6 tables).
_READ_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="crm-read")


def _thread_client() -> Client:
    """The calling thread's own Supabase client, created on first use.

    Only for reads running inside _READ_POOL. Writes stay on the module-level
    `supabase` client on the main thread, where there is nothing to race with.
    """
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _thread_local.client = client
    return client


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
    """Fetch a profile by login code. Identifies only -- does NOT authenticate.

    The login code is a username: it comes from a thousand-value space, so
    anyone with one can guess the rest. Never log a user in on the strength of
    this alone; go through authenticate().
    """
    response = supabase.table("profiles").select("*").eq("login_code", login_code).execute()
    if response.data:
        return response.data[0]
    return None


def authenticate(login_code: str, password: str):
    """Return the profile only when the code AND password both match.

    Uncached on purpose: a cached login check would keep answering after a
    password was reset or an account revoked.
    """
    if not login_code or not password:
        return None

    response = supabase.table("profiles").select("*").eq("login_code", login_code).execute()
    if not response.data:
        return None

    profile = response.data[0]
    if not passwords_match(password, profile.get("password")):
        return None
    return profile


def start_session(profile_id: str):
    """Issue a fresh session token for the 'remember me' cookie.

    Rotated on every login: an old cookie stops working once you log in again,
    so a stolen one has a short life.
    """
    token = generate_session_token()
    supabase.table("profiles").update({"session_token": token}).eq("id", profile_id).execute()
    _invalidate_reads()
    return token


def get_profile_by_session_token(token: str):
    """Restore a session from the cookie token, or None if it was revoked."""
    if not token:
        return None
    response = supabase.table("profiles").select("*").eq("session_token", token).execute()
    if response.data:
        return response.data[0]
    return None


def end_session(profile_id: str):
    """Revoke the session token so the old cookie is dead."""
    if not profile_id:
        return
    supabase.table("profiles").update({"session_token": None}).eq("id", profile_id).execute()
    _invalidate_reads()


def reset_password(profile_id: str):
    """Give someone a new password and return it to be shown once.

    This is the forgot-password flow: nobody can be locked out, and it also
    kills their session token so a device they lost stops working.
    """
    password = generate_password()
    supabase.table("profiles").update(
        {"password": password, "session_token": None}
    ).eq("id", profile_id).execute()
    _invalidate_reads()
    return password

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_user_roles(profile_id: str):
    """Fetch all roles a user holds by checking the role mapping tables.

    One query per role table, fired concurrently rather than in sequence -- this
    runs on every rerun, so five serial round-trips cost ~1.1s of dead time
    before any portal renders. Cached on top of that.

    Each worker uses its own client: see the CONCURRENT READS note above for why
    sharing one across threads corrupts the connection.
    """
    role_tables = ["admin", "coordinator", "hod", "employee", "client"]

    def holds_role(role):
        return bool(
            _thread_client().table(role + "s").select("id").eq("profile_id", profile_id)
            .execute().data
        )

    held = list(_READ_POOL.map(holds_role, role_tables))

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

# ---------------------------------------------------------------
# MEETINGS
#
# A meeting is private until someone deliberately shares it: both
# show_meeting_to_client and show_summary_to_client default to false in the
# schema. Nothing here ever defaults them open.
# ---------------------------------------------------------------

MEETING_SCHEDULED = "scheduled"
MEETING_COMPLETED = "completed"
MEETING_CANCELLED = "cancelled"

def normalize_join_url(url):
    """Force a pasted link to be absolute, or return None.

    "meet.google.com/abc" in an href is a RELATIVE path: the browser resolves it
    against the CRM's own domain and opens a CRM tab instead of the meeting.
    People paste links without the scheme constantly, so add it rather than
    make them get it right.

    Anything using a scheme other than http/https is dropped -- a join link has
    no business being javascript: or data:.
    """
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.lower().startswith(("http://", "https://")):
        return url
    # Any other scheme is rejected outright. Matching on "://" is not enough:
    # javascript:alert(1) has no slashes and would otherwise be handed a
    # https:// prefix and stored as a real-looking link. Dots are excluded from
    # the scheme so that a host:port ("meet.example.com:443/x") is not mistaken
    # for one.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-]*:", url):
        return None
    return "https://" + url

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_meetings_bulk(project_ids):
    """Meetings for many projects in one query, soonest-first per project.

    Returns {project_id: [meetings]}, with an empty list for projects that have
    none. The client portal renders a tab per project, so never call this in a
    loop.
    """
    grouped = {project_id: [] for project_id in project_ids}
    if not project_ids:
        return grouped

    response = supabase.table("meetings") \
        .select("*") \
        .in_("project_id", list(project_ids)) \
        .order("scheduled_at", desc=True) \
        .execute()

    for meeting in response.data:
        grouped.setdefault(meeting["project_id"], []).append(meeting)

    return grouped

def create_meeting(project_id: str, title: str, scheduled_at: str, agenda: str = None,
                   duration_minutes: int = 30, join_url: str = None,
                   created_by: str = None, show_meeting_to_client: bool = False):
    """Schedule a meeting against a project.

    scheduled_at must be an ISO timestamp. join_url is pasted by the staff
    member: the service account cannot host a Meet, so whoever creates the call
    in their own account stays its host.
    """
    payload = {
        "project_id": project_id,
        "title": title,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "show_meeting_to_client": show_meeting_to_client,
    }
    if agenda:
        payload["agenda"] = agenda
    join_url = normalize_join_url(join_url)
    if join_url:
        payload["join_url"] = join_url
    if created_by:
        payload["created_by"] = created_by

    response = supabase.table("meetings").insert(payload).execute()
    _invalidate_reads()
    return response.data[0]

def update_meeting(meeting_id: str, updates: dict):
    """Update a meeting (notes, summary, status, or either visibility toggle)."""
    if "join_url" in updates:
        updates = dict(updates, join_url=normalize_join_url(updates["join_url"]))
    response = supabase.table("meetings").update(updates).eq("id", meeting_id).execute()
    _invalidate_reads()
    return response.data

def set_meeting_hods(meeting_id: str, hod_profile_ids: list):
    """Replace the HODs tagged on a meeting with exactly this list.

    A full replace, not a diff against what was there before: both the schedule
    form and the edit form hand over "here is the complete list of who should
    see this now", which is simpler to reason about and matches how every other
    checkbox/multiselect in this app is saved.
    """
    supabase.table("meeting_hods").delete().eq("meeting_id", meeting_id).execute()
    if hod_profile_ids:
        supabase.table("meeting_hods").insert([
            {"meeting_id": meeting_id, "hod_profile_id": pid} for pid in hod_profile_ids
        ]).execute()
    _invalidate_reads()

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_meeting_hod_ids(meeting_id: str):
    """Which HODs are currently tagged on a meeting, to pre-fill the edit form."""
    response = supabase.table("meeting_hods").select("hod_profile_id").eq("meeting_id", meeting_id).execute()
    return [row["hod_profile_id"] for row in response.data]

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_meetings_for_hod(hod_profile_id: str):
    """Meetings a specific HOD has been tagged to attend, newest first.

    Two queries rather than one embedded-filter call: meeting_hods is the join
    table, so an HOD's meetings are looked up there first, then the meetings
    themselves are fetched with project/client resolved to names -- an HOD
    should never have to know a project_id to read their own agenda.
    """
    tagged = supabase.table("meeting_hods").select("meeting_id") \
        .eq("hod_profile_id", hod_profile_id).execute().data
    meeting_ids = [row["meeting_id"] for row in tagged]
    if not meeting_ids:
        return []

    response = supabase.table("meetings") \
        .select("*, projects(title, clients(company_name))") \
        .in_("id", meeting_ids) \
        .order("scheduled_at", desc=True) \
        .execute()
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
    """Counts for the admin KPI row, fired concurrently instead of one by one.

    Each worker uses its own client: see the CONCURRENT READS note above for why
    sharing one across threads corrupts the connection.
    """
    tables = ["admins", "coordinators", "hods", "employees", "projects", "clients"]

    def count_rows(table):
        # head=True: the count comes back in Content-Range, so there is no need
        # to drag every id across the wire to discard it.
        return (
            _thread_client().table(table).select("id", count="exact", head=True)
            .execute().count or 0
        )

    counts = list(_READ_POOL.map(count_rows, tables))

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
    """Create a profile with a freshly generated password.

    Every path that makes a user -- admin, coordinator onboarding, HOD adding an
    employee -- comes through here, so generating the password here is what
    guarantees no account is ever created without one. Callers must show
    response["password"] to whoever is setting the user up; it is the only time
    it is put in front of them on purpose.
    """
    payload = {
        "full_name": full_name,
        "role": role,
        "password": generate_password(),
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
