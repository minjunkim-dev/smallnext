# 공통 계약

API 명세의 원본은 Rust의 utoipa 선언입니다.
`openapi.json`은 생성 결과입니다. 직접 편집하지 않습니다.

명세 갱신:

```sh
make api-spec
```

명세 일치 검사:

```sh
make api-spec-check
```

`fixtures/`에는 세 프로젝트가 같은 의미를 확인할 테스트 데이터를 둡니다.
현재는 상태 확인 응답과 AI 제안 compact 계약을 정의했습니다.
`insufficient-info.json`은 정보 부족의 생성·공개 응답과 독립 검사 합성 사례입니다. Rust·iOS 전송/진행·구독 어댑터의 형식 회귀가 함께 사용하며 실제 모델 품질을 증명하지 않습니다.
`suggestion-compact.json`은 Rust `suggestion/compact.rs`의 system prompt, schema, 요청 종류별 허용 상태입니다.
Rust 테스트와 `scripts/test_oauth_contract.py`가 같은 파일과 비교합니다.
계약을 바꾸면 `UPDATE_CONTRACT_FIXTURES=1 cargo test --manifest-path services/api/Cargo.toml --lib compact_contract`로 다시 만들고 `scripts/oauth_quality.py`를 맞춥니다.
인증, 제품 데이터, 동기화 계약은 아직 구현하지 않았습니다.
