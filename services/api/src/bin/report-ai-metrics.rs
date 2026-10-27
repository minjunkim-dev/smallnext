//! Operator report: `report-ai-metrics FROM TO` prints anonymous metrics for [FROM, TO) UTC days.
#[tokio::main]
async fn main() -> std::process::ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let date = |v: &str| {
        v.len() == 10
            && v.bytes().enumerate().all(|(i, b)| {
                matches!(i, 4 | 7) == (b == b'-') && (b == b'-' || b.is_ascii_digit())
            })
    };
    let [from, to] = args.as_slice() else {
        eprintln!("usage: report-ai-metrics YYYY-MM-DD YYYY-MM-DD");
        return std::process::ExitCode::FAILURE;
    };
    if !date(from) || !date(to) || from >= to {
        eprintln!("usage: report-ai-metrics FROM TO (YYYY-MM-DD, FROM before TO)");
        return std::process::ExitCode::FAILURE;
    }
    match report(from, to).await {
        Ok(json) => {
            println!("{json}");
            std::process::ExitCode::SUCCESS
        }
        Err(_) => {
            // Database errors can contain connection details; keep host logs value-free.
            eprintln!("AI metrics report failed");
            std::process::ExitCode::FAILURE
        }
    }
}

async fn report(from: &str, to: &str) -> Result<String, Box<dyn std::error::Error>> {
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(&std::env::var("DATABASE_URL")?)
        .await?;
    Ok(smallnext_api::user_ai::metrics::report(&pool, from, to).await?)
}
