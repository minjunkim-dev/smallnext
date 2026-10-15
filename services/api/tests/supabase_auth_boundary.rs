use sqlx::{PgPool, postgres::PgPoolOptions};

async fn active(pool: &PgPool, user: &str, session: &str) -> bool {
    sqlx::query_scalar("SELECT smallnext_session_active($1,$2)")
        .bind(user)
        .bind(session)
        .fetch_one(pool)
        .await
        .unwrap()
}

#[tokio::test]
#[ignore = "requires isolated TEST_DATABASE_URL with no existing auth schema"]
async fn session_and_client_privileges_fail_closed_without_changing_auth_schema() {
    let url =
        std::env::var("TEST_DATABASE_URL").expect("explicit isolated TEST_DATABASE_URL required");
    let admin = PgPoolOptions::new().connect(&url).await.unwrap();
    let auth_exists: bool = sqlx::query_scalar("SELECT to_regnamespace('auth') IS NOT NULL")
        .fetch_one(&admin)
        .await
        .unwrap();
    assert!(
        !auth_exists,
        "this synthetic Auth test requires an isolated database"
    );
    let schema = format!("test_supabase_boundary_{}", std::process::id());
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&admin)
        .await
        .unwrap();
    let options: sqlx::postgres::PgConnectOptions = url.parse().unwrap();
    let pool = PgPoolOptions::new()
        .connect_with(options.options([("search_path", schema.as_str())]))
        .await
        .unwrap();
    let mut created = Vec::new();
    for role in ["anon", "authenticated", "service_role", "smallnext_api"] {
        let exists: bool =
            sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)")
                .bind(role)
                .fetch_one(&admin)
                .await
                .unwrap();
        if !exists {
            sqlx::query(&format!("CREATE ROLE {role} NOLOGIN"))
                .execute(&admin)
                .await
                .unwrap();
            created.push(role);
        }
        if role != "smallnext_api" {
            sqlx::query(&format!(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO {role}"
            ))
            .execute(&admin)
            .await
            .unwrap();
            sqlx::query(&format!(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT EXECUTE ON FUNCTIONS TO {role}"
            ))
            .execute(&admin)
            .await
            .unwrap();
        }
    }
    smallnext_api::migrate(&pool).await.unwrap();
    let user = "11111111-1111-4111-8111-111111111111";
    let session = "33333333-3333-4333-8333-333333333333";
    assert!(!active(&pool, user, session).await);
    for role in ["anon", "authenticated", "service_role"] {
        for table in ["ai_budget", "app_metadata", "_sqlx_migrations"] {
            let permission: bool = sqlx::query_scalar(
                "SELECT has_table_privilege($1, $2, 'SELECT,INSERT,UPDATE,DELETE')",
            )
            .bind(role)
            .bind(format!("{schema}.{table}"))
            .fetch_one(&pool)
            .await
            .unwrap();
            assert!(!permission, "client role must have no app table privileges");
        }
        let permission: bool =
            sqlx::query_scalar("SELECT has_function_privilege($1, $2, 'EXECUTE')")
                .bind(role)
                .bind(format!("{schema}.smallnext_session_active(text,text)"))
                .fetch_one(&pool)
                .await
                .unwrap();
        assert!(!permission, "client role must not inspect sessions");
    }
    let execute: bool =
        sqlx::query_scalar("SELECT has_function_privilege('smallnext_api', $1, 'EXECUTE')")
            .bind(format!("{schema}.smallnext_session_active(text,text)"))
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(execute);
    let protected: i64 = sqlx::query_scalar("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1 AND c.relname IN ('ai_budget','app_metadata','_sqlx_migrations') AND c.relrowsecurity")
        .bind(&schema).fetch_one(&pool).await.unwrap();
    assert_eq!(protected, 3);

    // Synthetic managed Auth schema, never executed against a remote Supabase project.
    sqlx::raw_sql("CREATE SCHEMA auth; CREATE TABLE auth.users(id UUID PRIMARY KEY, deleted_at TIMESTAMPTZ, banned_until TIMESTAMPTZ, is_anonymous BOOLEAN); CREATE TABLE auth.sessions(id UUID PRIMARY KEY, user_id UUID, not_after TIMESTAMPTZ)")
        .execute(&admin).await.unwrap();
    sqlx::query("INSERT INTO auth.users VALUES($1::text::uuid,NULL,NULL,TRUE)")
        .bind(user)
        .execute(&admin)
        .await
        .unwrap();
    sqlx::query("INSERT INTO auth.sessions VALUES($1::text::uuid,$2::text::uuid,NULL)")
        .bind(session)
        .bind(user)
        .execute(&admin)
        .await
        .unwrap();
    assert!(active(&pool, user, session).await);
    assert!(!active(&pool, "22222222-2222-4222-8222-222222222222", session).await);
    for mutation in [
        "UPDATE auth.sessions SET not_after=now()-interval '1 second'",
        "UPDATE auth.users SET banned_until=now()+interval '1 hour'",
        "UPDATE auth.users SET deleted_at=now()",
        "UPDATE auth.users SET is_anonymous=FALSE",
    ] {
        sqlx::raw_sql(mutation).execute(&admin).await.unwrap();
        assert!(!active(&pool, user, session).await);
        sqlx::raw_sql("UPDATE auth.sessions SET not_after=NULL; UPDATE auth.users SET banned_until=NULL,deleted_at=NULL,is_anonymous=TRUE").execute(&admin).await.unwrap();
    }
    sqlx::query("DELETE FROM auth.sessions")
        .execute(&admin)
        .await
        .unwrap();
    assert!(!active(&pool, user, session).await);
    pool.close().await;
    sqlx::raw_sql(&format!(
        "DROP SCHEMA auth CASCADE; DROP SCHEMA {schema} CASCADE"
    ))
    .execute(&admin)
    .await
    .unwrap();
    for role in created {
        sqlx::raw_sql(&format!("DROP OWNED BY {role}; DROP ROLE {role}"))
            .execute(&admin)
            .await
            .unwrap();
    }
    admin.close().await;
}
