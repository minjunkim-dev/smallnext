use super::{client, read_json};
use axum::http::{HeaderMap, StatusCode, header};
use jsonwebtoken::{
    Algorithm, DecodingKey, EncodingKey, Header, Validation, decode, decode_header, encode,
    get_current_timestamp,
};
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};
use tokio::sync::Mutex;

#[derive(Clone)]
pub(super) struct Firebase {
    project: String,
    allowed: HashSet<String>,
    account: Arc<ServiceAccount>,
    http: reqwest::Client,
    keys: Arc<Mutex<Keys>>,
    access: Arc<Mutex<Access>>,
    pub(super) endpoints: Endpoints,
}

#[derive(Clone)]
pub(super) struct Endpoints {
    pub keys: String,
    pub oauth: String,
    pub lookup: String,
}

#[derive(Deserialize)]
struct ServiceAccountFile {
    r#type: String,
    project_id: String,
    client_email: String,
    private_key: String,
}
struct ServiceAccount {
    email: String,
    key: EncodingKey,
}
#[derive(Default)]
struct Keys {
    values: HashMap<String, String>,
    expires: u64,
}
#[derive(Default)]
struct Access {
    token: String,
    expires: u64,
}

#[derive(Deserialize)]
struct Claims {
    sub: String,
    exp: u64,
    iat: u64,
    auth_time: u64,
    aud: String,
    iss: String,
    firebase: FirebaseClaims,
    user_id: Option<String>,
}
#[derive(Deserialize)]
struct FirebaseClaims {
    sign_in_provider: String,
}
#[derive(Deserialize)]
struct TokenResponse {
    access_token: String,
    expires_in: u64,
    token_type: String,
}
#[derive(Deserialize)]
struct Lookup {
    users: Vec<Account>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Account {
    local_id: String,
    #[serde(default)]
    disabled: bool,
    valid_since: Option<String>,
}

impl Firebase {
    pub(super) fn new(
        project: String,
        allowed: HashSet<String>,
        bytes: &[u8],
    ) -> Result<Self, &'static str> {
        if project.is_empty()
            || !project
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-')
            || allowed.is_empty()
            || allowed.iter().any(|uid| uid.is_empty() || uid.len() > 128)
        {
            return Err("invalid Firebase project or allowed UID configuration");
        }
        let file: ServiceAccountFile =
            serde_json::from_slice(bytes).map_err(|_| "invalid Firebase service account")?;
        if file.r#type != "service_account"
            || file.project_id != project
            || !file.client_email.ends_with(".gserviceaccount.com")
        {
            return Err("Firebase service account must belong to the configured project");
        }
        let key = EncodingKey::from_rsa_pem(file.private_key.as_bytes())
            .map_err(|_| "invalid Firebase service account key")?;
        let lookup =
            format!("https://identitytoolkit.googleapis.com/v1/projects/{project}/accounts:lookup");
        Ok(Self {
            project, allowed, account: Arc::new(ServiceAccount { email: file.client_email, key }),
            http: client()?, keys: Arc::default(), access: Arc::default(),
            endpoints: Endpoints {
                keys: "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com".into(),
                oauth: "https://oauth2.googleapis.com/token".into(), lookup,
            },
        })
    }

    pub(super) async fn authorize(&self, headers: &HeaderMap) -> Result<String, StatusCode> {
        let token = headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .filter(|v| {
                !v.is_empty() && v.len() <= 16 * 1024 && !v.bytes().any(|c| c.is_ascii_whitespace())
            })
            .ok_or(StatusCode::UNAUTHORIZED)?;
        let head = decode_header(token).map_err(|_| StatusCode::UNAUTHORIZED)?;
        if head.alg != Algorithm::RS256 {
            return Err(StatusCode::UNAUTHORIZED);
        }
        let kid = head
            .kid
            .filter(|s| !s.is_empty() && s.len() <= 128)
            .ok_or(StatusCode::UNAUTHORIZED)?;
        let key = self.key(&kid).await?;
        let mut validation = Validation::new(Algorithm::RS256);
        validation.leeway = 0;
        validation.set_audience(&[&self.project]);
        validation.set_issuer(&[format!("https://securetoken.google.com/{}", self.project)]);
        validation.set_required_spec_claims(&["exp", "iat", "aud", "iss", "sub"]);
        let claims = decode::<Claims>(token, &key, &validation)
            .map_err(|_| StatusCode::UNAUTHORIZED)?
            .claims;
        let now = get_current_timestamp();
        if claims.exp <= now
            || claims.iat > now
            || claims.auth_time > claims.iat
            || claims.aud != self.project
            || claims.iss != format!("https://securetoken.google.com/{}", self.project)
            || claims.sub.is_empty()
            || claims.sub.len() > 128
            || claims.firebase.sign_in_provider != "anonymous"
            || claims.user_id.as_ref().is_some_and(|id| id != &claims.sub)
        {
            return Err(StatusCode::UNAUTHORIZED);
        }
        if !self.allowed.contains(&claims.sub) {
            return Err(StatusCode::FORBIDDEN);
        }
        // A valid JWT is not a grant. No cached account state can bypass disable/revoke.
        let access = self.access_token().await?;
        let response = self
            .http
            .post(&self.endpoints.lookup)
            .bearer_auth(access)
            .json(&json!({"localId":[claims.sub]}))
            .send()
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        let lookup: Lookup = serde_json::from_value(
            read_json(response, 256 * 1024)
                .await
                .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?,
        )
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        let account = lookup
            .users
            .into_iter()
            .find(|user| user.local_id == claims.sub)
            .ok_or(StatusCode::UNAUTHORIZED)?;
        let valid_since = account
            .valid_since
            .as_deref()
            .unwrap_or("0")
            .parse::<u64>()
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        if account.disabled || claims.auth_time < valid_since {
            return Err(StatusCode::UNAUTHORIZED);
        }
        Ok(claims.sub)
    }

    async fn key(&self, kid: &str) -> Result<DecodingKey, StatusCode> {
        let mut keys = self.keys.lock().await;
        let now = get_current_timestamp();
        if keys.expires <= now {
            let response = self
                .http
                .get(&self.endpoints.keys)
                .send()
                .await
                .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
            let max_age = response
                .headers()
                .get(header::CACHE_CONTROL)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| {
                    v.split(',')
                        .find_map(|part| part.trim().strip_prefix("max-age=")?.parse::<u64>().ok())
                })
                .unwrap_or(0)
                .min(24 * 60 * 60);
            let values = serde_json::from_value(
                read_json(response, 256 * 1024)
                    .await
                    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?,
            )
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
            *keys = Keys {
                values,
                expires: now.saturating_add(max_age),
            };
        }
        // Unknown kid fails closed for the cache lifetime; it cannot trigger fetch storms.
        DecodingKey::from_rsa_pem(
            keys.values
                .get(kid)
                .ok_or(StatusCode::UNAUTHORIZED)?
                .as_bytes(),
        )
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)
    }

    async fn access_token(&self) -> Result<String, StatusCode> {
        let mut access = self.access.lock().await;
        let now = get_current_timestamp();
        if access.expires > now {
            return Ok(access.token.clone());
        }
        let assertion = encode(
            &Header::new(Algorithm::RS256),
            &json!({
                "iss":self.account.email,"scope":"https://www.googleapis.com/auth/identitytoolkit",
                "aud":"https://oauth2.googleapis.com/token","iat":now,"exp":now+3600
            }),
            &self.account.key,
        )
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        let response = self
            .http
            .post(&self.endpoints.oauth)
            .form(&[
                ("grant_type", "urn:ietf:params:oauth:grant-type:jwt-bearer"),
                ("assertion", assertion.as_str()),
            ])
            .send()
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        let result: TokenResponse = serde_json::from_value(
            read_json(response, 16 * 1024)
                .await
                .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?,
        )
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        if result.token_type != "Bearer"
            || result.access_token.is_empty()
            || result.access_token.contains(['\r', '\n'])
            || !(60..=3600).contains(&result.expires_in)
        {
            return Err(StatusCode::SERVICE_UNAVAILABLE);
        }
        *access = Access {
            token: result.access_token,
            expires: now + result.expires_in - 30,
        };
        Ok(access.token.clone())
    }
}
