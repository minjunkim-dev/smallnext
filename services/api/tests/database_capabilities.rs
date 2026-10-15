use sqlx::{PgPool, postgres::PgPoolOptions};
use std::process::{Command, Stdio};

async fn as_role(url: &str, schema: &str, role: &str) -> PgPool {
    let options: sqlx::postgres::PgConnectOptions = url.parse().unwrap();
    PgPoolOptions::new()
        .max_connections(3)
        .connect_with(options.options([("search_path", schema), ("role", role)]))
        .await
        .unwrap()
}

#[tokio::test]
#[ignore = "requires isolated TEST_DATABASE_URL and role-creating migration owner"]
async fn runtime_and_backup_capabilities_allow_only_required_budget_operations() {
    let url = std::env::var("TEST_DATABASE_URL").expect("explicit test database required");
    let owner = PgPoolOptions::new().connect(&url).await.unwrap();
    let schema = format!("test_capabilities_{}", std::process::id());
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&owner)
        .await
        .unwrap();
    let options: sqlx::postgres::PgConnectOptions = url.parse().unwrap();
    let admin = PgPoolOptions::new()
        .connect_with(options.options([("search_path", schema.as_str())]))
        .await
        .unwrap();
    let mut migration_url: reqwest::Url = url.parse().unwrap();
    migration_url
        .query_pairs_mut()
        .append_pair("options", &format!("-c search_path={schema}"));
    let migrated = Command::new(env!("CARGO_BIN_EXE_migrate-api"))
        .env("DATABASE_URL", migration_url.as_str())
        .output()
        .unwrap();
    assert!(migrated.status.success());
    assert_eq!(migrated.stdout, b"API migration completed\n");
    assert!(migrated.stderr.is_empty());
    smallnext_api::migrate(&admin).await.unwrap();
    let runtime = as_role(&url, &schema, "smallnext_api").await;
    let backup = as_role(&url, &schema, "smallnext_backup").await;
    let identity: String = sqlx::query_scalar("SELECT current_user")
        .fetch_one(&runtime)
        .await
        .unwrap();
    assert_eq!(identity, "smallnext_api");
    let privileged: i64 = sqlx::query_scalar("SELECT count(*) FROM pg_roles WHERE rolname IN ('smallnext_api','smallnext_backup') AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)")
        .fetch_one(&admin).await.unwrap();
    assert_eq!(privileged, 0);
    let owned: i64 = sqlx::query_scalar("SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname IN ('smallnext_api','smallnext_backup')")
        .fetch_one(&admin).await.unwrap();
    assert_eq!(owned, 0);
    let previous: String = sqlx::query_scalar(
        "SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - interval '1 month','YYYY-MM')",
    )
    .fetch_one(&admin)
    .await
    .unwrap();
    let current: String =
        sqlx::query_scalar("SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM')")
            .fetch_one(&admin)
            .await
            .unwrap();
    sqlx::query("INSERT INTO ai_budget(singleton,month,charged_micro_usd) VALUES(TRUE,$1,9)")
        .bind(previous)
        .execute(&runtime)
        .await
        .unwrap();
    smallnext_api::user_ai::budget::purge_expired(&runtime)
        .await
        .unwrap();
    let remaining: i64 = sqlx::query_scalar("SELECT count(*) FROM ai_budget")
        .fetch_one(&runtime)
        .await
        .unwrap();
    assert_eq!(remaining, 0);
    sqlx::query("INSERT INTO ai_budget(singleton,month,charged_micro_usd) VALUES(TRUE,$1,0) ON CONFLICT DO NOTHING").bind(current).execute(&runtime).await.unwrap();
    let mut reservation = runtime.begin().await.unwrap();
    let before: i64 =
        sqlx::query_scalar("SELECT charged_micro_usd FROM ai_budget WHERE singleton FOR UPDATE")
            .fetch_one(&mut *reservation)
            .await
            .unwrap();
    assert_eq!(before, 0);
    sqlx::query("UPDATE ai_budget SET charged_micro_usd=100 WHERE singleton")
        .execute(&mut *reservation)
        .await
        .unwrap();
    reservation.commit().await.unwrap();
    let row: (bool, String, i64, bool) =
        sqlx::query_as("SELECT singleton,month,charged_micro_usd,blocked FROM ai_budget")
            .fetch_one(&backup)
            .await
            .unwrap();
    assert_eq!(row.2, 100);
    let table_select: bool =
        sqlx::query_scalar("SELECT has_table_privilege('smallnext_backup',$1,'SELECT')")
            .bind(format!("{schema}.ai_budget"))
            .fetch_one(&admin)
            .await
            .unwrap();
    assert!(!table_select, "backup has column grants only");
    let active: bool = sqlx::query_scalar("SELECT smallnext_session_active('11111111-1111-4111-8111-111111111111','33333333-3333-4333-8333-333333333333')").fetch_one(&runtime).await.unwrap();
    assert!(!active, "ordinary PostgreSQL has no managed Auth session");
    for pool in [&runtime, &backup] {
        for denied in [
            "SELECT * FROM app_metadata",
            "SELECT * FROM _sqlx_migrations",
            "TRUNCATE ai_budget",
            "CREATE TABLE unexpected(value INT)",
            "CREATE SCHEMA unexpected_capability_schema",
            "ALTER TABLE ai_budget ADD COLUMN unexpected INT",
            "ALTER FUNCTION smallnext_session_active(TEXT,TEXT) OWNER TO smallnext_api",
        ] {
            assert!(
                sqlx::query(denied).execute(pool).await.is_err(),
                "forbidden operation succeeded: {denied}"
            );
        }
    }
    for denied in [
        "INSERT INTO ai_budget(singleton,month,charged_micro_usd) VALUES(TRUE,'2099-01',0)",
        "UPDATE ai_budget SET charged_micro_usd=0",
        "DELETE FROM ai_budget",
        "SELECT smallnext_session_active('a','b')",
    ] {
        assert!(
            sqlx::query(denied).execute(&backup).await.is_err(),
            "backup operation succeeded: {denied}"
        );
    }
    let mut altered = admin.acquire().await.unwrap();
    sqlx::query("ALTER TABLE ai_budget ADD COLUMN owner_only_secret TEXT")
        .execute(&mut *altered)
        .await
        .unwrap();
    assert!(
        sqlx::query("SELECT owner_only_secret FROM ai_budget")
            .execute(&backup)
            .await
            .is_err()
    );
    sqlx::query("ALTER TABLE ai_budget DROP COLUMN owner_only_secret")
        .execute(&mut *altered)
        .await
        .unwrap();
    drop(altered);

    // This test uses synthetic role startup options. Operational LOGIN credentials are separate.
    let base: reqwest::Url = url.parse().unwrap();
    let mut runtime_url = base.clone();
    runtime_url.query_pairs_mut().append_pair(
        "options",
        &format!("-c search_path={schema} -c role=smallnext_api"),
    );
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let mut child = Command::new(env!("CARGO_BIN_EXE_smallnext-api"))
        .env("DATABASE_URL", runtime_url.as_str())
        .env("API_AUTO_MIGRATE", "0")
        .env("API_BIND_ADDRESS", address.to_string())
        .env("USER_SERVER_AI", "0")
        .env("DEVELOPMENT_SUBSCRIPTION_AI", "0")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let http = reqwest::Client::new();
    let mut ready = false;
    for _ in 0..50 {
        if http
            .get(format!("http://{address}/ready"))
            .send()
            .await
            .is_ok_and(|r| r.status().is_success())
        {
            ready = true;
            break;
        }
        if child.try_wait().unwrap().is_some() {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
    let _ = child.kill();
    let _ = child.wait();
    assert!(
        ready,
        "runtime starts without migration/metadata privileges when API_AUTO_MIGRATE=0"
    );
    let mut default = Command::new(env!("CARGO_BIN_EXE_smallnext-api"))
        .env("DATABASE_URL", runtime_url.as_str())
        .env_remove("API_AUTO_MIGRATE")
        .env("API_BIND_ADDRESS", address.to_string())
        .env("USER_SERVER_AI", "0")
        .env("DEVELOPMENT_SUBSCRIPTION_AI", "0")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut rejected = false;
    for _ in 0..50 {
        if let Some(exit) = default.try_wait().unwrap() {
            rejected = !exit.success();
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
    let _ = default.kill();
    let _ = default.wait();
    assert!(rejected, "development default still attempts migration");
    let denied = Command::new(env!("CARGO_BIN_EXE_migrate-api"))
        .env("DATABASE_URL", runtime_url.as_str())
        .output()
        .unwrap();
    assert!(!denied.status.success());
    assert!(denied.stdout.is_empty());
    assert_eq!(denied.stderr, b"API migration failed\n");
    runtime.close().await;
    backup.close().await;
    admin.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&owner)
        .await
        .unwrap();
    owner.close().await;
}
