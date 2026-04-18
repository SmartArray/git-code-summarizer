# Summarizer

This tool explains what a file does.

It supports:

- local LLMs through an OpenAI-compatible endpoint
  for example Ollama on your own machine
- remote OpenAI-compatible providers
- Microsoft 365 Copilot

It reads:

- the current file contents
- the file path relative to the git repo
- the recent git commits for that file

It then builds a prompt for an LLM.

It can also send that prompt to an LLM and return a Markdown summary.

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

## Quick Start

### 1. Create a Profile Config

On macOS or Linux, create:

```text
~/.config/summarizer/config.json
```

Example:

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
python3 tools/summarizer/summarize-file.py path/to/file.cpp --prompt-only
```

Request a summary:

```bash
python3 tools/summarizer/summarize-file.py path/to/file.cpp --mode request
```

Force recomputation:

```bash
python3 tools/summarizer/summarize-file.py path/to/file.cpp --mode request --refresh
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
python3 tools/summarizer/summarize-file.py asu/lib/Components/src/BrewUnit/BrewUnit.cpp --mode request
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
tools/summarizer/sublime-text/SummarizeFile/
```

to:

```text
~/Library/Application Support/Sublime Text/Packages/User/
```

### 2. Edit The Settings File

Set:

```json
{
  "script_path": "/absolute/path/to/summarizer/summarize-file.py",
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
tools/summarizer/vscode/summarize-file-extension/
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
/absolute/path/to/summarizer/summarize-file.py
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
