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
IOS_FILE = Path("apps/ios/Config/Local.xcconfig")


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
    files = [root / SERVER_FILE, root / IOS_FILE]
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

    print("3. Supabase PostgreSQL을 준비하십시오. TLS 접속 URL을 받으십시오.")
    print("Free에는 자동 백업이 없습니다. 실제 운영 전에 백업 조건을 별도로 확정하십시오.")
    print("공급자·지역·승인한 백업 조건과 미확인 범위를 #162에 기록하십시오.")
    database = ask("DATABASE_URL")
    if confirm("실제 운영용 백업 조건을 확정했습니까? [y/N] ").lower() != "y":
        return False
    print("4. Supabase 프로젝트에서 Anonymous 인증을 켜십시오. Data API는 사용하지 않습니다.")
    open_page("https://supabase.com/dashboard")
    project_url = ask("SUPABASE_URL")
    client_key = ask("SUPABASE_PUBLISHABLE_KEY (공개 client 설정; secret key 아님)")
    print("5. 앱 테이블·인증 확인 함수의 client 접근 차단과 서버 전용 DB 역할을 확인하십시오.")
    uids = ask("AI_ALLOWED_SUPABASE_UIDS (이미 확인한 본인 익명 UID만 입력; 없으면 비워 두고 #47에서 준비)", optional=True)
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
    # Auth setup must preserve optional Crashlytics settings in the shared local file.
    previous_ios = files[1].read_text() if files[1].exists() else ""
    retained = [line for line in previous_ios.splitlines()
                if not any(re.match(r"\s*" + re.escape(key) + r"\s*=", line) for key in ios)]
    ios_text = "\n".join(retained) + "\n// Local authentication configuration. Do not commit.\n" + "".join(f"{key} = {xcconfig_value(value)}\n" for key, value in ios.items())
    save_private(files[0], server_text)
    save_private(files[1], ios_text)
    print("서버 환경 파일과 iOS 설정 파일을 권한 0600으로 저장했습니다.")
    print("#162에 공급자·지역·백업 조건·DB 권한만 기록하십시오. UID·키·토큰은 기록하지 마십시오.")
    print("실제 배포는 #164에서 수행하십시오. 서버 AI 활성화와 제공사 키 생성은 #47에서 수행하십시오.")
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
