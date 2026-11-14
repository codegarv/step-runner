"""Step runner: shows each step from a JSON file, asks yes/no, and runs only what you approve.

Usage:  python runner.py steps.json

Steps file format:
{
  "title": "Show file extensions",
  "steps": [
    {"description": "what it does, in plain words",
     "command": "the exact command",
     "undo":    "the exact command that reverses it (may be left out if 'backup' covers it)",
     "backup":  ["files or folders this step changes or deletes"],    optional
     "shell":   "powershell" | "cmd" | "sh",   optional; default powershell on Windows, sh elsewhere
     "admin":   true | false}                  optional; Windows shows a UAC prompt, Linux/Mac uses sudo
  ]
}

Before a step runs, every path in "backup" is copied to .runner-backups/ next to the steps file.
Backups older than KEEP_DAYS are removed when the runner starts. If a backup fails, the step does not run.

After a run it writes:
  <name>.log                  every step, your answer, and the exit code (appended)
  <name>.undo-<time>.json     a steps file that reverses what ran, newest first: it runs each
                              undo command and copies backed-up files back. Run it with this script.
"""
import ctypes
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

KEEP_DAYS = 7
SHELLS = ("powershell", "cmd", "sh")


def load_steps(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        sys.exit(f'{path}: needs a non-empty "steps" list')
    text = lambda v: isinstance(v, str) and v.strip()
    for i, s in enumerate(steps, 1):
        where = f"{path}: step {i}"
        if not isinstance(s, dict) or not text(s.get("description")):
            sys.exit(f"{where} needs a description")
        if not text(s.get("command")) and not s.get("restore"):
            sys.exit(f"{where} needs a command")
        backup = s.get("backup", [])
        if not isinstance(backup, list) or not all(text(p) for p in backup):
            sys.exit(f"{where}: backup must be a list of paths")
        restore = s.get("restore", [])
        if not isinstance(restore, list) or not all(isinstance(r, list) and len(r) == 2 and all(map(text, r)) for r in restore):
            sys.exit(f"{where}: restore must be a list of [saved, original] path pairs")
        if not text(s.get("undo")) and not backup and not restore:
            sys.exit(f"{where} needs an undo command or a backup list")
        if s.get("shell", default_shell()) not in SHELLS:
            sys.exit(f"{where}: shell must be one of {', '.join(SHELLS)}")
        if os.name != "nt" and s.get("shell") in ("powershell", "cmd"):
            sys.exit(f"{where}: {s['shell']} only works on Windows")
    return data.get("title") or os.path.basename(path), steps


def default_shell():
    return "powershell" if os.name == "nt" else "sh"


def is_admin():
    if os.name != "nt":
        return os.geteuid() == 0
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def shell_args(shell, command):
    if shell == "cmd":
        # /s keeps the quotes inside the command exactly as written.
        return f'cmd /d /s /c "{command}"'
    if shell == "powershell":
        return ["powershell", "-NoProfile", "-Command", command]
    return ["sh", "-c", command]


def copy_path(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)  # shortcut: merges into an existing folder, never deletes extra files in it
    else:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)


def execute(step, out=None):
    """Run the step's command, then copy back any restored files. Returns an exit code."""
    code = 0
    if step.get("command", "").strip():
        code = subprocess.run(shell_args(step.get("shell", default_shell()), step["command"]),
                              stdout=out, stderr=subprocess.STDOUT if out else None).returncode
    if code == 0:
        for saved, original in step.get("restore", []):
            if not os.path.exists(saved):
                print(f"  Backup is gone (older than {KEEP_DAYS} days?): {saved}", file=out or sys.stdout)
                return 1
            copy_path(saved, original)
    return code


def run_elevated(step, verb="runas"):
    """Run one step in a separate admin process and return its exit code. Output is shown afterwards."""
    with tempfile.TemporaryDirectory() as d:
        job, out = os.path.join(d, "job.json"), os.path.join(d, "out.txt")
        with open(job, "w", encoding="utf-8") as f:
            json.dump({"step": step, "out": out, "cwd": os.getcwd()}, f)
        helper = [sys.executable, os.path.abspath(__file__), "--elevated-step", job]
        if os.name != "nt":
            code = subprocess.run(["sudo"] + helper).returncode  # sudo asks for your password in this terminal
        else:
            code = shell_execute_wait(verb, helper)
        if os.path.exists(out):
            print(open(out, encoding="utf-8", errors="replace").read(), end="")
        return code


def shell_execute_wait(verb, argv):
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40,  # keep the process handle
                             lpVerb=verb, lpFile=argv[0], lpParameters=subprocess.list2cmdline(argv[1:]),
                             nShow=0)  # hidden window; output comes back through the file
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        print("  Admin prompt was declined or failed.")
        return 1
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return code.value


def elevated_step(job_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    os.chdir(job["cwd"])
    with open(job["out"], "w", encoding="utf-8") as out:
        code = execute(job["step"], out)
    sys.exit(code)


def prune_backups(root):
    if not os.path.isdir(root):
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
            shutil.rmtree(p, ignore_errors=True)
            print(f"Removed backup older than {KEEP_DAYS} days: {p}")


def back_up(paths, folder):
    """Copy each existing path into folder. Returns [(saved, original)]; raises if a copy fails."""
    saved = []
    for j, p in enumerate(paths):
        original = os.path.abspath(os.path.expanduser(p))
        if not os.path.exists(original):
            print(f"  Nothing to back up (doesn't exist yet): {original}")
            continue
        dst = os.path.join(folder, f"{j}_{os.path.basename(original.rstrip(os.sep)) or 'root'}")
        copy_path(original, dst)
        saved.append((dst, original))
    return saved


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--elevated-step":
        return elevated_step(sys.argv[2])
    if len(sys.argv) != 2:
        sys.exit("usage: python runner.py steps.json")
    path = sys.argv[1]
    title, steps = load_steps(path)
    stem = os.path.splitext(path)[0]
    stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    backup_root = os.path.join(os.path.dirname(os.path.abspath(path)), ".runner-backups")
    prune_backups(backup_root)
    done = []  # (step, [(saved, original)])

    def log(status, step, code=""):
        with open(stem + ".log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{status}\t{code}\t{step.get('command', '')}\n")

    print(f"== {title}: {len(steps)} step(s) ==")
    for i, s in enumerate(steps, 1):
        print(f"\nStep {i}/{len(steps)}: {s['description']}")
        print(f"  Runs ({s.get('shell', default_shell())}{', as admin' if s.get('admin') else ''}): {s.get('command') or '(nothing)'}")
        if s.get("restore"):
            print("  Copies back: " + ", ".join(orig for _, orig in s["restore"]))
        if s.get("backup"):
            print(f"  Backs up first (kept {KEEP_DAYS} days): " + ", ".join(s["backup"]))
        print(f"  Undo: {s.get('undo') or ('restore the backup' if s.get('backup') else '(none)')}")
        try:
            answer = input("  Run it? [y = yes, n = skip, q = quit] ").strip().lower()
        except EOFError:
            answer = "q"
        if answer == "q":
            log("quit", s)
            break
        if answer not in ("y", "yes"):
            print("  Skipped.")
            log("skipped", s)
            continue
        try:
            saved = back_up(s.get("backup", []), os.path.join(backup_root, f"{stamp}-step{i}"))
        except OSError as e:
            print(f"  Backup failed ({e}). Step not run, and stopping.")
            log("backup-failed", s)
            break
        code = run_elevated(s) if s.get("admin") and not is_admin() else execute(s)
        log("ran", s, code)
        if code != 0:
            print(f"  Failed (exit code {code}). Stopping so later steps don't build on a half-done change.")
            if saved:
                print(f"  Its backup is in {os.path.dirname(saved[0][0])}")
            break
        print("  Done.")
        done.append((s, saved))

    undo_steps = [{"description": "Undo: " + s["description"],
                   "command": s.get("undo", ""),
                   "undo": s.get("command", ""),
                   "restore": saved,
                   # same paths get backed up again before the undo, so undoing the undo can't lose anything
                   "backup": [os.path.abspath(os.path.expanduser(p)) for p in s.get("backup", [])],
                   "shell": s.get("shell", default_shell()),
                   "admin": bool(s.get("admin"))} for s, saved in reversed(done) if s.get("undo") or saved]
    print(f"\n{len(done)} step(s) ran.")
    if undo_steps:
        undo_path = f"{stem}.undo-{stamp}.json"
        with open(undo_path, "w", encoding="utf-8") as f:
            json.dump({"title": "Undo " + title, "steps": undo_steps}, f, indent=2)
        print(f"To roll back (backups kept {KEEP_DAYS} days): python runner.py \"{undo_path}\"")


if __name__ == "__main__":
    main()
