-- Open beta limits and anonymous operating metrics (#238). No raw UID, goal, response or token.
ALTER TABLE ai_budget
    ADD COLUMN day TEXT NOT NULL DEFAULT '',
    ADD COLUMN day_charged_micro_usd BIGINT NOT NULL DEFAULT 0 CHECK (day_charged_micro_usd >= 0);

-- user_hash is HMAC-SHA256(server-only key, UID). Rows expire after 30 days.
CREATE TABLE ai_daily_usage (
    day DATE NOT NULL,
    user_hash BYTEA NOT NULL CHECK (octet_length(user_hash) = 32),
    requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
    limited INTEGER NOT NULL DEFAULT 0 CHECK (limited >= 0),
    PRIMARY KEY (day, user_hash)
);

-- One row per reserved request. A row left as 'started' was cancelled. Rows expire after 90 days.
CREATE TABLE ai_request_metrics (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'started',
    elapsed_ms BIGINT CHECK (elapsed_ms >= 0),
    cost_micro_usd BIGINT CHECK (cost_micro_usd >= 0)
);
CREATE INDEX ai_request_metrics_started_at ON ai_request_metrics (started_at);

ALTER TABLE ai_daily_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_request_metrics ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ai_daily_usage, ai_request_metrics FROM PUBLIC;
REVOKE ALL ON SEQUENCE ai_request_metrics_id_seq FROM PUBLIC;

DO $$
DECLARE client_role TEXT;
BEGIN
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role', 'smallnext_backup'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE ai_daily_usage, ai_request_metrics FROM %I', client_role);
            EXECUTE format('REVOKE ALL ON SEQUENCE ai_request_metrics_id_seq FROM %I', client_role);
        END IF;
    END LOOP;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_daily_usage, ai_request_metrics TO smallnext_api;
GRANT USAGE ON SEQUENCE ai_request_metrics_id_seq TO smallnext_api;
CREATE POLICY smallnext_api_daily_usage ON ai_daily_usage TO smallnext_api
    USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY smallnext_api_request_metrics ON ai_request_metrics TO smallnext_api
    USING (TRUE) WITH CHECK (TRUE);
