const vscode = require("vscode");
const cp = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const TEMP_ROOT_DIRNAME = "vscode-summarize-file";
const managedTempFiles = new Set();

function getConfig() {
  return vscode.workspace.getConfiguration("summarizeFile");
}

function activeSourceFile() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || !editor.document || editor.document.isUntitled) {
    return null;
  }
  if (editor.document.uri.scheme !== "file") {
    return null;
  }
  return editor.document.uri.fsPath;
}

function repoRootForFile(filePath) {
  try {
    return cp
      .execFileSync("git", ["rev-parse", "--show-toplevel"], {
        cwd: path.dirname(filePath),
        encoding: "utf8"
      })
      .trim();
  } catch (_error) {
    return null;
  }
}

function summarizeScriptPath(sourceFile) {
  const configured = getConfig().get("scriptPath", "").trim();
  if (configured) {
    return path.resolve(configured);
  }

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(sourceFile));
  if (!workspaceFolder) {
    return null;
  }

  return path.join(workspaceFolder.uri.fsPath, "tools", "summarizer", "summarize-file.py");
}

function tempMarkdownPath(sourceFile) {
  const digest = crypto.createHash("sha256").update(path.resolve(sourceFile)).digest("hex").slice(0, 16);
  const filename = `${path.parse(sourceFile).name}-${digest}.md`;
  return path.join(os.tmpdir(), TEMP_ROOT_DIRNAME, filename);
}

function ensureTempDirectory(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

async function runSummarizeCommand(mode, refresh) {
  const sourceFile = activeSourceFile();
  if (!sourceFile) {
    await vscode.window.showErrorMessage("Open and focus a file first.");
    return;
  }

  const repoRoot = repoRootForFile(sourceFile);
  if (!repoRoot) {
    await vscode.window.showErrorMessage("The current file is not inside a git repository.");
    return;
  }

  const scriptPath = summarizeScriptPath(sourceFile);
  if (!scriptPath || !fs.existsSync(scriptPath)) {
    await vscode.window.showErrorMessage(
      "Summarize script not found. Set summarizeFile.scriptPath or open the matching workspace."
    );
    return;
  }

  const outputPath = tempMarkdownPath(sourceFile);
  ensureTempDirectory(outputPath);

  const args = [scriptPath, sourceFile];
  if (mode === "prompt") {
    args.push("--prompt-only");
  } else {
    args.push("--mode", "request");
  }
  if (refresh) {
    args.push("--refresh");
  }

  const extraArgs = getConfig().get("extraArgs", []);
  if (Array.isArray(extraArgs)) {
    args.push(...extraArgs.map(String));
  }

  const env = { ...process.env };
  const extraEnv = getConfig().get("env", {});
  if (extraEnv && typeof extraEnv === "object") {
    for (const [key, value] of Object.entries(extraEnv)) {
      env[String(key)] = String(value);
    }
  }

  const pythonExecutable = getConfig().get("pythonExecutable", "python3");
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Summarizing file",
      cancellable: false
    },
    async () => {
      let stdout;
      try {
        const result = await execFile(pythonExecutable, args, {
          cwd: repoRoot,
          env
        });
        stdout = result.stdout;
      } catch (error) {
        const detail = error.stderr || error.stdout || error.message || "Unknown error";
        await vscode.window.showErrorMessage(`Summarize tool failed: ${detail}`);
        return;
      }

      fs.writeFileSync(outputPath, stdout, "utf8");
      managedTempFiles.add(outputPath);

      const document = await vscode.workspace.openTextDocument(vscode.Uri.file(outputPath));
      await vscode.languages.setTextDocumentLanguage(document, "markdown");
      await vscode.window.showTextDocument(document, {
        preview: true,
        preserveFocus: false,
        viewColumn: vscode.ViewColumn.Beside
      });

      if (getConfig().get("showPreview", true)) {
        await vscode.commands.executeCommand("markdown.showPreviewToSide", document.uri);
      }
    }
  );
}

function execFile(command, args, options) {
  return new Promise((resolve, reject) => {
    cp.execFile(command, args, options, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

function cleanupTempFile(filePath) {
  if (!managedTempFiles.has(filePath)) {
    return;
  }
  try {
    fs.unlinkSync(filePath);
  } catch (_error) {
    return;
  } finally {
    managedTempFiles.delete(filePath);
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("summarizeFile.requestSummary", () =>
      runSummarizeCommand("request", false)
    )
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("summarizeFile.requestSummaryRefresh", () =>
      runSummarizeCommand("request", true)
    )
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("summarizeFile.showPromptOnly", () =>
      runSummarizeCommand("prompt", false)
    )
  );
  context.subscriptions.push(
    vscode.workspace.onDidCloseTextDocument((document) => {
      if (document.uri.scheme !== "file") {
        return;
      }
      cleanupTempFile(document.uri.fsPath);
    })
  );
}

function deactivate() {
  for (const filePath of Array.from(managedTempFiles)) {
    cleanupTempFile(filePath);
  }
}

module.exports = {
  activate,
  deactivate
};
