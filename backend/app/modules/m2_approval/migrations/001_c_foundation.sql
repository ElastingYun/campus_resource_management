-- C-owned baseline only. No references to another module's private tables.
CREATE TABLE c_users (
    id uuid PRIMARY KEY,
    username varchar(128) NOT NULL UNIQUE,
    password_hash text NOT NULL,
    department_id text NOT NULL,
    room_ids text[] NOT NULL DEFAULT '{}',
    all_rooms boolean NOT NULL DEFAULT false,
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE c_roles (name text PRIMARY KEY, permissions text[] NOT NULL);
CREATE TABLE c_user_roles (
    user_id uuid NOT NULL REFERENCES c_users(id),
    role_name text NOT NULL REFERENCES c_roles(name),
    PRIMARY KEY (user_id,role_name)
);
CREATE TABLE c_sessions (
    token_hash char(64) PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES c_users(id),
    expires_at timestamptz NOT NULL,
    revoked boolean NOT NULL DEFAULT false
);
CREATE INDEX c_sessions_expiry_idx ON c_sessions(expires_at);
CREATE TABLE c_login_buckets (
    key text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts >= 0)
);
CREATE TABLE c_audit_events (
    id uuid PRIMARY KEY,
    actor_id uuid,
    action text NOT NULL,
    target text NOT NULL,
    result text NOT NULL,
    occurred_at timestamptz NOT NULL,
    request_id varchar(128) NOT NULL,
    room_id text,
    changes jsonb NOT NULL
);
CREATE INDEX c_audit_scope_idx ON c_audit_events(room_id,occurred_at DESC,id DESC);
CREATE TABLE c_applications (
    id uuid PRIMARY KEY,
    applicant_id uuid NOT NULL REFERENCES c_users(id),
    room_id text NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL CHECK (ends_at > starts_at),
    purpose varchar(2000) NOT NULL CHECK (length(trim(purpose)) > 0),
    review_status text NOT NULL CHECK (review_status IN ('REVIEWING','PASSED','REJECTED','TIMED_OUT')),
    integration_status text NOT NULL CHECK (integration_status IN
        ('NONE','APPLY_PENDING','APPLY_UNKNOWN','APPLIED','APPLY_CONFLICT',
         'RELEASE_PENDING','RELEASE_UNKNOWN','RELEASED')),
    step_index integer NOT NULL CHECK (step_index >= 0),
    steps jsonb NOT NULL CHECK (jsonb_array_length(steps) > 0),
    rules jsonb NOT NULL,
    deadline timestamptz NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    generation integer NOT NULL DEFAULT 0 CHECK (generation >= 0),
    revoked boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX c_applications_owner_idx ON c_applications(applicant_id,created_at,id);
CREATE INDEX c_applications_scope_idx ON c_applications(room_id,created_at,id);
CREATE INDEX c_applications_due_idx ON c_applications(deadline) WHERE review_status='REVIEWING';
CREATE TABLE c_decisions (
    id uuid PRIMARY KEY,
    application_id uuid NOT NULL REFERENCES c_applications(id),
    step_index integer NOT NULL,
    actor_id uuid NOT NULL REFERENCES c_users(id),
    decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
    comment varchar(2000) NOT NULL,
    occurred_at timestamptz NOT NULL,
    UNIQUE (application_id,step_index)
);
CREATE TABLE c_receipts (
    actor_id uuid NOT NULL,
    action text NOT NULL,
    key varchar(128) NOT NULL,
    fingerprint char(64) NOT NULL,
    response jsonb NOT NULL,
    PRIMARY KEY (actor_id,action,key)
);
CREATE TABLE c_m1_operations (
    id uuid PRIMARY KEY,
    application_id uuid NOT NULL REFERENCES c_applications(id),
    generation integer NOT NULL,
    kind text NOT NULL CHECK (kind IN ('APPLY','RELEASE')),
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'PENDING' CHECK
        (state IN ('PENDING','RUNNING','UNKNOWN','DONE','CONFLICT','ATTENTION')),
    attempts integer NOT NULL DEFAULT 0,
    due_at timestamptz NOT NULL,
    lease_until timestamptz,
    lease_token uuid,
    error_code text,
    UNIQUE (application_id,generation)
);
CREATE INDEX c_m1_operations_due_idx ON c_m1_operations(due_at,lease_until)
    WHERE state IN ('PENDING','UNKNOWN','RUNNING');
CREATE TABLE c_business_events (
    id uuid PRIMARY KEY,
    application_id uuid NOT NULL REFERENCES c_applications(id),
    type text NOT NULL,
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL
);
