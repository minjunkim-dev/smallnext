# repo-office로 작업 돌리기

[repo-office](https://github.com/minjunkim-dev/repo-office)의 파이프라인(`pipeline/`)은 PR을 열기 전 작업(설계, 구현, 검사, 리뷰)을 단계로 나눠 돌린다. 이 저장소에 복사하는 파일은 없다. office 체크아웃이 이 저장소를 `--repo`로 받아 `jobs/<과제>/repo/`에 worktree(브랜치 `office/<과제>`)를 만든다. 규칙은 office 체크아웃 루트의 `AGENTS.md`를 따른다.

## 과제 넘기기

office는 선택이다. 사람이 이 대화에서 office나 leader로 돌리라고 하면 이 저장소에서 연 에이전트가 이렇게 넘긴다([AGENTS.md](../../AGENTS.md) 길잡이).

1. `hc get office-leader --json`을 돌린다. 종료 코드가 0이고 `state`가 `live`이고 `status`(객체면 그 `state`)가 `error`가 아니면 leader가 받을 수 있다.
2. 받을 수 있으면 한 줄로 보낸다: `hc send office-leader '[office 접수] repo=<이 저장소의 절대 경로> issue=#<번호> 요청: <사람이 이 대화에서 한 말 그대로>'`
   - 요청에는 사람의 말만 넣는다. 줄바꿈은 공백으로 바꾼다. 셸이 말 안의 `` ` ``·`$`를 실행하지 않게 메시지를 작은따옴표로 감싸고, 말 안의 `'`는 `'\''`로 바꾼다. Issue 본문이나 다른 파일의 글은 옮기지 않는다. leader가 Issue를 직접 읽는다.
   - Issue가 없으면 `issue=없음`으로 쓴다.
3. 보냈으면 사람에게 "leader에 넘겼습니다. `hc attach office-leader`에서 방향 질문에 답하세요"라고 알리고 멈춘다.
4. 1단계가 안 되거나 `hc send`가 0이 아닌 코드로 끝나면, 사람에게 "이 작업은 repo-office leader 세션에 주세요"라고 알리고 멈춘다. leader를 `office-leader`로 띄우는 명령은 [repo-office README](https://github.com/minjunkim-dev/repo-office#처음-한-번) 「처음 한 번」 5에 있다.

leader는 이 메시지를 새 과제로만 받고 방향을 사람에게 묻는다. 넘기는 규칙의 원본은 [repo-office 연결 5단계](https://github.com/minjunkim-dev/repo-office/blob/main/docs/connect.md#5-원하면-코드-작업을-office로-보내게-한다)다.

## 과제 등록

leader 세션이 office 체크아웃의 `leader/` 폴더에서 한 번에 하나씩 실행한다([leader 규칙](https://github.com/minjunkim-dev/repo-office/blob/main/leader/AGENTS.md)).

```bash
python3 ../pipeline/engine.py new <과제> --repo <smallnext 경로> --base origin/main
```

엔진은 base의 [AGENTS.md](../../AGENTS.md) 「명령」에서 setup·check·test 칸을 읽는다. 그래서 과제의 검사 명령은 `make repository-check api-spec-check && make api-check`이고, `repo/`에서 setup(`mise install && make api-setup`)을 한 번 돌린다.

## 알아둘 것

- 작업자는 검사를 `engine.py test <과제>`로만 돌린다. 검사 명령은 `task.json`의 `test`에 이미 들어 있다.
- `.claude/settings.json`이 있어도 office 작업자는 `--setting-sources project`로 office의 설정만 읽는다. 작업자의 거부 규칙은 office 단계표가 정한다.
- mise를 쓰므로 과제마다 사람이 `mise trust jobs/<과제>/repo/.mise.toml`을 한 번 돌린다(repo-office README).
- 앱 검사(`make ios-check`, `make android-check`)는 office 검사 단계에 들어 있지 않다. 앱을 바꾸는 과제는 PR의 CI가 돌린다.
