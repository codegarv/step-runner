"""Self-test for runner.py. Works on Windows, Linux and macOS: python test_runner.py"""
import builtins, glob, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "runner.py")
sys.path.insert(0, HERE)
import runner

WIN = os.name == "nt"


def touch(p, shell):
    if shell == "powershell":
        return f'New-Item -ItemType File -Path "{p}" | Out-Null'
    if shell == "cmd":
        return f'type nul > "{p}"'
    return f'touch "{p.replace(os.sep, "/")}"'


def remove(p, shell):
    if shell == "powershell":
        return f'Remove-Item -Recurse -Force "{p}"'
    if shell == "cmd":
        return f'if exist "{p}\\" (rmdir /s /q "{p}") else (del /q "{p}")'
    return f'rm -rf "{p.replace(os.sep, "/")}"'


def exit_code(n, shell):
    return f"exit /b {n}" if shell == "cmd" else f"exit {n}"


def run(steps_file, answers):
    r = subprocess.run([sys.executable, RUNNER, steps_file], input=answers, text=True, capture_output=True)
    return r.stdout + r.stderr


def write(d, name, steps):
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"title": name, "steps": steps}, f)
    return path


def only_undo_file(d, stem):
    files = sorted(glob.glob(os.path.join(d, f"{stem}.undo-*.json")), key=os.path.getmtime)
    assert files, f"no undo file for {stem}"
    return files[-1]


shells = [runner.default_shell()]
if WIN:
    shells.append("cmd")
    if shutil.which("sh"):
        shells.append("sh")  # Git Bash's sh: exercises the Linux/Mac command path on Windows

for sh in shells:
    with tempfile.TemporaryDirectory() as d:
        # 1. yes runs, no skips, a failure stops the rest, and the log records it all
        made, skipped, after = (os.path.join(d, n) for n in ("made.txt", "skipped.txt", "after.txt"))
        steps = write(d, "basic.json", [
            {"description": "create", "command": touch(made, sh), "undo": remove(made, sh), "shell": sh},
            {"description": "answer no", "command": touch(skipped, sh), "undo": "x", "shell": sh},
            {"description": "fails", "command": exit_code(3, sh), "undo": "x", "shell": sh},
            {"description": "after failure", "command": touch(after, sh), "undo": "x", "shell": sh},
        ])
        out = run(steps, "y\nn\ny\ny\n")
        assert os.path.exists(made), out
        assert not os.path.exists(skipped), "'n' must skip the step"
        assert "exit code 3" in out and not os.path.exists(after), "a failed step must stop the run\n" + out
        log = open(os.path.join(d, "basic.log"), encoding="utf-8").read()
        assert log.count("\tran\t") == 2 and "\tskipped\t" in log, log
        run(only_undo_file(d, "basic"), "y\n")
        assert not os.path.exists(made), "undo command must reverse the step"

        # 2. deleting a folder: backed up first, undo restores it, undoing the undo is backed up too
        folder = os.path.join(d, "important")
        os.makedirs(folder)
        with open(os.path.join(folder, "notes.txt"), "w") as f:
            f.write("keep me")
        steps = write(d, "delete.json", [
            {"description": "delete folder", "command": remove(folder, sh), "backup": [folder], "shell": sh}])
        out = run(steps, "y\n")
        assert not os.path.exists(folder), out
        assert glob.glob(os.path.join(d, ".runner-backups", "*", "*", "notes.txt")), "backup must exist"
        undo = only_undo_file(d, "delete")
        out = run(undo, "y\n")
        assert open(os.path.join(folder, "notes.txt")).read() == "keep me", "undo must restore the folder\n" + out
        redo = only_undo_file(d, os.path.splitext(os.path.basename(undo))[0])
        assert json.load(open(redo))["steps"][0]["backup"], "undoing the undo must back up first"

        # 3. if the backup fails, the step must not run
        steps = write(d, "nobackup.json", [
            {"description": "backup fails", "command": touch(after, sh), "backup": [folder], "shell": sh}])

        def broken_copy(*_):
            raise OSError("simulated copy failure")

        real_copy, real_input, real_argv = runner.copy_path, builtins.input, sys.argv
        runner.copy_path, builtins.input, sys.argv = broken_copy, (lambda *_: "y"), ["runner.py", steps]
        try:
            runner.main()
        finally:
            runner.copy_path, builtins.input, sys.argv = real_copy, real_input, real_argv
        assert not os.path.exists(after), "a step whose backup failed must not run"
    print(f"ok: {sh}")

with tempfile.TemporaryDirectory() as d:
    # 4. admin plumbing: the separate process runs the step and reports its exit code.
    #    Windows uses verb "open" here so no UAC prompt appears; Linux/Mac only if sudo needs no password.
    p = os.path.join(d, "elevated.txt")
    sh = runner.default_shell()
    if WIN:
        assert runner.run_elevated({"command": touch(p, sh), "shell": sh}, verb="open") == 0
        assert os.path.exists(p), "separate process must run the command"
        assert runner.run_elevated({"command": exit_code(4, sh), "shell": sh}, verb="open") == 4

        # The admin process must find the output file already there (made by us, so we can read it back),
        # and an unreadable output file must not crash the runner after the step ran.
        real_wait = runner.shell_execute_wait

        def check_out_exists(verb, argv):
            out = json.load(open(argv[-1], encoding="utf-8"))["out"]
            assert os.path.exists(out), "output file must exist before the admin process starts"
            return real_wait(verb, argv)

        def lose_output(verb, argv):
            os.remove(json.load(open(argv[-1], encoding="utf-8"))["out"])
            return 0

        try:
            runner.shell_execute_wait = check_out_exists
            assert runner.run_elevated({"command": exit_code(0, sh), "shell": sh}, verb="open") == 0
            runner.shell_execute_wait = lose_output
            assert runner.run_elevated({"command": "x", "shell": sh}) == 0, "missing output must not crash"
        finally:
            runner.shell_execute_wait = real_wait
        print("ok: admin process plumbing (UAC prompt itself not tested)")
    elif subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        assert runner.run_elevated({"command": touch(p, sh), "shell": sh}) == 0 and os.path.exists(p)
        assert runner.run_elevated({"command": exit_code(4, sh), "shell": sh}) == 4
        print("ok: sudo plumbing")
    else:
        print("skipped: sudo needs a password here")

    # 5. bad steps files are rejected before anything runs
    for bad in ([{"description": "no undo", "command": "echo hi"}],
                [{"description": "bad shell", "command": "echo hi", "undo": "x", "shell": "zsh"}],
                [{"description": "bad backup", "command": "echo hi", "backup": "not-a-list"}]):
        path = write(d, "bad.json", bad)
        assert subprocess.run([sys.executable, RUNNER, path], capture_output=True).returncode != 0, bad

import watcher

with tempfile.TemporaryDirectory() as d:
    # 6. watcher: a finished *.steps.json is moved to done/ and offered once; other and half-written files are left
    opened = []
    path = write(d, "job.steps.json", [{"description": "x", "command": "x", "undo": "x"}])
    write(d, "notes.json", [])
    fresh = write(d, "fresh.steps.json", [])
    old = time.time() - 5
    for p in (path, os.path.join(d, "notes.json")):
        os.utime(p, (old, old))
    moved = watcher.check_inbox(d, opened.append)
    assert len(moved) == 1 and opened == moved and moved[0].startswith(os.path.join(d, "done")), moved
    assert not os.path.exists(path) and os.path.exists(moved[0]), "file must move into done/"
    assert os.path.exists(fresh), "a file still being written must wait for the next pass"
    assert watcher.check_inbox(d, opened.append) == [] and len(opened) == 1, "each file is offered only once"

    def no_terminal(_):
        raise FileNotFoundError("x-terminal-emulator")

    lost = write(d, "noterm.steps.json", [])
    os.utime(lost, (old, old))
    assert watcher.check_inbox(d, no_terminal) == [], "a terminal that can't open must not crash the watcher"
    print("ok: watcher")

print("all runner checks passed")
