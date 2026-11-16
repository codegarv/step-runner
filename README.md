# step-runner

Run a list of commands one at a time, and say yes or no to each before it runs.

You write the steps in a JSON file. For each step the runner shows what it does, the exact command, and how to undo it, then asks:

```
Step 1/1: Tell File Explorer to stop hiding file extensions (your user account only).
  Runs (powershell): reg add "HKCU\...\Advanced" /v HideFileExt /t REG_DWORD /d 0 /f
  Undo: reg add "HKCU\...\Advanced" /v HideFileExt /t REG_DWORD /d 1 /f
  Run it? [y = yes, n = skip, q = quit]
```

The runner works on Windows, macOS and Linux. The watcher (see below) is fully supported only on Windows. It is plain Python with no extra packages.

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

## Let Claude hand you commands it can't run

Sometimes Claude can save files on your computer but isn't allowed to type into a terminal. The watcher closes that gap: Claude saves a steps file into an inbox folder, a terminal window pops up by itself, and you answer y/n as usual.

Turn it on once (Windows). It starts hidden now and at every login:

```bash
python watcher.py --install
```

Turn it off (stops the running watcher and removes it from login):

```bash
python watcher.py --uninstall
```

If you move the step-runner folder or reinstall Python, run `--install` again. The login entry remembers the old paths and otherwise fails without telling you.

On macOS or Linux, run `python watcher.py` and leave that window open (Ctrl+C stops it). This has not been tested on a real Mac or Linux desktop. On Linux it needs `x-terminal-emulator` (Debian and Ubuntu have it). If no terminal opens, the watcher prints the command to run yourself.

Then tell Claude how to use it. This only works where Claude can save files on your computer: Claude Code, or a Claude app with computer use (control of your screen). A claude.ai chat in a browser or the phone app can't reach your disk, so it can't use the inbox. Paste this into your Claude instructions (for example `~/.claude/CLAUDE.md` for Claude Code):

```text
When you need a command run on my computer and you can't run it yourself, save it as a
step-runner steps file in ~/step-runner-inbox/ with a name ending in .steps.json.
Format: {"title": "...", "steps": [{"description": "...", "command": "...", "undo": "..."}]}
Use PowerShell commands on Windows. Use "backup": [paths] for anything that deletes or overwrites.
If you can't save files directly but can control apps, open Notepad, type the file, and save it
there with "Save as type: All files". A terminal will open and I will approve each step.
```

How it behaves:

- It checks `~/step-runner-inbox` every 2 seconds for files ending in `.steps.json`.
- Each file is moved into `~/step-runner-inbox/done/` before its terminal opens, so it's offered once. Its log and undo file land there too.
- **Nothing runs without your `y`.** Any program that can write to that folder can put a prompt in front of you, so read every step before you approve it.
- The new terminal may open behind your other windows. Look for it in the taskbar.
- The Notepad route (Claude typing the file into Notepad) has not been tested end to end yet.

## What it can't do

- **It can't work inside apps or web pages.** Commands can open a website, an app, a file or a folder, but can't click, type, or read what's on screen. Sending a message, filling a form, or changing a website setting (like your claude.ai profile) is up to you, or to Claude in Chrome, a browser extension that lets Claude click and type in pages. Claude in Chrome works only in Google Chrome, not Edge, Brave, Arc, Firefox or Safari.
- **It can't change things stored online**, like account settings, except by opening the page for you.
- **It can't fix a wrong command.** It runs exactly what's written. If a command has a typo or a wrong path, running it again fails again.
- **It never runs anything unattended.** Every step waits for your `y`, so it needs you at the keyboard. This is on purpose.
- **Undo has limits.**
  - An undo is only as good as its `undo` command. Some steps can't really be undone (for example, "close the browser tab yourself").
  - Restoring a backed-up folder copies the old files back but doesn't delete files added since.
  - Backups are deleted after 7 days.
- **Admin steps run in a hidden window.** Their output appears only after they finish. An admin command that waits for you to type something will hang with nothing on screen.
- **No time limit.** A command that never finishes keeps the runner waiting until you close the window.

## Run the tests

```bash
python test_runner.py
```

GitHub runs these on Windows, macOS and Linux on every push.

## A word of caution

The runner runs whatever command you approve, with your permissions (or admin rights if the step asks). Only run steps files you wrote or have read and trust.

## License

MIT. See [LICENSE](LICENSE).
