#!/usr/bin/env python3
"""사람이 실행하는 #162 준비 wizard. 계정 생성과 배포는 수행하지 않는다."""

import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
import warnings
import webbrowser
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVER_FILE = Path("infra/production/.env.production")
MIGRATION_FILE = Path("infra/production/.env.migration")
IOS_FILE = Path("apps/ios/Config/Local.Release.xcconfig")


def env_value(value):
    if any(character in value for character in "\r\n\0"):
        raise ValueError("한 줄 값을 입력하십시오.")
    if "\\" in value:
        raise ValueError("URL의 역슬래시는 percent-encoding으로 입력하십시오.")
    # Compose single quotes prevent interpolation; do not source this file in a shell.
    return "'" + value.replace("'", "\\'") + "'"


def xcconfig_value(value):
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
        raise ValueError("iOS 설정에 허용되지 않는 문자가 있습니다.")
    return value.replace("//", "/$()/")


def save_private(path, content):
    if path.is_symlink():
        raise ValueError("설정 파일의 symlink를 제거하십시오.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env.prepare-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(root=ROOT, prompt=getpass.getpass, confirm=input, open_page=webbrowser.open):
    server_file, migration_file, ios_file = [root / name for name in (SERVER_FILE, MIGRATION_FILE, IOS_FILE)]
    files = [server_file, migration_file, ios_file]
    if any(path.is_symlink() for path in files):
        raise ValueError("설정 파일의 symlink를 제거하십시오.")
    for path in files:
        if path.exists() and confirm(f"{path.name}에 저장한 값이 있습니다. 덮어쓸까요? [y/N] ").lower() != "y":
            print("취소했습니다. 기존 파일을 유지합니다.")
            return False

    def ask(label, optional=False):
        value = prompt(label + " (입력 숨김): ").strip()
        if (not value and not optional) or any(character in value for character in "\r\n\0"):
            raise ValueError("빈 값 또는 여러 줄 값을 저장하지 않습니다.")
        return value

    print("1. Linux 서버를 준비하십시오. Docker Compose를 설치하고 방화벽의 80/443을 허용하십시오.")
    open_page("https://docs.docker.com/engine/install/")
    if confirm("서버 준비를 확인했습니까? [y/N] ").lower() != "y":
        return False
    print("2. 도메인의 DNS A/AAAA를 서버에 연결하십시오. DNS 관리 화면에서 전파를 확인하십시오.")
    domain = ask("API 도메인")
    origin = urlsplit("https://" + domain)
    if not origin.hostname or origin.netloc != domain or any(part for part in (origin.path, origin.query, origin.fragment)) or origin.username or origin.password:
        raise ValueError("API 도메인만 입력하십시오.")
    xcconfig_value("https://" + domain)

    print("3. Supabase PostgreSQL의 runtime 로그인과 schema-owner 로그인을 분리하십시오.")
    print("runtime에는 smallnext_api 역할만 부여하십시오. schema owner는 migrate service에서만 사용하십시오.")
    print("두 접속 URL에 sslmode=verify-full을 사용하십시오. 사용자 CA가 필요하면 sslrootcert에 컨테이너의 CA mount 경로를 지정하십시오.")
    print("CA 파일을 Git에서 제외하고 read-only로 mount하십시오. 로컬 경로와 컨테이너 경로를 구분하십시오.")
    database = ask("RUNTIME_DATABASE_URL (API 전용)")
    migration_database = ask("MIGRATION_DATABASE_URL (schema owner; migrate service 전용)")
    if database == migration_database:
        raise ValueError("runtime과 schema-owner 접속 URL을 분리하십시오.")
    print("Free에는 자동 백업이 없습니다. #170의 확정 조건은 예산 데이터만 12시간마다 암호화하여 최대 7일 보관하는 것입니다.")
    print("RPO와 RTO는 각각 24시간입니다. 익명 계정·세션은 백업하지 않습니다. 계정 유실 시 재생성합니다.")
    print("별도 백업 도구에서 smallnext_backup 전용 접속과 암호화 저장 위치를 설정하십시오. 이 wizard는 백업을 실행하지 않습니다.")
    print("공급자·지역·백업과 복원 검증 결과·미확인 범위를 #162에 기록하십시오.")
    if confirm("확정한 백업 조건과 별도 백업 설정을 확인했습니까? [y/N] ").lower() != "y":
        return False
    print("4. Supabase 프로젝트에서 Anonymous 인증을 켜십시오. Data API는 사용하지 않습니다.")
    open_page("https://supabase.com/dashboard")
    project_url = ask("SUPABASE_URL")
    client_key = ask("SUPABASE_PUBLISHABLE_KEY (공개 client 설정; secret key 아님)")
    if not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", client_key):
        raise ValueError("sb_publishable_로 시작하는 공개 client 키를 입력하십시오.")
    print("5. 앱 테이블·인증 확인 함수의 client 접근 차단과 서버 전용 DB 역할을 확인하십시오.")
    uids = ask("AI_ALLOWED_SUPABASE_UIDS (이미 확인한 본인 익명 UID만 입력; 없으면 비워 두고 #242에서 준비)", optional=True)
    if confirm("DB 최소 권한과 파일 보호를 확인했습니까? [y/N] ").lower() != "y":
        return False

    server = {
        "API_DOMAIN": domain, "DATABASE_URL": database,
        "SUPABASE_URL": project_url, "SUPABASE_PUBLISHABLE_KEY": client_key,
        "AI_ALLOWED_SUPABASE_UIDS": uids,
    }
    ios = {
        "SMALLNEXT_API_BASE_URL": "https://" + domain,
        "SMALLNEXT_SUPABASE_URL": project_url, "SMALLNEXT_SUPABASE_PUBLISHABLE_KEY": client_key,
    }
    server_text = "# AI OFF. Compose --env-file only; do not shell-source.\n" + "".join(f"{key}={env_value(value)}\n" for key, value in server.items())
    migration_text = "# Schema owner. migrate service only; never pass to the API or shell-source.\nDATABASE_URL=" + env_value(migration_database) + "\n"
    # Auth setup must preserve optional Crashlytics settings in the shared local file.
    previous_ios = ios_file.read_text() if ios_file.exists() else ""
    retained = [line for line in previous_ios.splitlines()
                if not any(re.match(r"\s*" + re.escape(key) + r"\s*=", line) for key in ios)]
    ios_text = "\n".join(retained) + "\n// Local authentication configuration. Do not commit.\n" + "".join(f"{key} = {xcconfig_value(value)}\n" for key, value in ios.items())
    save_private(server_file, server_text)
    save_private(migration_file, migration_text)
    save_private(ios_file, ios_text)
    print("runtime 환경 파일·migration 환경 파일·Release iOS 설정 파일을 각각 권한 0600으로 저장했습니다.")
    print("API에는 runtime 환경 파일만 전달하십시오. API_AUTO_MIGRATE=0은 운영 Compose가 고정합니다.")
    print("#162에 공급자·지역·백업 조건·DB 권한만 기록하십시오. UID·키·토큰은 기록하지 마십시오.")
    print("실제 배포는 #164에서 수행하십시오. 서버 AI 활성화와 제공사 키 생성은 #242에서 수행하십시오.")
    return True


def main():
    if not sys.stdin.isatty():
        print("FAIL: 값을 숨길 수 있는 대화형 터미널에서 실행하십시오.")
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return 0 if prepare() else 1
    except (OSError, ValueError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("FAIL: 준비를 중단했습니다. 입력 값은 출력하지 않습니다.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
