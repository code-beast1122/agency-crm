import os
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

try:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL"))
    SUPABASE_KEY = st.secrets.get("ANON_KEY", os.environ.get("ANON_KEY"))
except Exception:
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials. Make sure SUPABASE_URL and ANON_KEY are set in .env or Streamlit secrets")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_profile_by_code(login_code: str):
    """Fetch user profile based on unique login code."""
    response = supabase.table("profiles").select("*").eq("login_code", login_code).execute()
    if response.data:
        return response.data[0]
    return None

def get_projects_for_client(client_profile_id: str):
    """Fetch projects associated with a specific client's profile ID."""
    # First get the client ID
    client_response = supabase.table("clients").select("id").eq("profile_id", client_profile_id).execute()
    if not client_response.data:
        return []
    
    client_id = client_response.data[0]["id"]
    projects_response = supabase.table("projects").select("*").eq("client_id", client_id).execute()
    return projects_response.data

def get_tasks_for_project(project_id: str):
    """Fetch tasks for a specific project."""
    response = supabase.table("tasks").select("*").eq("project_id", project_id).execute()
    return response.data

def get_all_employees():
    """Fetch all employee profiles with their employee record."""
    response = supabase.table("employees").select("id, profile_id, department, designation, profiles(full_name)").execute()
    return response.data

def get_all_projects():
    """Fetch all projects (for manager)."""
    response = supabase.table("projects").select("*, clients(company_name)").execute()
    return response.data

def get_all_clients():
    """Fetch all clients (for manager)."""
    response = supabase.table("clients").select("id, company_name, profile_id, profiles(full_name)").execute()
    return response.data

def get_all_tasks():
    """Fetch all tasks (for manager/dispatcher)."""
    response = supabase.table("tasks").select("*, projects(title), employees(profiles(full_name))").execute()
    return response.data

def update_task(task_id: str, updates: dict):
    """Update a specific task."""
    response = supabase.table("tasks").update(updates).eq("id", task_id).execute()
    return response.data

def create_client_record(profile_id: str, company_name: str):
    """Create a client record."""
    response = supabase.table("clients").insert({
        "profile_id": profile_id,
        "company_name": company_name
    }).execute()
    return response.data[0]

def create_employee_record(profile_id: str, department: str, designation: str):
    """Create an employee record."""
    response = supabase.table("employees").insert({
        "profile_id": profile_id,
        "department": department,
        "designation": designation
    }).execute()
    return response.data[0]

def create_project(client_id: str, title: str):
    """Create a project."""
    response = supabase.table("projects").insert({
        "client_id": client_id,
        "title": title
    }).execute()
    return response.data[0]

def update_project(project_id: str, updates: dict):
    """Update a specific project."""
    response = supabase.table("projects").update(updates).eq("id", project_id).execute()
    return response.data

def create_proposal(project_id: str, file_url: str):
    """Create a proposal."""
    response = supabase.table("proposals").insert({
        "project_id": project_id,
        "file_url": file_url
    }).execute()
    return response.data[0]

def create_profile(full_name: str, role: str, login_code: str):
    """Create a profile."""
    response = supabase.table("profiles").insert({
        "full_name": full_name,
        "role": role,
        "login_code": login_code
    }).execute()
    return response.data[0]

def create_task(project_id: str, title: str, description: str, source: str = "internal", deadline: str = None, image_url: str = None, estimated_hours: float = 0.0):
    """Create a task."""
    payload = {
        "project_id": project_id,
        "title": title,
        "description": description,
        "task_source": source,
        "estimated_hours": estimated_hours
    }
    if deadline:
        payload["deadline"] = deadline
    if image_url:
        payload["image_url"] = image_url
        
    response = supabase.table("tasks").insert(payload).execute()
    return response.data[0]

def start_task_timer(task_id: str, employee_id: str):
    """Start a timer for a task."""
    response = supabase.table("time_logs").insert({
        "task_id": task_id,
        "employee_id": employee_id
    }).execute()
    return response.data[0] if response.data else None

def stop_task_timer(time_log_id: str):
    """Stop a timer by ID."""
    now = datetime.now(timezone.utc).isoformat()
    response = supabase.table("time_logs").update({"end_time": now}).eq("id", time_log_id).execute()
    return response.data[0] if response.data else None

def get_active_timer(task_id: str, employee_id: str):
    """Get active timer for an employee on a task."""
    response = supabase.table("time_logs").select("*").eq("task_id", task_id).eq("employee_id", employee_id).is_("end_time", "null").execute()
    if response.data:
        return response.data[0]
    return None

def get_total_time_logged(task_id: str):
    """Calculate total duration logged for a task in hours."""
    response = supabase.table("time_logs").select("*").eq("task_id", task_id).not_.is_("end_time", "null").execute()
    total_hours = 0.0
    for log in response.data:
        try:
            start = datetime.fromisoformat(log["start_time"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(log["end_time"].replace("Z", "+00:00"))
            duration = end - start
            total_hours += duration.total_seconds() / 3600.0
        except Exception:
            pass # Skip invalid dates
    return total_hours
