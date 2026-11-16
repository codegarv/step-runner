# step-runner

Run a list of commands one at a time, and say yes or no to each before it runs.

You write the steps in a JSON file. For each step the runner shows what it does, the exact command, and how to undo it, then asks:

```
Step 1/1: Tell File Explorer to stop hiding file extensions (your user account only).
  Runs (powershell): reg add "HKCU\...\Advanced" /v HideFileExt /t REG_DWORD /d 0 /f
  Undo: reg add "HKCU\...\Advanced" /v HideFileExt /t REG_DWORD /d 1 /f
  Run it? [y = yes, n = skip, q = quit]
```

It works on Windows, macOS and Linux. It is one Python file with no extra packages.

## What it does for you

- **Asks before every step.** `y` runs it, `n` skips it, `q` stops.
- **Stops on the first failure**, so later steps don't build on a half-done change.
- **Backs up files first.** List files or folders under `backup` and they are copied to `.runner-backups/` before the step runs. If the copy fails, the step does not run. Backups are kept 7 days.
- **Writes an undo file.** After a run you get `<name>.undo-<time>.json`, which reverses what ran, newest first. Run it with the same script.
- **Keeps a log.** `<name>.log` records every step, your answer, and the exit code.
- **Runs admin steps.** Steps marked `"admin": true` show a UAC prompt on Windows, or ask for your password through `sudo` on macOS and Linux.

## Install

You need Python 3.10 or newer. Check with `python --version` (on macOS and Linux it may be `python3`).

Download the code: on this page click **Code → Download ZIP** and unzip it, or use git:

```bash
git clone https://github.com/codegarv/step-runner.git
```

```bash
cd step-runner
```

## Use it

```bash
python runner.py steps.json
```

Try the included example on Windows (it only changes a File Explorer setting for your account, and the undo file puts it back):

```bash
python runner.py show_extensions.json
```

To roll back, run the undo file it prints at the end:

```bash
python runner.py "show_extensions.undo-<time>.json"
```

## Write your own steps file

This example uses macOS and Linux commands. On Windows, write PowerShell commands instead, or add `"shell": "cmd"` to a step to use cmd.

```json
{
  "title": "Clean up my downloads",
  "steps": [
    {
      "description": "Delete the old installers folder.",
      "command": "rm -rf ~/Downloads/old-installers",
      "backup": ["~/Downloads/old-installers"]
    },
    {
      "description": "Create a folder for screenshots.",
      "command": "mkdir ~/Pictures/screenshots",
      "undo": "rmdir ~/Pictures/screenshots"
    }
  ]
}
```

Each step has:

| Field | Required | Meaning |
|---|---|---|
| `description` | yes | What the step does, in plain words. |
| `command` | yes | The exact command to run. |
| `undo` | yes, unless `backup` is set | The command that reverses it. |
| `backup` | no | Files or folders to copy before the step runs. The undo file copies them back. |
| `shell` | no | `powershell`, `cmd` or `sh`. Default: `powershell` on Windows, `sh` elsewhere. |
| `admin` | no | `true` to run with admin rights. |

## Run the tests

```bash
python test_runner.py
```

GitHub runs these on Windows, macOS and Linux on every push.

## A word of caution

The runner runs whatever command you approve, with your permissions (or admin rights if the step asks). Only run steps files you wrote or have read and trust.

## License

MIT. See [LICENSE](LICENSE).
