#!/usr/bin/env python3
"""Resolve pinned tools and reject incompatible local or CI environments."""
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / ".ci/toolchains.json").read_text())


def rust_version():
    text = (ROOT / "rust-toolchain.toml").read_text()
    return re.search(r'channel\s*=\s*"([0-9.]+)"', text).group(1)


def output(command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def require(label, actual, expected):
    if actual != expected:
        raise ValueError(f"{label}: expected {expected}; found {actual}")
    print(f"{label}: {actual}")


def check_java():
    java = str(Path(os.environ["JAVA_HOME"]) / "bin/java") if os.environ.get("JAVA_HOME") else "java"
    version = output([java, "-XshowSettings:properties", "-version"])
    match = re.search(r"java.runtime.version\s*=\s*(\S+)", version)
    require("Java runtime", match.group(1) if match else "unknown", config()["java_runtime"])


def check_android():
    check_java()
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT", ""))
    if sdk == Path("."):
        raise ValueError("Set ANDROID_HOME to the Android SDK directory")
    pins = config()
    for package in (f'platforms/android-{pins["android_platform"]}',
                    f'build-tools/{pins["android_build_tools"]}'):
        if not (sdk / package).is_dir():
            raise ValueError(f"Missing Android SDK package: {package}; run make android-sdk")
        print(f"Android package: {package}")


def android_avd_image():
    """CI 기기 테스트 이미지에서 ABI만 이 호스트 CPU에 맞춘다. Apple silicon은 x86_64 이미지를 실행하지 못한다."""
    image = config()["android_system_image"]
    abi = "arm64-v8a" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    return f'{image.rsplit(";", 1)[0]};{abi}'


def install_android_avd():
    """CI의 `Start emulator` 단계와 같은 이미지·기본 기기로 `SmallnextCI` AVD를 만든다."""
    check_java()
    sdk = Path(os.environ["ANDROID_HOME"])
    image = android_avd_image()
    subprocess.run([str(sdk / "cmdline-tools/latest/bin/sdkmanager"), image, "emulator"], check=True)
    subprocess.run([str(sdk / "cmdline-tools/latest/bin/avdmanager"), "create", "avd", "--force",
                    "--name", "SmallnextCI", "--package", image], input="no\n", text=True, check=True)
    print(f"AVD SmallnextCI: {image}")


def check_ios():
    pins = config()
    version = output(["xcodebuild", "-version"])
    require("Xcode", version, f'Xcode {pins["xcode"]}\nBuild version {pins["xcode_build"]}')
    require("iOS simulator SDK", output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"]), pins["ios_sdk"])


def github_outputs():
    pins = config()
    values = {"java": pins["java"], "rust": rust_version(),
              "android-system-image": pins["android_system_image"],
              "developer-dir": f'/Applications/Xcode_{pins["xcode"]}.app/Contents/Developer'}
    with open(os.environ["GITHUB_OUTPUT"], "a") as target:
        for name, value in values.items():
            target.write(f"{name}={value}\n")


def main():
    action = sys.argv[1]
    if action == "github":
        github_outputs()
    elif action == "rust-install":
        subprocess.run(["rustup", "toolchain", "install", rust_version(), "--profile", "minimal",
                        "--component", "clippy", "--component", "rustfmt"], check=True)
    elif action == "rust":
        require("Rust", output(["rustc", "--version"]).split()[1], rust_version())
    elif action == "java":
        check_java()
    elif action == "android":
        check_android()
    elif action == "android-install":
        check_java()
        sdk = Path(os.environ["ANDROID_HOME"])
        pins = config()
        subprocess.run([str(sdk / "cmdline-tools/latest/bin/sdkmanager"),
                        f'platforms;android-{pins["android_platform"]}',
                        f'build-tools;{pins["android_build_tools"]}', "platform-tools"], check=True)
    elif action == "android-avd":
        install_android_avd()
    elif action == "ios":
        check_ios()
    else:
        raise ValueError(f"Unknown environment action: {action}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Environment check failed: {error}", file=sys.stderr)
        sys.exit(1)
