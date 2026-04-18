#!/usr/bin/env python3
"""Build an LLM prompt for a file and optionally send it to an LLM provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request


DEFAULT_COMMIT_COUNT = 10
DEFAULT_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_OPENAI_BASE_URL = "http://localhost:11434/v1"
DEFAULT_OPENAI_MODEL = "llama3.1"
DEFAULT_MS_TENANT = "organizations"
DEFAULT_MS_GRAPH_BASE_URL = "https://graph.microsoft.com/beta"
DEFAULT_CACHE_VERSION = 1
DEFAULT_MODE = "request"
DEFAULT_SYSTEM_MESSAGE = (
    "You are a careful software engineer. Explain the file in concise, clear "
    "language and base the recent-change summary on the provided git history."
)
DEFAULT_MS_SCOPE_VALUES = [
    "offline_access",
    "openid",
    "profile",
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/People.Read.All",
    "https://graph.microsoft.com/OnlineMeetingTranscript.Read.All",
    "https://graph.microsoft.com/Chat.Read",
    "https://graph.microsoft.com/ChannelMessage.Read.All",
    "https://graph.microsoft.com/ExternalItem.Read.All",
]


@dataclass
class CommitEntry:
    commit_hash: str
    author_date: str
    subject: str
    body: str

    def message_text(self) -> str:
        parts = [self.subject.strip()]
        if self.body.strip():
            parts.append(self.body.strip())
        return "\n".join(parts).strip()

    def render(self) -> str:
        header = f"- {self.author_date} {self.commit_hash[:12]} {self.subject.strip()}"
        if not self.body.strip():
            return header
        indented_body = "\n".join(f"  {line}" for line in self.body.strip().splitlines())
        return f"{header}\n{indented_body}"


class ScriptError(RuntimeError):
    """Expected script failure."""


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


def default_cwd_config_path() -> Path:
    return Path.cwd() / "summarizer.json"


def load_config(config_path: Path) -> Dict[str, Any]:
    config = read_json(config_path)
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ScriptError(f"Config file '{config_path}' must contain a JSON object")
    return config


def merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged


def load_effective_config(explicit_config_path: Optional[str]) -> Dict[str, Any]:
    if explicit_config_path:
        return load_config(Path(explicit_config_path).expanduser())

    profile_config = load_config(default_profile_config_path())
    cwd_config = load_config(default_cwd_config_path())
    return merge_config(profile_config, cwd_config)


def apply_config_defaults(args: argparse.Namespace, config: Dict[str, Any]) -> argparse.Namespace:
    if getattr(args, "prompt_only", False):
        args.mode = "prompt"
    elif args.mode is None:
        mode = config.get("mode")
        if isinstance(mode, str) and mode in {"prompt", "request"}:
            args.mode = mode
        else:
            args.mode = DEFAULT_MODE

    if args.provider is None:
        provider = config.get("provider")
        if isinstance(provider, str):
            args.provider = provider
        else:
            args.provider = "openai-compatible"

    if args.model is None:
        model = config.get("model")
        if isinstance(model, str):
            args.model = model
        else:
            args.model = DEFAULT_OPENAI_MODEL

    if args.base_url is None:
        base_url = config.get("base_url")
        if isinstance(base_url, str):
            args.base_url = base_url
        else:
            args.base_url = DEFAULT_OPENAI_BASE_URL

    if args.api_key is None:
        api_key = config.get("api_key")
        if isinstance(api_key, str):
            args.api_key = api_key

    if args.api_key_env is None:
        api_key_env = config.get("api_key_env")
        if isinstance(api_key_env, str):
            args.api_key_env = api_key_env
        else:
            args.api_key_env = DEFAULT_OPENAI_API_KEY_ENV

    if args.system_message is None:
        system_message = config.get("system_message")
        if isinstance(system_message, str):
            args.system_message = system_message
        else:
            args.system_message = DEFAULT_SYSTEM_MESSAGE

    if args.ms_tenant is None:
        ms_tenant = config.get("ms_tenant")
        if isinstance(ms_tenant, str):
            args.ms_tenant = ms_tenant
        else:
            args.ms_tenant = DEFAULT_MS_TENANT

    if args.ms_graph_base_url is None:
        graph_url = config.get("ms_graph_base_url")
        if isinstance(graph_url, str):
            args.ms_graph_base_url = graph_url
        else:
            args.ms_graph_base_url = DEFAULT_MS_GRAPH_BASE_URL

    if not args.ms_scopes:
        ms_scopes = config.get("ms_scopes")
        if isinstance(ms_scopes, list) and all(isinstance(item, str) for item in ms_scopes):
            args.ms_scopes = ms_scopes

    return args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an LLM prompt for a file using current file contents and recent git "
            "history, and optionally send it to an LLM."
        )
    )
    parser.add_argument("filepath", help="Path to the file to summarize")
    parser.add_argument(
        "--config",
        help=(
            "Path to the JSON config file. If omitted, the script loads the profile "
            "config and lets summarizer.json in the current working directory override it."
        ),
    )
    parser.add_argument(
        "-n",
        "--num-commits",
        type=int,
        default=DEFAULT_COMMIT_COUNT,
        help=f"Number of recent commits to inspect (default: {DEFAULT_COMMIT_COUNT})",
    )
    parser.add_argument(
        "--mode",
        choices=("prompt", "request"),
        default=None,
        help="Print the generated prompt, or send it to a provider",
    )
    parser.add_argument(
        "--prompt-only",
        action="store_true",
        help="Shortcut for '--mode prompt'",
    )
    parser.add_argument(
        "--provider",
        choices=("openai-compatible", "m365-copilot"),
        default=None,
        help="LLM provider used in request mode",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Also print the generated prompt before the model response in request mode",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds for provider requests (default: 120)",
    )
    parser.add_argument(
        "--cache-dir",
        help="Directory for cached request results",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache lookup and cache writes in request mode",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore any cached entry and recompute the response",
    )

    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Base URL for the OpenAI-compatible provider "
            f"(default: {DEFAULT_OPENAI_BASE_URL})"
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model name for request mode (default: {DEFAULT_OPENAI_MODEL})",
    )
    parser.add_argument(
        "--api-key",
        help="API key for the OpenAI-compatible provider",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help=(
            "Environment variable used for the OpenAI-compatible API key "
            f"(default: {DEFAULT_OPENAI_API_KEY_ENV})"
        ),
    )
    parser.add_argument(
        "--system-message",
        default=None,
        help="System message for the OpenAI-compatible provider",
    )

    parser.add_argument(
        "--ms-client-id",
        help="Client ID of the Microsoft Entra app registration used for device-code auth",
    )
    parser.add_argument(
        "--ms-tenant",
        default=None,
        help=f"Tenant for Microsoft device-code auth (default: {DEFAULT_MS_TENANT})",
    )
    parser.add_argument(
        "--ms-graph-base-url",
        default=None,
        help=(
            "Base URL for Microsoft Graph Copilot APIs "
            f"(default: {DEFAULT_MS_GRAPH_BASE_URL})"
        ),
    )
    parser.add_argument(
        "--ms-scope",
        action="append",
        dest="ms_scopes",
        default=[],
        help=(
            "Additional Microsoft Graph OAuth scope. Repeat the option to add more. "
            "If omitted, the script uses a default Copilot Chat scope set."
        ),
    )
    parser.add_argument(
        "--ms-token-cache",
        help="Override the Microsoft token cache path",
    )
    parser.add_argument(
        "--ms-clear-cache",
        action="store_true",
        help="Remove the cached Microsoft token before authenticating",
    )

    args = parser.parse_args()
    if args.num_commits <= 0:
        parser.error("--num-commits must be greater than 0")

    config = load_effective_config(args.config)
    return apply_config_defaults(args, config)


def run_git(args: List[str], repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ScriptError("git is not installed or not available in PATH") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "git command failed"
        raise ScriptError(message) from exc
    return completed.stdout


def find_repo_root() -> Path:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ScriptError("Current directory is not inside a git repository") from exc
    return Path(completed.stdout.strip()).resolve()


def resolve_repo_file(filepath: str, repo_root: Path) -> Path:
    candidate = Path(filepath)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ScriptError(
            f"File '{candidate}' is outside the git repository '{repo_root}'"
        ) from exc

    if not candidate.is_file():
        raise ScriptError(f"File '{candidate}' does not exist or is not a regular file")
    return candidate


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ScriptError(f"Failed to read file '{path}': {exc}") from exc


def get_relative_repo_path(file_path: Path, repo_root: Path) -> str:
    return file_path.relative_to(repo_root).as_posix()


def get_recent_commits(repo_root: Path, relative_path: str, limit: int) -> List[CommitEntry]:
    format_string = "%H%x1f%aI%x1f%s%x1f%b%x1e"
    output = run_git(
        ["log", "--follow", f"-n{limit}", f"--format={format_string}", "--", relative_path],
        repo_root,
    )

    commits: List[CommitEntry] = []
    for chunk in output.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        commits.append(
            CommitEntry(
                commit_hash=parts[0].strip(),
                author_date=parts[1].strip(),
                subject=parts[2].strip(),
                body=parts[3].strip(),
            )
        )

    commits.reverse()
    return commits


def get_latest_file_commit(repo_root: Path, relative_path: str) -> str:
    output = run_git(
        ["log", "--follow", "-n1", "--format=%H", "--", relative_path],
        repo_root,
    ).strip()
    return output


def build_prompt(relative_path: str, code: str, commits: List[CommitEntry], limit: int) -> str:
    commit_messages = [entry.message_text() for entry in commits if entry.message_text()]
    if commit_messages:
        chronological_messages = "\n\n".join(commit_messages)
        chronological_section = chronological_messages
        detailed_history = "\n".join(entry.render() for entry in commits)
    else:
        chronological_section = "No commits found for this file in the inspected range."
        detailed_history = "No commits found for this file in the inspected range."

    return f"""You are analyzing a single file from a git repository.

File path relative to the git root:
{relative_path}

Current file contents:
```text
{code}
```

Recent commit messages for this file, in chronological order (oldest to newest), from the last {limit} commits inspected:
{chronological_section}

Detailed recent file history:
{detailed_history}

Please answer in simple language and keep it practical.
Return the answer as Markdown.

Use these sections:
## File Purpose
## Main Responsibilities
## Recent Changes
## Uncertainty

In those sections, provide:
1. File purpose: what this file is for.
2. Main responsibilities: the main things the file does.
3. Recent changes: summarize what changed recently and what those changes were likely trying to achieve.
4. Any uncertainty: call out missing context or places where the commit messages are too vague.
"""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def default_cache_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "summarize-file"
        return Path.home() / "AppData" / "Local" / "summarize-file"

    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "summarize-file"
    return Path.home() / ".cache" / "summarize-file"


def get_ms_token_cache_path(explicit_path: Optional[str]) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    return default_cache_dir() / "ms365-token.json"


def get_response_cache_dir(explicit_path: Optional[str]) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "gcs" / "responses"
        return Path.home() / "AppData" / "Local" / "gcs" / "responses"

    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "gcs" / "responses"
    return Path.home() / ".cache" / "gcs" / "responses"


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScriptError(f"Failed to read JSON file '{path}': {exc}") from exc


def http_json_request(
    method: str,
    url: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float,
) -> Dict[str, Any]:
    body: Optional[bytes] = None
    req_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = request.Request(url=url, data=body, headers=req_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_bytes = response.read()
            if not response_bytes:
                return {}
            return json.loads(response_bytes.decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ScriptError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except error.URLError as exc:
        raise ScriptError(f"Request to {url} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Response from {url} was not valid JSON") from exc


def http_form_request(url: str, data: Dict[str, str], timeout: float) -> Dict[str, Any]:
    encoded = parse.urlencode(data).encode("utf-8")
    req = request.Request(
        url=url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ScriptError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except error.URLError as exc:
        raise ScriptError(f"Request to {url} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Response from {url} was not valid JSON") from exc


def get_openai_api_key(args: argparse.Namespace) -> Optional[str]:
    if args.api_key:
        return args.api_key
    if args.api_key_env:
        return os.environ.get(args.api_key_env)
    return None


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def extract_openai_text(response_payload: Dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ScriptError("OpenAI-compatible response does not contain choices")

    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_value = item.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
        if text_parts:
            return "\n".join(text_parts)
    raise ScriptError("OpenAI-compatible response does not contain text content")


def request_openai_compatible(prompt: str, args: argparse.Namespace) -> str:
    headers = {"Accept": "application/json"}
    api_key = get_openai_api_key(args)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": args.system_message},
            {"role": "user", "content": prompt},
        ],
    }
    response_payload = http_json_request(
        "POST",
        f"{normalize_base_url(args.base_url)}/chat/completions",
        payload=payload,
        headers=headers,
        timeout=args.timeout,
    )
    return extract_openai_text(response_payload)


def get_ms_scopes(args: argparse.Namespace) -> List[str]:
    if args.ms_scopes:
        return args.ms_scopes
    return list(DEFAULT_MS_SCOPE_VALUES)


def token_is_valid(token_data: Dict[str, Any]) -> bool:
    expires_at = token_data.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        return False
    return time.time() < float(expires_at) - 60


def token_matches_request(
    token_data: Dict[str, Any],
    *,
    client_id: str,
    tenant: str,
    scopes: List[str],
) -> bool:
    if token_data.get("client_id") != client_id:
        return False
    if token_data.get("tenant") != tenant:
        return False
    cached_scopes = token_data.get("scopes")
    if not isinstance(cached_scopes, list):
        return False
    return cached_scopes == scopes


def build_ms_token_record(
    token_payload: Dict[str, Any],
    *,
    client_id: str,
    tenant: str,
    scopes: List[str],
) -> Dict[str, Any]:
    expires_in = int(token_payload.get("expires_in", 0))
    refresh_token = token_payload.get("refresh_token")
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ScriptError("Microsoft token response did not contain an access_token")

    record: Dict[str, Any] = {
        "client_id": client_id,
        "tenant": tenant,
        "scopes": scopes,
        "access_token": access_token,
        "expires_at": int(time.time()) + expires_in,
    }
    if isinstance(refresh_token, str) and refresh_token:
        record["refresh_token"] = refresh_token
    return record


def try_ms_refresh_token(
    token_data: Dict[str, Any],
    *,
    client_id: str,
    tenant: str,
    scopes: List[str],
    timeout: float,
) -> Optional[Dict[str, Any]]:
    refresh_token = token_data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return None

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    payload = http_form_request(
        token_url,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": " ".join(scopes),
        },
        timeout,
    )
    return build_ms_token_record(
        payload,
        client_id=client_id,
        tenant=tenant,
        scopes=scopes,
    )


def acquire_ms_device_code_token(
    *,
    client_id: str,
    tenant: str,
    scopes: List[str],
    timeout: float,
) -> Dict[str, Any]:
    device_code_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    device_code_payload = http_form_request(
        device_code_url,
        {
            "client_id": client_id,
            "scope": " ".join(scopes),
        },
        timeout,
    )
    message = device_code_payload.get("message")
    if not isinstance(message, str) or not message:
        raise ScriptError("Microsoft device-code response did not contain a user message")
    print(message, file=sys.stderr)

    device_code = device_code_payload.get("device_code")
    interval = int(device_code_payload.get("interval", 5))
    expires_in = int(device_code_payload.get("expires_in", 900))
    if not isinstance(device_code, str) or not device_code:
        raise ScriptError("Microsoft device-code response did not contain device_code")

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        try:
            token_payload = http_form_request(
                token_url,
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code,
                },
                timeout,
            )
        except ScriptError as exc:
            message_text = str(exc)
            if "authorization_pending" in message_text:
                continue
            if "slow_down" in message_text:
                interval += 5
                continue
            raise

        return build_ms_token_record(
            token_payload,
            client_id=client_id,
            tenant=tenant,
            scopes=scopes,
        )

    raise ScriptError("Microsoft device-code login timed out before authorization completed")


def get_ms_access_token(args: argparse.Namespace) -> str:
    if not args.ms_client_id:
        raise ScriptError("--ms-client-id is required for provider 'm365-copilot'")

    scopes = get_ms_scopes(args)
    cache_path = get_ms_token_cache_path(args.ms_token_cache)
    if args.ms_clear_cache and cache_path.exists():
        cache_path.unlink()

    token_data = read_json(cache_path)
    if token_data and token_matches_request(
        token_data,
        client_id=args.ms_client_id,
        tenant=args.ms_tenant,
        scopes=scopes,
    ):
        if token_is_valid(token_data):
            return token_data["access_token"]

        try:
            refreshed = try_ms_refresh_token(
                token_data,
                client_id=args.ms_client_id,
                tenant=args.ms_tenant,
                scopes=scopes,
                timeout=args.timeout,
            )
        except ScriptError:
            refreshed = None

        if refreshed:
            write_json(cache_path, refreshed)
            return refreshed["access_token"]

    token_data = acquire_ms_device_code_token(
        client_id=args.ms_client_id,
        tenant=args.ms_tenant,
        scopes=scopes,
        timeout=args.timeout,
    )
    write_json(cache_path, token_data)
    return token_data["access_token"]


def local_timezone_name() -> str:
    now = datetime.now().astimezone()
    tz_name = now.tzname()
    if tz_name:
        return tz_name
    return "UTC"


def extract_m365_text(response_payload: Dict[str, Any]) -> str:
    messages = response_payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ScriptError("Microsoft Copilot response did not contain messages")

    for message in reversed(messages):
        if isinstance(message, dict):
            text = message.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise ScriptError("Microsoft Copilot response did not contain message text")


def request_m365_copilot(prompt: str, args: argparse.Namespace) -> str:
    access_token = get_ms_access_token(args)
    base_url = normalize_base_url(args.ms_graph_base_url)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    conversation = http_json_request(
        "POST",
        f"{base_url}/copilot/conversations",
        payload={},
        headers=headers,
        timeout=args.timeout,
    )
    conversation_id = conversation.get("id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise ScriptError("Microsoft Copilot conversation creation did not return an id")

    response_payload = http_json_request(
        "POST",
        f"{base_url}/copilot/conversations/{conversation_id}/chat",
        payload={
            "message": {"text": prompt},
            "locationHint": {"timeZone": local_timezone_name()},
        },
        headers=headers,
        timeout=args.timeout,
    )
    return extract_m365_text(response_payload)


def request_summary(prompt: str, args: argparse.Namespace) -> str:
    if args.provider == "openai-compatible":
        return request_openai_compatible(prompt, args)
    if args.provider == "m365-copilot":
        return request_m365_copilot(prompt, args)
    raise ScriptError(f"Unsupported provider '{args.provider}'")


def build_cache_metadata(
    *,
    args: argparse.Namespace,
    relative_path: str,
    code: str,
    prompt: str,
    latest_commit: str,
) -> Dict[str, Any]:
    return {
        "cache_version": DEFAULT_CACHE_VERSION,
        "file_path": relative_path,
        "latest_file_commit": latest_commit,
        "file_content_sha256": sha256_text(code),
        "num_commits": args.num_commits,
        "provider": args.provider,
        "model": args.model,
        "system_message": args.system_message,
        "prompt_sha256": sha256_text(prompt),
        "base_url": normalize_base_url(args.base_url),
        "ms_graph_base_url": normalize_base_url(args.ms_graph_base_url),
    }


def build_cache_key(metadata: Dict[str, Any]) -> str:
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cache_file_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / cache_key[:2] / f"{cache_key}.json"


def load_cached_response(cache_path: Path) -> Optional[str]:
    payload = read_json(cache_path)
    if not payload:
        return None
    response = payload.get("response")
    if isinstance(response, str):
        return response
    return None


def write_cached_response(
    cache_path: Path,
    *,
    metadata: Dict[str, Any],
    prompt: str,
    response: str,
) -> None:
    payload = {
        "metadata": metadata,
        "created_at": datetime.now().astimezone().isoformat(),
        "prompt": prompt,
        "response": response,
    }
    write_json(cache_path, payload)


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root()
    file_path = resolve_repo_file(args.filepath, repo_root)
    relative_path = get_relative_repo_path(file_path, repo_root)
    code = read_text_file(file_path)
    commits = get_recent_commits(repo_root, relative_path, args.num_commits)
    prompt = build_prompt(relative_path, code, commits, args.num_commits)
    latest_commit = get_latest_file_commit(repo_root, relative_path)

    if args.mode == "prompt":
        print(prompt)
        return 0

    cache_dir = get_response_cache_dir(args.cache_dir)
    cache_metadata = build_cache_metadata(
        args=args,
        relative_path=relative_path,
        code=code,
        prompt=prompt,
        latest_commit=latest_commit,
    )
    cache_key = build_cache_key(cache_metadata)
    cache_path = get_cache_file_path(cache_dir, cache_key)

    if args.print_prompt:
        print(prompt)
        print("\n" + "=" * 80 + "\n")

    if not args.no_cache and not args.refresh:
        cached_response = load_cached_response(cache_path)
        if cached_response is not None:
            print(cached_response)
            return 0

    result = request_summary(prompt, args)
    if not args.no_cache:
        write_cached_response(
            cache_path,
            metadata=cache_metadata,
            prompt=prompt,
            response=result,
        )
    print(result)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)
    except ScriptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
