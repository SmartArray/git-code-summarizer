# GitCodeSummarizer

> "Large codebases do not fail because code is missing. They fail because context is missing."

GitCodeSummarizer, or `gcs`, helps you recover that context fast.

In a modern codebase with hundreds of source files and hundreds of colleagues, the real problem is rarely "what does this file contain?" The real problem is:

- why this file exists
- what responsibility it owns
- what changed recently
- what those changes were trying to achieve

Reading a file in isolation is usually not enough. Reading the file together with its recent git history is much better. That is what this tool does.

`gcs` reads the current source file, its path inside the repository, and the recent commits that touched it. It then builds a focused prompt and asks an LLM to explain the file in Markdown. The result is much closer to how engineers actually reason about code: current implementation plus recent intent.

This is especially useful when:

- onboarding into a large project
- reviewing unfamiliar modules
- preparing refactors
- understanding ownership boundaries
- recovering intent from terse commit messages

It supports:

- local LLMs through an OpenAI-compatible endpoint
  for example Ollama on your own machine
- remote OpenAI-compatible providers
- Microsoft 365 Copilot

## Table Of Contents

- [What Is In This Folder](#what-is-in-this-folder)
- [What The Script Does](#what-the-script-does)
- [Install](#install)
- [Quick Start](#quick-start)
- [Example With Ollama](#example-with-ollama)
- [Batch Cache Warming](#batch-cache-warming)
- [CLI Arguments](#cli-arguments)
- [Config Order](#config-order)
- [Cache](#cache)
- [Sublime Text Setup](#sublime-text-setup)
- [VS Code Setup](#vs-code-setup)
- [Notes](#notes)

## What Is In This Folder

- `summarize-file.py`
  The main Python script.
- `gcs-cache-glob.py`
  Batch helper that warms the response cache for files matched from the current directory.
- `summarizer.example.json`
  Example config file.
- `sublime-text/`
  Sublime Text integration.
- `vscode/`
  VS Code integration.

## What The Script Does

Given a file path, it:

1. Finds the git repo root.
2. Reads the current file contents.
3. Reads the last `N` commits for that file.
4. Builds a prompt.
5. Either:
   prints the prompt, or
   sends the prompt to an LLM.
6. Caches the LLM response on disk.

The cache is invalidated automatically when:

- the file changes locally
- a new commit touches the file
- the prompt changes
- the model or provider changes

## Install

### 1. Clone To A Persistent Path

Pick a stable location that will not move around.

macOS / Linux example:

```bash
mkdir -p ~/opt
git clone https://github.com/SmartArray/git-code-summarizer.git ~/opt/git-code-summarizer
```

Windows PowerShell example:

```powershell
New-Item -ItemType Directory -Force "$HOME\opt" | Out-Null
git clone https://github.com/SmartArray/git-code-summarizer.git "$HOME\opt\git-code-summarizer"
```

### 2. Add A `gcs` Command

macOS / Linux symlink:

```bash
mkdir -p ~/.local/bin
ln -sf ~/opt/git-code-summarizer/summarize-file.py ~/.local/bin/gcs
chmod +x ~/opt/git-code-summarizer/summarize-file.py
```

Make sure `~/.local/bin` is in your `PATH`.

Optional helper command:

```bash
ln -sf ~/opt/git-code-summarizer/gcs-cache-glob.py ~/.local/bin/gcs-cache-glob
chmod +x ~/opt/git-code-summarizer/gcs-cache-glob.py
```

Windows equivalent:

Create a `gcs.cmd` file somewhere in your `PATH`, for example in `%USERPROFILE%\bin\gcs.cmd`:

```bat
@echo off
python "%USERPROFILE%\opt\git-code-summarizer\summarize-file.py" %*
```

If `%USERPROFILE%\bin` does not exist yet:

```powershell
New-Item -ItemType Directory -Force "$HOME\bin" | Out-Null
```

Then add that directory to your `PATH`.

If you also want the batch helper, create `%USERPROFILE%\bin\gcs-cache-glob.cmd`:

```bat
@echo off
python "%USERPROFILE%\opt\git-code-summarizer\gcs-cache-glob.py" %*
```

## Quick Start

### 1. Create A Profile Config

On macOS or Linux, create:

```text
~/.config/summarizer/config.json
```

Create the directory first:

```bash
mkdir -p ~/.config/summarizer
```

Then create the config file:

```json
{
  "provider": "openai-compatible",
  "model": "llama3.1",
  "base_url": "http://localhost:11434/v1",
  "api_key_env": "OPENAI_API_KEY",
  "system_message": "You are a careful software engineer. Explain the file in concise, clear language and base the recent-change summary on the provided git history."
}
```

On Windows, use:

```text
%APPDATA%\summarizer\config.json
```

Create the directory first:

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\summarizer" | Out-Null
```

Then create the same `config.json` there.

`OPENAI_API_KEY` is only needed for cloud LLM providers.

It is not required for local models such as Ollama when your local endpoint does not require authentication.

### 2. Optional: Create A Repo-Local Override

In the repo root, create:

```text
summarizer.json
```

This overrides the profile config for this repo only.

Example:

```json
{
  "model": "qwen2.5-coder:14b",
  "base_url": "http://localhost:11434/v1"
}
```

### 3. Run It

Prompt only:

```bash
gcs path/to/file.cpp --prompt-only
```

Request a summary:

```bash
gcs path/to/file.cpp --mode request
```

Force recomputation:

```bash
gcs path/to/file.cpp --mode request --refresh
```

You can also run it directly:

```bash
python3 summarize-file.py path/to/file.cpp --mode request
```

## Example With Ollama

Start Ollama and make sure the OpenAI-compatible endpoint is available:

```text
http://localhost:11434/v1
```

Example config:

```json
{
  "provider": "openai-compatible",
  "model": "llama3.1",
  "base_url": "http://localhost:11434/v1"
}
```

Then run:

```bash
gcs path/to/file.cpp --mode request
```

## Batch Cache Warming

`gcs-cache-glob` scans the current working directory with a glob pattern, then calls the repo-local `summarize-file.py` once per matched file. Child output is suppressed; the helper prints progress only.

Examples:

```bash
gcs-cache-glob "*.cpp" --mode request
gcs-cache-glob "**/*.cpp" --mode request --refresh
gcs-cache-glob --keep-going "**/*.cpp" --mode request
```

Wrapper-specific behavior:

| Argument | Values | Default | Notes |
| --- | --- | --- | --- |
| `<pattern>` | Any Python `glob` pattern such as `*.cpp` or `**/*.cpp` | Required | Matching starts from the current working directory. `**` works recursively. |
| `--keep-going` | Flag | `false` | Continue processing after a file fails and report failures at the end. |
| `--fail-fast` | Flag | `true` | Stop on the first failed file. This is the default behavior. |
| Remaining args | Any `gcs` CLI args | Forwarded unchanged | Passed to `summarize-file.py` for each matched file. |

## CLI Arguments

The command format is:

```text
gcs <filepath> [options]
```

Most request-mode settings can also come from config. In the table below, the default value is the effective default after config is applied.

| Argument | Values | Default | Notes |
| --- | --- | --- | --- |
| `filepath` | Path to a file inside the current git repo | Required | Must point to a regular file inside the repository. |
| `--config <path>` | Path to a JSON config file | Not set | If omitted, `gcs` loads profile config and then `summarizer.json` in the current working directory. |
| `-n`, `--num-commits <int>` | Integer greater than `0` | `10` | Number of recent commits to inspect for the target file. |
| `--mode <mode>` | `prompt`, `request` | `request` | `prompt` prints only the generated prompt. `request` calls the configured provider. |
| `--prompt-only` | Flag | `false` | Shortcut for `--mode prompt`. |
| `--provider <provider>` | `openai-compatible`, `m365-copilot` | `openai-compatible` | Provider used in request mode. |
| `--print-prompt` | Flag | `false` | In request mode, prints the prompt before the model response. |
| `--timeout <seconds>` | Positive number | `120.0` | HTTP timeout for provider requests. |
| `--cache-dir <path>` | Directory path | OS-specific persistent user cache | Overrides the default response cache directory. Default: macOS/Linux `~/.cache/gcs/responses/`, Windows `%LOCALAPPDATA%\gcs\responses\`. |
| `--no-cache` | Flag | `false` | Disables cache reads and writes. |
| `--refresh` | Flag | `false` | Ignores any cached response and recomputes it. |
| `--base-url <url>` | URL | Config value or `http://localhost:11434/v1` | Base URL for the OpenAI-compatible provider. |
| `--model <name>` | Any model name string | Config value or `llama3.1` | Model used in request mode. |
| `--api-key <key>` | Any string | Not set | Direct API key for the OpenAI-compatible provider. |
| `--api-key-env <envvar>` | Environment variable name | Config value or `OPENAI_API_KEY` | Environment variable used to read the API key. |
| `--system-message <text>` | Any string | Config value or built-in system prompt | System message for the OpenAI-compatible provider. |
| `--ms-client-id <id>` | Microsoft Entra application client ID | Not set | Required for Microsoft device-code auth when using `m365-copilot`. |
| `--ms-tenant <tenant>` | Tenant string such as `organizations`, `common`, `consumers`, or a tenant ID | Config value or `organizations` | Tenant used for Microsoft device-code auth. |
| `--ms-graph-base-url <url>` | URL | Config value or `https://graph.microsoft.com/beta` | Base URL for Microsoft Graph Copilot APIs. |
| `--ms-scope <scope>` | OAuth scope string; repeat the flag to add more | Config value or built-in Copilot scope set | Adds Microsoft Graph OAuth scopes. If omitted, `gcs` uses the default Copilot Chat scopes. |
| `--ms-token-cache <path>` | File path | OS-specific user cache path | Overrides the Microsoft token cache file path. |
| `--ms-clear-cache` | Flag | `false` | Deletes the cached Microsoft token before authenticating. |

Default Microsoft scopes used when `--ms-scope` is not provided:

- `offline_access`
- `openid`
- `profile`
- `https://graph.microsoft.com/Sites.Read.All`
- `https://graph.microsoft.com/Mail.Read`
- `https://graph.microsoft.com/People.Read.All`
- `https://graph.microsoft.com/OnlineMeetingTranscript.Read.All`
- `https://graph.microsoft.com/Chat.Read`
- `https://graph.microsoft.com/ChannelMessage.Read.All`
- `https://graph.microsoft.com/ExternalItem.Read.All`

## Config Order

The script loads config in this order:

1. `--config <path>`
2. profile config
3. `summarizer.json` in the current working directory

If both profile config and `summarizer.json` exist, the current working directory file wins.

## Cache

The response cache is now a user-level persistent cache. By default it is stored outside the repo in:

```text
macOS/Linux: ~/.cache/gcs/responses/
Windows: %LOCALAPPDATA%\gcs\responses\
```

`gcs` uses that cache across repositories and across reboots. The cache key logic is unchanged, so entries are still based on file content plus git commit state.

Useful flags:

- `--refresh`
  Ignore the cache and recompute.
- `--no-cache`
  Do not read or write cache entries.
- `--cache-dir <path>`
  Override the default response cache directory.

## Sublime Text Setup

### 1. Copy The Plugin Files

Copy everything from:

```text
sublime-text/SummarizeFile/
```

to:

```text
~/Library/Application Support/Sublime Text/Packages/User/
```

### 2. Edit The Settings File

Set:

```json
{
  "script_path": "/absolute/path/to/git-code-summarizer/summarize-file.py",
  "python_executable": "python3",
  "extra_args": [],
  "env": {}
}
```

### 3. Use It

Command Palette:

- `Summarize File: Request Summary`
- `Summarize File: Request Summary (Refresh Cache)`
- `Summarize File: Show Prompt Only`

Hotkey on macOS:

- `cmd+alt+s`

The plugin opens a temp Markdown file, overwrites it on rerun, and deletes it when the tab is closed.

## VS Code Setup

### 1. Open The Extension Folder

Open:

```text
vscode/summarize-file-extension/
```

in VS Code.

### 2. Start The Extension Host

Press:

```text
F5
```

### 3. Configure It

Use VS Code settings:

- `summarizeFile.scriptPath`
- `summarizeFile.pythonExecutable`
- `summarizeFile.extraArgs`
- `summarizeFile.env`
- `summarizeFile.showPreview`

Typical script path:

```text
/absolute/path/to/git-code-summarizer/summarize-file.py
```

### 4. Use It

Commands:

- `Summarize File: Request Summary`
- `Summarize File: Request Summary (Refresh Cache)`
- `Summarize File: Show Prompt Only`

Hotkey on macOS:

- `cmd+alt+s`

The extension opens a temp Markdown file, reuses it for the same source file, and deletes it when the editor closes.

## Notes

- The script expects to run inside a git repository.
- The LLM response is requested as Markdown.
- The Microsoft 365 Copilot mode needs an Entra app registration and device-code auth.
