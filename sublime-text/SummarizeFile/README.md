# SummarizeFile Sublime Plugin

This Sublime Text plugin runs `tools/summarizer/summarize-file.py` for the active file and opens the result as a temporary Markdown file.

## Behavior

- Uses the Python tool's existing request cache automatically.
- Opens the summary in a temporary `.md` file under the system temp directory.
- Reuses the same temp path for the same source file and overwrites it on each run.
- Deletes the temp file when the Markdown tab is closed.

## Install On macOS

Copy these files into your Sublime Text `Packages/User` directory:

- `SummarizeFile.py`
- `SummarizeFile.sublime-commands`
- `Default (OSX).sublime-keymap`
- `SummarizeFile.sublime-settings`

Typical path:

`~/Library/Application Support/Sublime Text/Packages/User/`

## Configure

Edit `SummarizeFile.sublime-settings`:

```json
{
  "script_path": "/absolute/path/to/summarizer/summarize-file.py",
  "python_executable": "python3",
  "extra_args": [],
  "env": {}
}
```

The Python tool loads config from:

- profile config: `~/.config/summarizer/config.json` on macOS/Linux
- override config: `summarizer.json` in the current working directory

If both exist, the current working directory config wins. A sample config is in:

`tools/summarizer/summarizer.example.json`

Useful `extra_args` examples:

```json
{
  "extra_args": ["--mode", "request"]
}
```

```json
{
  "extra_args": ["--provider", "openai-compatible", "--model", "llama3.1"]
}
```

If you need environment variables for the provider:

```json
{
  "env": {
    "OPENAI_API_KEY": "your-key"
  }
}
```

## Commands

Open the Command Palette and run:

- `Summarize File: Request Summary`
- `Summarize File: Request Summary (Refresh Cache)`
- `Summarize File: Show Prompt Only`

## Hotkey

On macOS, the plugin binds:

- `cmd+alt+s` to `Summarize File: Request Summary`
