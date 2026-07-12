# Agency CRM Development Plan

## 1. Project Overview
A lightweight, pure Python CRM built specifically for your agency. The system will ditch JavaScript entirely, relying on **Streamlit** for a rapid, reactive frontend and **Supabase (PostgreSQL)** for the backend, storage, and logic. 

**Core Objectives:**
- Zero-friction client access using an Access Code (no email/password needed).
- Hierarchical staff portal mapping exact roles (Manager, Supervisor, HR, Employee).
- Project-centric architecture where tasks and proposals revolve around a central Project hub.
- Integrated time tracking on tasks.
- Streamlined one-step onboarding flow for managers to add clients and proposals instantly.

---

## 2. Tech Stack
- **Frontend / UI:** Streamlit (Python)
- **Backend / Database:** Supabase (PostgreSQL)
- **File Storage:** Supabase Storage Bucket (`proposals` and `task_attachments`)
- **Authentication/Access:** Custom logic using unique string `login_code` matched against the `profiles` table.

---

## 3. Database Architecture (Supabase DDL)

To set up your database, execute the following SQL script directly in your Supabase SQL Editor. It creates the custom Enum types, tables, and necessary foreign key constraints.

```sql
-- 1. Create Enums for standardized fields
CREATE TYPE user_role AS ENUM ('client', 'employee', 'manager', 'hr', 'supervisor');
CREATE TYPE task_source AS ENUM ('internal', 'client_request');
CREATE TYPE task_status AS ENUM ('todo', 'in_progress', 'review', 'done');
CREATE TYPE project_status AS ENUM ('pitching', 'active', 'completed', 'cancelled');
CREATE TYPE proposal_status AS ENUM ('draft', 'sent', 'approved', 'rejected');

-- 2. Profiles Table (Authentication & Routing)
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'client',
    login_code TEXT UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Clients Table (Business Entity)
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Employees Table (Agency Staff)
CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    department TEXT,
    designation TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Projects Table (The Central Hub)
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status project_status DEFAULT 'pitching',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 6. Proposals Table
CREATE TABLE proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_url TEXT NOT NULL,
    version INT DEFAULT 1,
    status proposal_status DEFAULT 'sent',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 7. Tasks Table (With Time Tracking & Sourcing)
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assigned_to UUID REFERENCES employees(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    task_source task_source DEFAULT 'internal',
    status task_status DEFAULT 'todo',
    estimated_hours NUMERIC(5, 2) DEFAULT 0.0,
    actual_hours NUMERIC(5, 2) DEFAULT 0.0,
    image_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 4. Implementation Steps

### Phase 1: Foundation
1. Create a new Supabase project.
2. Run the DDL script in the Supabase SQL Editor.
3. Create the necessary storage buckets in Supabase (`documents` for proposals, `task_images` for progress shots).
4. Initialize your Python project (`pip install streamlit supabase`).

### Phase 2: Authentication & Routing
1. Build `app.py` with `st.tabs(["Client Login", "Staff Login"])`.
2. Implement the Access Code verification logic connecting to the `profiles` table.
3. Create routing files based on the fetched `role` flag (`client_portal.py`, `manager_dashboard.py`, `employee_dashboard.py`).

### Phase 3: The Manager/Staff Portal
1. **Onboarding Form:** Implement the 5-step transaction (Profile -> Client -> Project -> Upload -> Proposal).
2. **Task Dispatcher:** Build the global task view. Query all `tasks` and use `st.selectbox` tied to the `employees` table for assignments.
3. **Employee View:** Filter tasks by `assigned_to`. Add the `st.number_input` for employees to update `actual_hours` and `st.file_uploader` for progress images.

### Phase 4: The Client Portal
1. Fetch projects where `client_id` matches the logged-in user.
2. For each project, display the proposal link.
3. Query `tasks` linked to the project to calculate overall completion percentage (`done` vs `total`).
4. Provide a form for clients to insert new records into the `tasks` table flagged as `client_request`.

---
