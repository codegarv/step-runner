"""Watches an inbox folder and opens a terminal for each steps file that lands in it.

This is how Claude hands you commands it couldn't run itself: Claude saves a steps file into the inbox,
a terminal window pops up running runner.py on it, and you answer y/n to each step as usual.
Nothing runs without your yes.

Usage:
  python watcher.py               watch ~/step-runner-inbox until you press Ctrl+C
  python watcher.py --install     Windows: also start it hidden every time you log in, and start it now
  python watcher.py --uninstall   Windows: stop starting it at login

Files must end in .steps.json. Each one is moved into inbox/done/ before its terminal opens,
so it is offered only once; its log and undo file are written there too.
"""
import os
import shlex
import subprocess
import sys
import time

INBOX = os.path.join(os.path.expanduser("~"), "step-runner-inbox")
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "runner.py")
STARTUP_FILE = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                            "step-runner-watcher.cmd")


def console_python():
    # The hidden watcher runs under pythonw, which has no console; the terminal needs python.exe to ask y/n.
    exe = sys.executable
    alt = os.path.join(os.path.dirname(exe), "python.exe")
    return alt if os.path.basename(exe).lower() == "pythonw.exe" and os.path.exists(alt) else exe


def open_terminal(steps_file):
    py = console_python()
    if os.name == "nt":
        q = lambda s: "'" + s.replace("'", "''") + "'"  # PowerShell single-quoted string
        subprocess.Popen(["powershell", "-NoProfile", "-NoExit", "-Command",
                          f"& {q(py)} {q(RUNNER)} {q(steps_file)}"],
                         creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=os.path.dirname(steps_file))
        return
    cmd = f"cd {shlex.quote(os.path.dirname(steps_file))} && {shlex.quote(py)} {shlex.quote(RUNNER)} {shlex.quote(steps_file)}"
    if sys.platform == "darwin":
        script = cmd.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"',
                          "-e", 'tell application "Terminal" to activate'])
    else:
        # shortcut: needs a desktop with x-terminal-emulator (Debian/Ubuntu); add others if someone needs them
        subprocess.Popen(["x-terminal-emulator", "-e", "sh", "-c", cmd + "; exec sh"])


def check_inbox(inbox, opener=open_terminal):
    """Move each finished *.steps.json into inbox/done/ and open a terminal for it. Returns the moved paths."""
    done_dir = os.path.join(inbox, "done")
    moved = []
    for name in sorted(os.listdir(inbox)):
        src = os.path.join(inbox, name)
        if not name.endswith(".steps.json") or not os.path.isfile(src):
            continue
        if time.time() - os.path.getmtime(src) < 1:
            continue  # may still be being written; pick it up on the next pass
        os.makedirs(done_dir, exist_ok=True)
        dst = os.path.join(done_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{name}")
        try:
            os.replace(src, dst)
        except OSError:
            continue  # another watcher took it, or it's locked; try again next pass
        try:
            opener(dst)
        except OSError as e:  # e.g. no terminal program found; the file is already in done/, so say where
            print(f"Couldn't open a terminal ({e}). Run it yourself: python runner.py \"{dst}\"")
            continue
        moved.append(dst)
    return moved


def stop_running():
    """Windows: end any hidden watcher started from this file, so install/uninstall leave exactly one or none."""
    me = os.path.abspath(__file__).replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like "
                    f"('*' + [Management.Automation.WildcardPattern]::Escape('{me}') + '*') }} | "
                    "Invoke-CimMethod -MethodName Terminate | Out-Null"])


def install():
    if os.name != "nt":
        sys.exit("--install only supports Windows so far. On Mac/Linux, add 'python watcher.py' to your login items.")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        sys.exit(f"Couldn't find {pythonw}")
    with open(STARTUP_FILE, "w", encoding="utf-8") as f:
        f.write(f'@start "" "{pythonw}" "{os.path.abspath(__file__)}"\n')
    stop_running()  # installing twice must not leave two watchers
    subprocess.Popen([pythonw, os.path.abspath(__file__)])
    print(f"Watching {INBOX} now and at every login.\nTo stop: python watcher.py --uninstall")


def uninstall():
    if os.name != "nt":
        sys.exit("--uninstall only supports Windows. On Mac/Linux, press Ctrl+C in the watcher's window.")
    if os.path.exists(STARTUP_FILE):
        os.remove(STARTUP_FILE)
    stop_running()
    print("Stopped the watcher. It won't start at login any more.")


def main():
    if sys.argv[1:] == ["--install"]:
        return install()
    if sys.argv[1:] == ["--uninstall"]:
        return uninstall()
    if sys.argv[1:]:
        sys.exit(__doc__)
    os.makedirs(INBOX, exist_ok=True)
    print(f"Watching {INBOX} for *.steps.json files. Ctrl+C to stop.")
    while True:
        try:
            for p in check_inbox(INBOX):
                print(f"Opened a terminal for {p}")
        except OSError as e:  # e.g. the inbox was deleted; recreate it and keep going
            print(f"Inbox problem ({e}); retrying.")
            os.makedirs(INBOX, exist_ok=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
