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

## What Is In This Folder

- `summarize-file.py`
  The main Python script.
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
git clone <repo-url> ~/opt/git-code-summarizer
```

Windows PowerShell example:

```powershell
New-Item -ItemType Directory -Force "$HOME\opt" | Out-Null
git clone <repo-url> "$HOME\opt\git-code-summarizer"
```

### 2. Add A `gcs` Command

macOS / Linux symlink:

```bash
mkdir -p ~/.local/bin
ln -sf ~/opt/git-code-summarizer/summarize-file.py ~/.local/bin/gcs
chmod +x ~/opt/git-code-summarizer/summarize-file.py
```

Make sure `~/.local/bin` is in your `PATH`.

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

## Config Order

The script loads config in this order:

1. `--config <path>`
2. profile config
3. `summarizer.json` in the current working directory

If both profile config and `summarizer.json` exist, the current working directory file wins.

## Cache

The response cache is stored in:

```text
.tools-cache/summarize-file/
```

inside the repo by default.

Useful flags:

- `--refresh`
  Ignore the cache and recompute.
- `--no-cache`
  Do not read or write cache entries.
- `--cache-dir <path>`
  Use a different cache directory.

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
