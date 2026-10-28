
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE repositories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    provider VARCHAR(50) NOT NULL,
    repository_url TEXT NOT NULL,
    default_branch VARCHAR(255) DEFAULT 'main',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_repositories_project
        FOREIGN KEY (project_id)
        REFERENCES projects(id)
        ON DELETE RESTRICT
);


CREATE TABLE spec_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    version_number INTEGER NOT NULL,
    spec_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_spec_versions_project
        FOREIGN KEY (project_id)
        REFERENCES projects(id),

    CONSTRAINT uq_project_spec_version
        UNIQUE (project_id, version_number),
CONSTRAINT uq_spec_version_project
    UNIQUE (id, project_id),
    CONSTRAINT chk_spec_version_positive
        CHECK (version_number > 0)
);


CREATE TABLE compilations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    spec_version_id UUID NOT NULL,
    target_platform VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_compilations_project
        FOREIGN KEY (project_id)
        REFERENCES projects(id),

CONSTRAINT fk_compilations_spec_version
    FOREIGN KEY (spec_version_id, project_id)
    REFERENCES spec_versions(id, project_id),
    CONSTRAINT chk_compilation_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compilation_id UUID NOT NULL,
    job_type VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_jobs_compilation
        FOREIGN KEY (compilation_id)
        REFERENCES compilations(id),

    CONSTRAINT chk_job_status
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),

    CONSTRAINT chk_job_attempts
        CHECK (attempts >= 0)
);


CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compilation_id UUID NOT NULL,
    file_path TEXT NOT NULL,
    file_type VARCHAR(100) NOT NULL,
    content_hash VARCHAR(64),
    storage_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_artifacts_compilation
        FOREIGN KEY (compilation_id)
        REFERENCES compilations(id),

    CONSTRAINT uq_artifact_compilation_path
        UNIQUE (compilation_id, file_path)
);


-- Task 3: Database Indexes

CREATE INDEX idx_repositories_project_id
    ON repositories(project_id);

CREATE INDEX idx_spec_versions_project_id
    ON spec_versions(project_id);

CREATE INDEX idx_compilations_project_id
    ON compilations(project_id);

CREATE INDEX idx_compilations_spec_version_id
    ON compilations(spec_version_id);

CREATE INDEX idx_jobs_compilation_id
    ON jobs(compilation_id);

CREATE INDEX idx_artifacts_compilation_id
    ON artifacts(compilation_id);
