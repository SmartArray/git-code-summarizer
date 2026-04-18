# Summarize File VS Code Extension

This extension runs `tools/summarizer/summarize-file.py` for the active file and opens the Markdown result in VS Code.

## Behavior

- Uses the Python tool's request cache automatically.
- Creates a deterministic temp Markdown file under the system temp directory.
- Reuses and overwrites the same temp file for the same source file.
- Deletes the temp file when the document closes.
- Can also open the built-in Markdown preview to the side.

## Commands

- `Summarize File: Request Summary`
- `Summarize File: Request Summary (Refresh Cache)`
- `Summarize File: Show Prompt Only`

Default macOS hotkey:

- `cmd+alt+s`

## Settings

- `summarizeFile.scriptPath`
- `summarizeFile.pythonExecutable`
- `summarizeFile.extraArgs`
- `summarizeFile.env`
- `summarizeFile.showPreview`

If `summarizeFile.scriptPath` is empty, the extension looks for:

`tools/summarizer/summarize-file.py`

under the current workspace folder.

## Config Resolution In The Python Tool

The Python tool itself loads config in this order:

1. Explicit `--config`
2. Profile config
   `~/.config/summarizer/config.json` on macOS/Linux
3. `summarizer.json` in the current working directory

The current working directory config overrides the profile config.

## Development

Open this folder in VS Code and press `F5` to launch an Extension Development Host.
