-- In-app account deletion (App Review 5.1.1(v)). Only an anonymous account; Auth cascades its sessions.
-- Dynamic SQL keeps migrations compatible with ordinary PostgreSQL, where nothing is deleted.
CREATE FUNCTION smallnext_delete_anonymous_user(user_id TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE deleted BOOLEAN;
BEGIN
    IF to_regclass('auth.users') IS NULL THEN
        RETURN FALSE;
    END IF;
    EXECUTE 'WITH removed AS (
        DELETE FROM auth.users WHERE id = $1::uuid AND is_anonymous IS TRUE RETURNING 1
    ) SELECT EXISTS (SELECT 1 FROM removed)' INTO deleted USING user_id;
    RETURN deleted;
END;
$$;
REVOKE ALL ON FUNCTION smallnext_delete_anonymous_user(TEXT) FROM PUBLIC;

DO $$
DECLARE client_role TEXT;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role', 'smallnext_backup'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION smallnext_delete_anonymous_user(TEXT) FROM %I', client_role);
        END IF;
    END LOOP;
END;
$$;
GRANT EXECUTE ON FUNCTION smallnext_delete_anonymous_user(TEXT) TO smallnext_api;
