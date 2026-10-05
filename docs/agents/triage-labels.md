# Triage Labels

설치된 engineering skill은 다음 역할을 같은 이름의 GitHub 라벨로 적용한다.
기존에 사용자가 확인한 기본 라벨을 유지한다.

| Skill 역할 | GitHub 라벨 | 의미 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 담당자의 초기 검토가 필요하다. |
| `needs-info` | `needs-info` | 질문을 해결할 추가 정보가 필요하다. |
| `ready-for-agent` | `ready-for-agent` | 조건을 확정해 에이전트가 구현할 수 있다. |
| `ready-for-human` | `ready-for-human` | 사람이 직접 처리해야 한다. |
| `wontfix` | `wontfix` | 처리하지 않기로 결정했다. |

skill이 역할을 지정하면 위 GitHub 라벨을 사용한다.
필요한 라벨이 없으면 같은 이름으로 생성한다.
다른 이름의 중복 라벨을 임의로 만들지 않는다.
제품 결정과 사람의 병합 책임은 [WORKFLOW](../WORKFLOW.md)를 따른다.
