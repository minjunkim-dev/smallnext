# PostgreSQL CA

Supabase의 공식 CA를 `supabase-ca.crt`로 내려받는다. 값은 Git에 넣지 않는다.
API와 migration 컨테이너는 이 폴더를 `/etc/smallnext/tls`에 읽기 전용으로 연결한다.
DB URL에 `sslmode=verify-full&sslrootcert=/etc/smallnext/tls/supabase-ca.crt`를 지정한다.
인증서 갱신 후 연결 검사를 수행한다.
