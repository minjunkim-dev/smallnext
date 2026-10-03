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
현재는 상태 확인 응답만 정의했습니다.
인증, 제품 데이터, 동기화 계약은 아직 구현하지 않았습니다.
