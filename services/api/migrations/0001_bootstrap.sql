-- Infrastructure metadata only. Product models will use separate migrations.
CREATE TABLE app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO app_metadata (key, value) VALUES ('schema_version', '1');
