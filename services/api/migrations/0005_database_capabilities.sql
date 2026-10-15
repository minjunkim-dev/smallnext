-- Schema owners run migrations. Runtime/backup identities inherit only these NOLOGIN roles.
-- A shared role namespace needs one lock when tests migrate independent schemas concurrently.
SELECT pg_advisory_xact_lock(170, 5);
DO $$
DECLARE capability TEXT;
BEGIN
    FOREACH capability IN ARRAY ARRAY['smallnext_api', 'smallnext_backup'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = capability) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', capability);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = capability
            AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
            OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = capability)
        THEN
            RAISE EXCEPTION 'unsafe existing database capability role';
        END IF;
        EXECUTE format('REVOKE ALL ON TABLE app_metadata, ai_budget, _sqlx_migrations FROM %I', capability);
        EXECUTE format('REVOKE ALL ON FUNCTION smallnext_session_active(TEXT,TEXT) FROM %I', capability);
        EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM %I', current_schema(), capability);
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', current_schema(), capability);
    END LOOP;
    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM PUBLIC', current_schema());
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_budget TO smallnext_api;
CREATE POLICY smallnext_api_budget ON ai_budget TO smallnext_api
    USING (TRUE) WITH CHECK (TRUE);
GRANT EXECUTE ON FUNCTION smallnext_session_active(TEXT, TEXT) TO smallnext_api;

GRANT SELECT (singleton, month, charged_micro_usd, blocked) ON ai_budget TO smallnext_backup;
CREATE POLICY smallnext_backup_budget ON ai_budget FOR SELECT TO smallnext_backup USING (TRUE);
