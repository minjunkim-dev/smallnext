use super::{client, read_json};
use axum::http::{HeaderMap, StatusCode, header};
use jsonwebtoken::{
    Algorithm, DecodingKey, Validation, decode, decode_header, get_current_timestamp,
    jwk::{AlgorithmParameters, EllipticCurve, JwkSet, KeyAlgorithm, KeyOperations, PublicKeyUse},
};
use serde::Deserialize;
use sqlx::PgPool;
use std::{collections::HashSet, sync::Arc};
use tokio::sync::Mutex;

#[derive(Clone)]
pub(super) struct Supabase {
    issuer: String,
    publishable_key: String,
    /// None is the explicit public beta mode.
    pub(super) allowed: Option<HashSet<String>>,
    http: reqwest::Client,
    keys: Arc<Mutex<Keys>>,
    pub(super) endpoints: Endpoints,
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{Json, Router, routing::get};
    use jsonwebtoken::{EncodingKey, Header, encode, jwk::Jwk};
    use serde_json::json;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn configuration_rejects_secret_keys_unsafe_urls_and_invalid_uids() {
        let allowed: HashSet<String> = ["11111111-1111-4111-8111-111111111111".into()].into();
        for url in [
            "http://project.supabase.co",
            "https://user:pass@project.supabase.co",
            "https://project.supabase.co/path",
            "https://project.supabase.co?value=1",
        ] {
            assert!(
                Supabase::new(
                    url.into(),
                    "sb_publishable_test".into(),
                    Some(allowed.clone())
                )
                .is_err()
            );
        }
        for key in ["sb_secret_test", "legacy-token", "sb_publishable_"] {
            assert!(
                Supabase::new(
                    "https://project.supabase.co".into(),
                    key.into(),
                    Some(allowed.clone())
                )
                .is_err()
            );
        }
        assert!(
            Supabase::new(
                "https://project.supabase.co".into(),
                "sb_publishable_test-A".into(),
                Some(allowed)
            )
            .is_ok()
        );
        for allowed in [Some(HashSet::new()), Some(["invalid".into()].into())] {
            assert!(
                Supabase::new(
                    "https://project.supabase.co".into(),
                    "sb_publishable_test-A".into(),
                    allowed
                )
                .is_err()
            );
        }
        // Public mode is a distinct None, never an accidentally empty allowlist.
        assert!(
            Supabase::new(
                "https://project.supabase.co".into(),
                "sb_publishable_test-A".into(),
                None
            )
            .is_ok()
        );
        assert!(!valid_uuid("invalid"));
    }

    #[tokio::test]
    async fn asymmetric_jwks_verify_both_algorithms_and_reject_key_confusion_without_refetch() {
        for (algorithm, private) in [
            (Algorithm::RS256, super::super::test_key::PRIVATE),
            (Algorithm::ES256, super::super::test_key::EC_PRIVATE),
        ] {
            let signing = match algorithm {
                Algorithm::RS256 => EncodingKey::from_rsa_pem(private.as_bytes()).unwrap(),
                _ => EncodingKey::from_ec_pem(private.as_bytes()).unwrap(),
            };
            let mut jwk = Jwk::from_encoding_key(&signing, algorithm).unwrap();
            jwk.common.key_id = Some("current".into());
            let count = Arc::new(AtomicUsize::new(0));
            let requests = count.clone();
            let value = json!({"keys":[jwk]});
            let app = Router::new().route(
                "/keys",
                get(move || {
                    let value = value.clone();
                    requests.fetch_add(1, Ordering::SeqCst);
                    async move { ([("Cache-Control", "max-age=600")], Json(value)) }
                }),
            );
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let address = listener.local_addr().unwrap();
            let server = tokio::spawn(async move {
                axum::serve(listener, app).await.unwrap();
            });
            let mut auth = Supabase::new(
                "https://project.supabase.co".into(),
                "sb_publishable_test".into(),
                Some(["11111111-1111-4111-8111-111111111111".into()].into()),
            )
            .unwrap();
            auth.endpoints.keys = format!("http://{address}/keys");
            let key = auth.key("current", algorithm).await.unwrap();
            let mut header = Header::new(algorithm);
            header.kid = Some("current".into());
            let token = encode(
                &header,
                &json!({"exp":get_current_timestamp()+60}),
                &signing,
            )
            .unwrap();
            assert!(decode::<serde_json::Value>(&token, &key, &Validation::new(algorithm)).is_ok());
            assert!(matches!(
                auth.key("unknown", algorithm).await,
                Err(StatusCode::UNAUTHORIZED)
            ));
            let wrong = if algorithm == Algorithm::RS256 {
                Algorithm::ES256
            } else {
                Algorithm::RS256
            };
            assert!(matches!(
                auth.key("current", wrong).await,
                Err(StatusCode::UNAUTHORIZED)
            ));
            assert_eq!(count.load(Ordering::SeqCst), 1);
            {
                let mut cache = auth.keys.lock().await;
                let duplicate = cache.values[0].clone();
                cache.values.push(duplicate);
            }
            assert!(matches!(
                auth.key("current", algorithm).await,
                Err(StatusCode::UNAUTHORIZED)
            ));
            auth.keys.lock().await.values.pop();
            auth.keys.lock().await.values[0].common.public_key_use = Some(PublicKeyUse::Encryption);
            assert!(matches!(
                auth.key("current", algorithm).await,
                Err(StatusCode::UNAUTHORIZED)
            ));
            server.abort();
        }
    }
}

#[derive(Clone)]
pub(super) struct Endpoints {
    pub keys: String,
    pub user: String,
}

#[derive(Default)]
struct Keys {
    values: Vec<jsonwebtoken::jwk::Jwk>,
    expires: u64,
}

#[derive(Deserialize)]
struct Claims {
    sub: String,
    exp: u64,
    iat: u64,
    aud: String,
    iss: String,
    role: String,
    is_anonymous: bool,
    session_id: String,
}

#[derive(Deserialize)]
struct User {
    id: String,
    is_anonymous: bool,
}

pub(super) fn valid_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()
            }
        })
}

impl Supabase {
    pub(super) fn new(
        url: String,
        publishable_key: String,
        allowed: Option<HashSet<String>>,
    ) -> Result<Self, &'static str> {
        let parsed = reqwest::Url::parse(&url).map_err(|_| "invalid Supabase configuration")?;
        if parsed.scheme() != "https"
            || parsed.host_str().is_none()
            || !parsed.username().is_empty()
            || parsed.password().is_some()
            || !matches!(parsed.path(), "" | "/")
            || parsed.query().is_some()
            || parsed.fragment().is_some()
            || !publishable_key.starts_with("sb_publishable_")
            || !publishable_key
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
            || publishable_key.len() <= "sb_publishable_".len()
            || allowed
                .as_ref()
                .is_some_and(|a| a.is_empty() || a.iter().any(|uid| !valid_uuid(uid)))
        {
            return Err("invalid Supabase configuration");
        }
        let issuer = format!("{}/auth/v1", url.trim_end_matches('/'));
        Ok(Self {
            endpoints: Endpoints {
                keys: format!("{issuer}/.well-known/jwks.json"),
                user: format!("{issuer}/user"),
            },
            issuer,
            publishable_key,
            allowed,
            http: client()?,
            keys: Arc::default(),
        })
    }

    pub(super) async fn authorize(
        &self,
        headers: &HeaderMap,
        database: &PgPool,
    ) -> Result<String, StatusCode> {
        let token = headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .filter(|v| {
                !v.is_empty() && v.len() <= 16 * 1024 && !v.bytes().any(|c| c.is_ascii_whitespace())
            })
            .ok_or(StatusCode::UNAUTHORIZED)?;
        let head = decode_header(token).map_err(|_| StatusCode::UNAUTHORIZED)?;
        if !matches!(head.alg, Algorithm::ES256 | Algorithm::RS256) {
            return Err(StatusCode::UNAUTHORIZED);
        }
        let kid = head
            .kid
            .filter(|s| !s.is_empty() && s.len() <= 128)
            .ok_or(StatusCode::UNAUTHORIZED)?;
        let key = self.key(&kid, head.alg).await?;
        let mut validation = Validation::new(head.alg);
        validation.leeway = 0;
        validation.validate_nbf = true;
        validation.set_audience(&["authenticated"]);
        validation.set_issuer(&[&self.issuer]);
        validation.set_required_spec_claims(&["exp", "iat", "aud", "iss", "sub"]);
        let claims = decode::<Claims>(token, &key, &validation)
            .map_err(|_| StatusCode::UNAUTHORIZED)?
            .claims;
        let now = get_current_timestamp();
        if claims.exp <= now
            || claims.iat > now
            || claims.iat >= claims.exp
            || claims.aud != "authenticated"
            || claims.iss != self.issuer
            || claims.role != "authenticated"
            || !claims.is_anonymous
            || !valid_uuid(&claims.sub)
            || !valid_uuid(&claims.session_id)
        {
            return Err(StatusCode::UNAUTHORIZED);
        }
        if self
            .allowed
            .as_ref()
            .is_some_and(|a| !a.contains(&claims.sub))
        {
            return Err(StatusCode::FORBIDDEN);
        }
        // A signed JWT does not prove that the account or its session still exists.
        let response = self
            .http
            .get(&self.endpoints.user)
            .header("apikey", &self.publishable_key)
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        if matches!(response.status().as_u16(), 401 | 403 | 404) {
            return Err(StatusCode::UNAUTHORIZED);
        }
        let user: User = serde_json::from_value(
            read_json(response, 256 * 1024)
                .await
                .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?,
        )
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        if user.id != claims.sub || !user.is_anonymous {
            return Err(StatusCode::UNAUTHORIZED);
        }
        // No cached account/session result can bypass logout, deletion or a ban.
        let active: bool = sqlx::query_scalar("SELECT smallnext_session_active($1, $2)")
            .bind(&claims.sub)
            .bind(&claims.session_id)
            .fetch_one(database)
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        if !active {
            return Err(StatusCode::UNAUTHORIZED);
        }
        Ok(claims.sub)
    }

    async fn key(&self, kid: &str, algorithm: Algorithm) -> Result<DecodingKey, StatusCode> {
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
                .min(10 * 60);
            let jwks: JwkSet = serde_json::from_value(
                read_json(response, 256 * 1024)
                    .await
                    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?,
            )
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
            *keys = Keys {
                values: jwks.keys,
                expires: now.saturating_add(max_age),
            };
        }
        // Unknown kid fails closed for the cache lifetime; it cannot trigger fetch storms.
        let mut matching = keys
            .values
            .iter()
            .filter(|key| key.common.key_id.as_deref() == Some(kid));
        let key = matching.next().ok_or(StatusCode::UNAUTHORIZED)?;
        if matching.next().is_some() {
            return Err(StatusCode::UNAUTHORIZED);
        }
        let compatible = matches!(
            (&key.algorithm, key.common.key_algorithm, algorithm),
            (
                AlgorithmParameters::RSA(_),
                Some(KeyAlgorithm::RS256),
                Algorithm::RS256
            )
        ) || matches!((&key.algorithm, key.common.key_algorithm, algorithm),
                (AlgorithmParameters::EllipticCurve(parameters), Some(KeyAlgorithm::ES256), Algorithm::ES256)
                    if parameters.curve == EllipticCurve::P256);
        if !compatible
            || key
                .common
                .public_key_use
                .as_ref()
                .is_some_and(|v| *v != PublicKeyUse::Signature)
            || key
                .common
                .key_operations
                .as_ref()
                .is_some_and(|v| !v.contains(&KeyOperations::Verify))
        {
            return Err(StatusCode::UNAUTHORIZED);
        }
        DecodingKey::from_jwk(key).map_err(|_| StatusCode::SERVICE_UNAVAILABLE)
    }
}
