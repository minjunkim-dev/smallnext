# Domain Docs

Smallnext는 **single-context**를 사용한다.
iOS·Android·API를 같은 제품의 구현으로 관리한다. 플랫폼별로 제품 용어집을 나누지 않는다.

## 읽기 순서

1. 코드와 사양을 탐색하기 전에 루트 `CONTEXT.md`를 읽는다.
2. `docs/adr/`에 관련 ADR이 있으면 읽는다.
3. 제품 동작의 확정 답은 해당 GitHub Issue에서 확인한다. 기준은 [DECISIONS](../DECISIONS.md)와 완료한 [개발 사양 지도](https://github.com/minjunkim-dev/smallnext/issues/2)를 참조한다.

`CONTEXT.md`나 관련 ADR이 없으면 그대로 진행한다.
빈 문서나 ADR 디렉터리를 미리 만들지 않는다. 용어나 결정이 확정될 때 필요한 문서만 만든다.

## 용어와 결정

`CONTEXT.md`는 제품 용어집이다.
코드 구현, 기능 사양, 작업 메모를 넣지 않는다.
Issue·사양·테스트에서 같은 대상에는 용어집의 같은 용어를 사용한다.
정의와 다른 의미가 필요하면 먼저 차이를 확인한다.

제품 결정은 GitHub Issue의 확정 답을 따른다.
결정 상세를 다른 문서에 복제하지 않는다.
기존 ADR과 충돌하면 해당 ADR과 충돌 내용을 명시한다.
되돌리기 어렵고 이유를 보존할 필요가 있는 기술 결정만 ADR로 기록한다.

향후 도메인을 실제로 분리하면 `CONTEXT-MAP.md`가 각 context의 용어집을 가리키도록 변경한다.
현재 플랫폼 디렉터리만으로 multi-context를 도입하지 않는다.
