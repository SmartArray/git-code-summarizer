import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import sublime
import sublime_plugin


PLUGIN_SETTINGS = "SummarizeFile.sublime-settings"
TEMP_ROOT_DIRNAME = "sublime-summarize-file"


def plugin_settings():
    return sublime.load_settings(PLUGIN_SETTINGS)


def python_executable():
    configured = plugin_settings().get("python_executable")
    if configured:
        return configured
    return shutil.which("python3") or shutil.which("python") or "python3"


def summarize_script_path():
    configured = plugin_settings().get("script_path")
    if configured:
        return Path(os.path.expanduser(configured))
    raise RuntimeError("SummarizeFile setting 'script_path' is not configured")


def repo_root_for_file(file_path):
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(Path(file_path).parent),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def temp_markdown_path(source_file):
    source = Path(source_file).resolve()
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
    filename = source.stem + "-" + digest + ".md"
    return Path(tempfile.gettempdir()) / TEMP_ROOT_DIRNAME / filename


class SummarizeFileCommand(sublime_plugin.WindowCommand):
    def run(self, mode="request", refresh=False):
        view = self.window.active_view()
        if view is None or not view.file_name():
            sublime.error_message("Open and focus a file first.")
            return

        source_file = view.file_name()
        repo_root = repo_root_for_file(source_file)
        if not repo_root:
            sublime.error_message("The current file is not inside a git repository.")
            return

        script_path = summarize_script_path()
        if not script_path.is_file():
            sublime.error_message(
                "Summarize script not found.\n\n"
                "Set 'script_path' in SummarizeFile.sublime-settings."
            )
            return

        output_path = temp_markdown_path(source_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [python_executable(), str(script_path), source_file]
        if mode == "prompt":
            cmd.append("--prompt-only")
        else:
            cmd.extend(["--mode", "request"])
        if refresh:
            cmd.append("--refresh")

        extra_args = plugin_settings().get("extra_args", [])
        if isinstance(extra_args, list):
            cmd.extend(str(item) for item in extra_args)

        self.window.status_message("Generating file summary...")
        sublime.set_timeout_async(
            lambda: self._run_summary(cmd, repo_root, output_path, source_file),
            0,
        )

    def _run_summary(self, cmd, repo_root, output_path, source_file):
        env = os.environ.copy()
        extra_env = plugin_settings().get("env", {})
        if isinstance(extra_env, dict):
            for key, value in extra_env.items():
                env[str(key)] = str(value)

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            completed = subprocess.run(
                cmd,
                cwd=repo_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                startupinfo=startupinfo,
            )
            content = completed.stdout
        except FileNotFoundError as exc:
            sublime.set_timeout(
                lambda: sublime.error_message(f"Failed to start summarize tool:\n\n{exc}"),
                0,
            )
            return
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip()
            stdout = exc.stdout.strip()
            detail = stderr or stdout or "Unknown error"
            sublime.set_timeout(
                lambda: sublime.error_message(f"Summarize tool failed:\n\n{detail}"),
                0,
            )
            return

        output_path.write_text(content, encoding="utf-8")
        sublime.set_timeout(
            lambda: self._open_output(output_path, source_file),
            0,
        )

    def _open_output(self, output_path, source_file):
        view = self.window.open_file(str(output_path))
        if view is None:
            sublime.error_message(f"Failed to open summary file:\n\n{output_path}")
            return

        settings = view.settings()
        settings.set("summarize_file_temp", True)
        settings.set("summarize_file_source", source_file)
        settings.set("summarize_file_output", str(output_path))
        settings.set("word_wrap", True)
        view.set_scratch(True)
        try:
            view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")
        except Exception:
            pass
        self.window.status_message("File summary ready.")


class SummarizeFileTempCleanupListener(sublime_plugin.EventListener):
    def on_pre_close(self, view):
        if not view.settings().get("summarize_file_temp"):
            return

        output_path = view.settings().get("summarize_file_output")
        if not output_path:
            return

        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass
