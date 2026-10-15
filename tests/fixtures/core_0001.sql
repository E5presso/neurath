CREATE TABLE core_schema_revision (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
INSERT INTO core_schema_revision VALUES ('core_0001');
CREATE TABLE core_projects (id VARCHAR NOT NULL PRIMARY KEY, root_path VARCHAR NOT NULL);
CREATE TABLE core_project_locations (kind VARCHAR NOT NULL, path VARCHAR NOT NULL, project_id VARCHAR NOT NULL REFERENCES core_projects(id), PRIMARY KEY(kind,path), CONSTRAINT location_kind CHECK(kind IN ('git','folder')));
CREATE TABLE core_sessions (id VARCHAR NOT NULL PRIMARY KEY, project_id VARCHAR NOT NULL REFERENCES core_projects(id), provider VARCHAR NOT NULL, host_session_id VARCHAR NOT NULL, working_directory VARCHAR NOT NULL, revision INTEGER NOT NULL, CONSTRAINT uq_core_host_session UNIQUE(project_id,provider,host_session_id), CONSTRAINT uq_core_session_scope UNIQUE(project_id,id), CONSTRAINT session_revision_positive CHECK(revision >= 1));
