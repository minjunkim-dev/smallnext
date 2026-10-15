-- Client API roles must never read or reset the server's aggregate spending state.
ALTER TABLE app_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE _sqlx_migrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app_metadata, ai_budget, _sqlx_migrations FROM PUBLIC;

-- Only the server DB identity can ask this yes/no question. Never expose auth tables.
-- Dynamic SQL keeps migrations and AI OFF compatible with ordinary PostgreSQL.
CREATE FUNCTION smallnext_session_active(user_id TEXT, session_id TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE active BOOLEAN;
BEGIN
    IF to_regclass('auth.sessions') IS NULL OR to_regclass('auth.users') IS NULL THEN
        RETURN FALSE;
    END IF;
    EXECUTE 'SELECT EXISTS (
        SELECT 1 FROM auth.sessions AS s JOIN auth.users AS u ON u.id = s.user_id
        WHERE s.id = $2::uuid AND s.user_id = $1::uuid
          AND (s.not_after IS NULL OR s.not_after > CURRENT_TIMESTAMP)
          AND u.deleted_at IS NULL
          AND (u.banned_until IS NULL OR u.banned_until <= CURRENT_TIMESTAMP)
          AND u.is_anonymous IS TRUE
    )' INTO active USING user_id, session_id;
    RETURN active;
END;
$$;
REVOKE ALL ON FUNCTION smallnext_session_active(TEXT, TEXT) FROM PUBLIC;

DO $$
DECLARE client_role TEXT;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE app_metadata, ai_budget, _sqlx_migrations FROM %I', client_role);
            EXECUTE format('REVOKE ALL ON FUNCTION smallnext_session_active(TEXT,TEXT) FROM %I', client_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smallnext_api') THEN
        GRANT EXECUTE ON FUNCTION smallnext_session_active(TEXT, TEXT) TO smallnext_api;
    END IF;
END;
$$;
