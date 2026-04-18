#!/usr/bin/env python3
"""Interactive installer for GitCodeSummarizer."""

from __future__ import annotations

import getpass
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib import error, request


APP_NAME = "GitCodeSummarizer"
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"
DEFAULT_REMOTE_BASE_URL = "https://api.openai.com/v1"
DEFAULT_INSTALL_DIR_UNIX = Path.home() / "opt" / "git-code-summarizer"
DEFAULT_INSTALL_DIR_WINDOWS = Path.home() / "opt" / "git-code-summarizer"
EXTENSION_VERSION = "0.0.1"

COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_CYAN = "\033[36m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM") not in {None, "dumb"}


def paint(text: str, style: str) -> str:
    if not supports_color():
        return text
    return f"{style}{text}{COLOR_RESET}"


def heading(text: str) -> None:
    print()
    print(paint(text, COLOR_BOLD + COLOR_CYAN))


def info(text: str) -> None:
    print(paint(text, COLOR_CYAN))


def success(text: str) -> None:
    print(paint(text, COLOR_GREEN))


def warning(text: str) -> None:
    print(paint(text, COLOR_YELLOW))


def failure(text: str) -> None:
    print(paint(text, COLOR_RED))


def subtle(text: str) -> str:
    return paint(text, COLOR_DIM)


def prompt_text(label: str, default: Optional[str] = None, *, secret: bool = False) -> str:
    suffix = f" {subtle(f'[default: {default}]')}" if default else ""
    while True:
        raw_prompt = f"{label}{suffix}\n> "
        answer = getpass.getpass(raw_prompt) if secret else input(raw_prompt)
        answer = answer.strip()
        if answer:
            return answer
        if default is not None:
            return default
        warning("Please enter a value.")


def prompt_yes_no(label: str, default: bool) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{label} {subtle(f'[{default_label}]')}\n> ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        warning("Please answer yes or no.")


def prompt_choice(label: str, options: Sequence[Tuple[str, str]], default_key: str) -> str:
    print(label)
    for index, (key, description) in enumerate(options, start=1):
        default_marker = " (default)" if key == default_key else ""
        print(f"  {index}. {description}{default_marker}")
    while True:
        answer = input("> ").strip()
        if not answer:
            return default_key
        if answer.isdigit():
            numeric_index = int(answer) - 1
            if 0 <= numeric_index < len(options):
                return options[numeric_index][0]
        for key, _description in options:
            if answer == key:
                return key
        warning("Choose one of the listed options.")


def source_root() -> Path:
    return Path(__file__).resolve().parent


def default_install_dir() -> Path:
    if os.name == "nt":
        return DEFAULT_INSTALL_DIR_WINDOWS
    return DEFAULT_INSTALL_DIR_UNIX


def default_profile_config_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "summarizer" / "config.json"
        return Path.home() / "AppData" / "Roaming" / "summarizer" / "config.json"

    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "summarizer" / "config.json"
    return Path.home() / ".config" / "summarizer" / "config.json"


def default_launcher_dir() -> Path:
    if os.name == "nt":
        path_dirs = [Path(item) for item in os.environ.get("PATH", "").split(os.pathsep) if item]
        for candidate in path_dirs:
            try:
                candidate.relative_to(Path.home())
            except ValueError:
                continue
            if candidate.exists():
                return candidate
        return Path.home() / "bin"
    return Path.home() / ".local" / "bin"


def read_json_file(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return data


def write_json_file(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_repo_tree(target_root: Path) -> None:
    src = source_root()
    if src == target_root:
        info(f"Using current checkout in place: {target_root}")
        return

    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "node_modules")
    staging_parent = Path(tempfile.mkdtemp(prefix="gcs-install-"))
    staging_root = staging_parent / src.name
    try:
        shutil.copytree(src, staging_root, ignore=ignore)
        target_root.parent.mkdir(parents=True, exist_ok=True)
        if target_root.exists():
            shutil.copytree(staging_root, target_root, dirs_exist_ok=True)
        else:
            shutil.move(str(staging_root), str(target_root))
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def detect_ollama_models() -> List[str]:
    ollama = shutil.which("ollama")
    if not ollama:
        return []
    try:
        completed = subprocess.run(
            [ollama, "list"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    models: List[str] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("name"):
            continue
        models.append(stripped.split()[0])
    return models


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def test_openai_compatible_endpoint(base_url: str, api_key: str) -> Tuple[bool, str]:
    url = f"{normalize_base_url(base_url)}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url=url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"HTTP {exc.code} from {url}: {detail}"
    except error.URLError as exc:
        return False, f"Request to {url} failed: {exc}"
    except json.JSONDecodeError:
        return False, f"Response from {url} was not valid JSON"

    models = payload.get("data")
    if isinstance(models, list):
        return True, f"Endpoint responded and returned {len(models)} models."
    return True, "Endpoint responded with valid JSON."


def profile_config_for_answers(
    provider_kind: str,
    model: str,
    base_url: str,
    api_key: Optional[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "provider": "openai-compatible",
        "model": model,
        "base_url": base_url,
        "system_message": (
            "You are a careful software engineer. Explain the file in concise, clear "
            "language and base the recent-change summary on the provided git history."
        ),
    }
    if provider_kind == "remote":
        payload["api_key"] = api_key or ""
    return payload


def make_unix_launcher(name: str, script_path: Path, python_executable: str) -> str:
    return (
        "#!/bin/sh\n"
        f'exec "{python_executable}" "{script_path}" "$@"\n'
    )


def make_windows_launcher(script_path: Path, python_executable: str) -> str:
    return (
        "@echo off\r\n"
        f'"{python_executable}" "{script_path}" %*\r\n'
    )


def install_launchers(install_root: Path, launcher_dir: Path) -> List[Path]:
    created: List[Path] = []
    launcher_dir.mkdir(parents=True, exist_ok=True)
    python_executable = sys.executable or "python3"

    if os.name == "nt":
        launcher_specs = [
            (launcher_dir / "gcs.cmd", install_root / "summarize-file.py"),
            (launcher_dir / "gcs-cache-glob.cmd", install_root / "gcs-cache-glob.py"),
        ]
        for launcher_path, target_script in launcher_specs:
            launcher_path.write_text(
                make_windows_launcher(target_script, python_executable),
                encoding="utf-8",
                newline="",
            )
            created.append(launcher_path)
    else:
        launcher_specs = [
            (launcher_dir / "gcs", install_root / "summarize-file.py"),
            (launcher_dir / "gcs-cache-glob", install_root / "gcs-cache-glob.py"),
        ]
        for launcher_path, target_script in launcher_specs:
            launcher_path.write_text(
                make_unix_launcher(launcher_path.name, target_script, python_executable),
                encoding="utf-8",
            )
            current_mode = launcher_path.stat().st_mode if launcher_path.exists() else 0
            launcher_path.chmod(current_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXGRP | stat.S_IXOTH)
            created.append(launcher_path)

    return created


def detect_vscode_locations() -> Tuple[Path, Path]:
    home = Path.home()
    candidates: List[Tuple[Path, Path]] = []
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        userprofile = Path(os.environ.get("USERPROFILE", home))
        candidates.extend(
            [
                (appdata / "Code" / "User" / "settings.json", userprofile / ".vscode" / "extensions"),
                (appdata / "Code - Insiders" / "User" / "settings.json", userprofile / ".vscode-insiders" / "extensions"),
                (appdata / "VSCodium" / "User" / "settings.json", userprofile / ".vscode-oss" / "extensions"),
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                (
                    home / "Library" / "Application Support" / "Code" / "User" / "settings.json",
                    home / ".vscode" / "extensions",
                ),
                (
                    home / "Library" / "Application Support" / "Code - Insiders" / "User" / "settings.json",
                    home / ".vscode-insiders" / "extensions",
                ),
                (
                    home / "Library" / "Application Support" / "VSCodium" / "User" / "settings.json",
                    home / ".vscode-oss" / "extensions",
                ),
            ]
        )
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        candidates.extend(
            [
                (config_home / "Code" / "User" / "settings.json", home / ".vscode" / "extensions"),
                (config_home / "Code - Insiders" / "User" / "settings.json", home / ".vscode-insiders" / "extensions"),
                (config_home / "VSCodium" / "User" / "settings.json", home / ".vscode-oss" / "extensions"),
            ]
        )

    for settings_path, extensions_dir in candidates:
        if settings_path.parent.exists() or extensions_dir.exists():
            return settings_path, extensions_dir
    return candidates[0]


def install_vscode_extension(install_root: Path) -> Path:
    settings_path, extensions_dir = detect_vscode_locations()
    extensions_dir.mkdir(parents=True, exist_ok=True)
    extension_target = extensions_dir / f"local.summarize-file-{EXTENSION_VERSION}"
    shutil.copytree(
        install_root / "vscode" / "summarize-file-extension",
        extension_target,
        dirs_exist_ok=True,
    )

    settings = read_json_file(settings_path) if settings_path.exists() else {}
    settings["summarizeFile.scriptPath"] = str((install_root / "summarize-file.py").resolve())
    settings["summarizeFile.pythonExecutable"] = sys.executable or "python3"
    settings["summarizeFile.extraArgs"] = []
    settings["summarizeFile.env"] = {}
    settings.setdefault("summarizeFile.showPreview", True)
    write_json_file(settings_path, settings)
    return extension_target


def detect_sublime_user_dir() -> Path:
    home = Path.home()
    candidates: List[Path] = []
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates.extend(
            [
                appdata / "Sublime Text" / "Packages" / "User",
                appdata / "Sublime Text 3" / "Packages" / "User",
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                home / "Library" / "Application Support" / "Sublime Text" / "Packages" / "User",
                home / "Library" / "Application Support" / "Sublime Text 3" / "Packages" / "User",
            ]
        )
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        candidates.extend(
            [
                config_home / "sublime-text" / "Packages" / "User",
                config_home / "sublime-text-3" / "Packages" / "User",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def install_sublime_plugin(install_root: Path) -> Path:
    user_dir = detect_sublime_user_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    plugin_src = install_root / "sublime-text" / "SummarizeFile"
    for name in [
        "SummarizeFile.py",
        "SummarizeFile.sublime-commands",
        "Default (OSX).sublime-keymap",
    ]:
        shutil.copy2(plugin_src / name, user_dir / name)

    settings_payload = {
        "script_path": str((install_root / "summarize-file.py").resolve()),
        "python_executable": sys.executable or "python3",
        "extra_args": [],
        "env": {},
    }
    write_json_file(user_dir / "SummarizeFile.sublime-settings", settings_payload)
    return user_dir


def collect_answers() -> Dict[str, object]:
    heading(f"{APP_NAME} Installer")
    print("This installer will set up the tool, generate a global profile config,")
    print("and optionally install command-line launchers plus editor integrations.")

    provider_kind = prompt_choice(
        "Which model provider do you want to use?",
        [
            ("local", "Local Ollama / local OpenAI-compatible endpoint"),
            ("remote", "Hosted OpenAI-compatible endpoint"),
        ],
        default_key="local",
    )

    if provider_kind == "local":
        base_url = prompt_text("Base URL for the local endpoint:", DEFAULT_LOCAL_BASE_URL)
        ollama_models = detect_ollama_models()
        if ollama_models:
            info("Detected Ollama models:")
            for name in ollama_models[:12]:
                print(f"  - {name}")
            default_model = ollama_models[0]
        else:
            warning("No local Ollama models detected automatically.")
            default_model = "llama3.1"
        model = prompt_text("Which model should gcs use?", default_model)
        api_key = None
    else:
        base_url = prompt_text("Base URL for the OpenAI-compatible endpoint:", DEFAULT_REMOTE_BASE_URL)
        model = prompt_text("Which model should gcs use?")
        api_key = prompt_text("API key to store in the global profile config:", secret=True)
        info("Testing the endpoint with a lightweight /models request...")
        ok, message = test_openai_compatible_endpoint(base_url, api_key)
        if ok:
            success(message)
        else:
            warning(message)
            if not prompt_yes_no("Continue anyway?", True):
                raise SystemExit(1)

    install_path = Path(
        prompt_text("Where should the repo be installed?", str(default_install_dir()))
    ).expanduser().resolve()
    profile_config_path = default_profile_config_path()
    install_cli = prompt_yes_no("Install command-line launchers for gcs and gcs-cache-glob?", True)
    launcher_dir = None
    if install_cli:
        launcher_dir = Path(
            prompt_text("Launcher directory:", str(default_launcher_dir()))
        ).expanduser().resolve()
    install_vscode = prompt_yes_no("Install the VS Code extension and configure it?", True)
    install_sublime = prompt_yes_no("Install the Sublime Text plugin and configure it?", False)

    return {
        "provider_kind": provider_kind,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "install_path": install_path,
        "profile_config_path": profile_config_path,
        "install_cli": install_cli,
        "launcher_dir": launcher_dir,
        "install_vscode": install_vscode,
        "install_sublime": install_sublime,
    }


def print_summary(answers: Dict[str, object]) -> None:
    heading("Planned Changes")
    print(f"Install location: {answers['install_path']}")
    print(f"Profile config:   {answers['profile_config_path']}")
    print(f"Provider:         {answers['provider_kind']}")
    print(f"Model:            {answers['model']}")
    print(f"Base URL:         {answers['base_url']}")
    print(f"CLI launchers:    {'yes' if answers['install_cli'] else 'no'}")
    print(f"VS Code:          {'yes' if answers['install_vscode'] else 'no'}")
    print(f"Sublime Text:     {'yes' if answers['install_sublime'] else 'no'}")


def perform_install(answers: Dict[str, object]) -> None:
    install_root = Path(answers["install_path"])
    provider_kind = str(answers["provider_kind"])
    model = str(answers["model"])
    base_url = str(answers["base_url"])
    api_key = answers["api_key"]
    profile_config_path = Path(answers["profile_config_path"])

    heading("Installing Files")
    copy_repo_tree(install_root)
    success(f"Installed repo files into {install_root}")

    profile_config = profile_config_for_answers(
        provider_kind=provider_kind,
        model=model,
        base_url=base_url,
        api_key=str(api_key) if api_key is not None else None,
    )
    write_json_file(profile_config_path, profile_config)
    success(f"Wrote profile config to {profile_config_path}")

    if answers["install_cli"]:
        launcher_dir = Path(answers["launcher_dir"])
        try:
            created = install_launchers(install_root, launcher_dir)
            success(f"Installed launchers into {launcher_dir}")
            for launcher in created:
                print(f"  - {launcher}")
        except OSError as exc:
            warning(f"Failed to install command-line launchers: {exc}")

    if answers["install_vscode"]:
        try:
            extension_path = install_vscode_extension(install_root)
            success(f"Installed VS Code extension into {extension_path}")
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            warning(f"Failed to install VS Code integration: {exc}")

    if answers["install_sublime"]:
        try:
            sublime_dir = install_sublime_plugin(install_root)
            success(f"Installed Sublime Text plugin into {sublime_dir}")
        except OSError as exc:
            warning(f"Failed to install Sublime Text integration: {exc}")


def print_next_steps(answers: Dict[str, object]) -> None:
    heading("Next Steps")
    print("1. If VS Code or Sublime Text was open during install, restart it.")
    if answers["install_cli"]:
        launcher_dir = Path(answers["launcher_dir"])
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if str(launcher_dir) not in path_entries:
            print(f"2. Add {launcher_dir} to PATH if it is not already available in new shells.")
        else:
            print("2. CLI launchers should already be reachable from your PATH.")
    else:
        print("2. You can run the tool directly with Python from the install directory.")
    print("3. Try: gcs README.md --mode request")


def main(argv: Sequence[str]) -> int:
    if any(arg in {"-h", "--help"} for arg in argv):
        print("Interactive installer for GitCodeSummarizer.")
        print("Run without arguments and answer the prompts.")
        return 0

    answers = collect_answers()
    print_summary(answers)
    if not prompt_yes_no("Proceed with installation?", True):
        warning("Installation cancelled.")
        return 1

    try:
        perform_install(answers)
    except KeyboardInterrupt:
        warning("Installation cancelled.")
        return 1
    except Exception as exc:
        failure(f"Installation failed: {exc}")
        return 1

    print_next_steps(answers)
    success("Install complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
