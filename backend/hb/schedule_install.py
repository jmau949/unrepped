"""`hb schedule install` / `remove` — the per-user OS schedule for the scans (docs/05 §2).

`make start` ends with `install`, so a fresh clone scans on its own from the first
day and a moved checkout re-points its jobs. Everything is per user and needs no
administrator: Task Scheduler jobs on Windows (through ops/windows-tasks.ps1),
launchd agents in ~/Library/LaunchAgents on macOS, systemd --user timers in
~/.config/systemd/user on Linux, or a marked block in the user's crontab where
there is no systemd user instance.

The three jobs are the ones every setup runs (docs/05 §2): `hb pipeline daily
--catch-up` and `hb pipeline listing-scan --catch-up` hourly on the hour, `hb
alerts send` hourly at :30, all `uv run --no-sync` from backend/. On macOS and Linux their output goes to
DATA_DIR/logs/hb-<job>.log; the Windows tasks run headless through conhost and
keep no log file (ops/windows-tasks.ps1).

`run(argv, stdin)` is the seam tests stub: every launchctl / systemctl / crontab /
powershell call goes through it.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

from hb import config
from hb.config import settings

JOBS = (  # name, hb arguments, minute past the hour
    ("daily", ("pipeline", "daily", "--catch-up"), 0),
    ("scan", ("pipeline", "listing-scan", "--catch-up"), 0),
    ("alerts", ("alerts", "send"), 30),
)
WINDOWS_TASKS = ("HB Daily Pipelines", "HB Listing Scan", "HB Alerts Send",
                 "HB SchoolDigger Catch-up")
LAUNCHD_PREFIX = "com.home-buying."
CRON_BEGIN = "# >>> home-buying schedule (hb schedule install) >>>"
CRON_END = "# <<< home-buying schedule <<<"


def run(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=stdin, capture_output=True, text=True)


def _ok(argv: list[str]) -> bool:
    try:
        return run(argv).returncode == 0
    except FileNotFoundError:
        return False


def uv_path() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is not on PATH, so the scheduled jobs could not start. Install it "
                           "(docs/11 §1) and run `make schedule` again.")
    return uv


def command(job_args: tuple[str, ...]) -> list[str]:
    return [uv_path(), "run", "--no-sync", "hb", *job_args]


def logs_dir() -> Path:
    folder = settings.data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _uid() -> int:
    return os.getuid() if hasattr(os, "getuid") else 501


def install(platform: str | None = None, home: Path | None = None) -> list[str]:
    """Set the schedule up for this user; returns lines saying what was done."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        return _install_windows()
    if platform == "darwin":
        return _install_launchd(home)
    if _ok(["systemctl", "--user", "daemon-reload"]):
        return _install_systemd_user(home)
    return _install_cron()


def remove(platform: str | None = None, home: Path | None = None) -> list[str]:
    """Undo `install`; safe when nothing is installed."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        return _remove_windows()
    if platform == "darwin":
        return _remove_launchd(home)
    return _remove_systemd_user(home) + _remove_cron()


# ---------------------------------------------------------------- Windows


def _powershell(*args: str) -> list[str]:
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args]


def _install_windows() -> list[str]:
    script = config._REPO_ROOT / "ops" / "windows-tasks.ps1"
    out = run(_powershell("-File", str(script)))
    if out.returncode != 0:
        raise RuntimeError(f"ops\\windows-tasks.ps1 failed:\n{out.stderr or out.stdout}")
    return [f"Task Scheduler: {', '.join(WINDOWS_TASKS[:3])} — hourly, as you; no administrator "
            "needed. They run while you are logged in (a locked screen is fine).",
            "To open the app from your phone on the same wifi, run ops\\windows-lan.ps1 once as "
            "Administrator (the only step that needs it)."]


def _remove_windows() -> list[str]:
    names = ",".join(f"'{n}'" for n in WINDOWS_TASKS)
    run(_powershell("-Command", f"Unregister-ScheduledTask -TaskName {names} -Confirm:$false "
                                 "-ErrorAction SilentlyContinue"))
    return [f"Task Scheduler: removed {', '.join(WINDOWS_TASKS)} (where present)"]


# ---------------------------------------------------------------- macOS (launchd)


def _plist(label: str, argv: list[str], minute: int, log: Path) -> str:
    args = "".join(f"<string>{escape(a)}</string>" for a in argv)
    path_env = ":".join([str(Path(argv[0]).parent), "/opt/homebrew/bin", "/usr/local/bin",
                         "/usr/bin", "/bin"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>WorkingDirectory</key><string>{escape(str(config._BACKEND_DIR))}</string>
  <key>StartCalendarInterval</key><dict><key>Minute</key><integer>{minute}</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{escape(path_env)}</string></dict>
</dict>
</plist>
"""


def _install_launchd(home: Path) -> list[str]:
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, args, minute in JOBS:
        label = LAUNCHD_PREFIX + name
        plist = agents / f"{label}.plist"
        plist.write_text(_plist(label, command(args), minute, logs_dir() / f"hb-{name}.log"),
                         encoding="utf-8")
        run(["launchctl", "bootout", f"gui/{_uid()}/{label}"])  # not loaded yet: fine
        out = run(["launchctl", "bootstrap", f"gui/{_uid()}", str(plist)])
        if out.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap failed for {label}: {out.stderr or out.stdout}")
        lines.append(f"launchd: {label} ({plist})")
    lines.append("Hourly while you are logged in; a run missed while the Mac slept happens as "
                 "soon as it wakes.")
    return lines


def _remove_launchd(home: Path) -> list[str]:
    agents = home / "Library" / "LaunchAgents"
    removed = []
    for name, _args, _minute in JOBS:
        label = LAUNCHD_PREFIX + name
        run(["launchctl", "bootout", f"gui/{_uid()}/{label}"])
        plist = agents / f"{label}.plist"
        if plist.exists():
            plist.unlink()
            removed.append(label)
    return [f"launchd: removed {', '.join(removed)}" if removed else "launchd: nothing installed"]


# ---------------------------------------------------------------- Linux (systemd --user)


def _unit_dir(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def _units(name: str, args: tuple[str, ...], minute: int, log: Path) -> tuple[str, str]:
    desc = f"home-buying: hb {' '.join(args)}"
    service = f"""[Unit]
Description={desc}

[Service]
Type=oneshot
WorkingDirectory={config._BACKEND_DIR}
ExecStart={shlex.join(command(args))}
StandardOutput=append:{log}
StandardError=append:{log}
"""
    timer = f"""[Unit]
Description={desc} (hourly, catch-up)

[Timer]
OnCalendar=*-*-* *:{minute:02d}:00
Persistent=true
OnStartupSec=10min

[Install]
WantedBy=timers.target
"""
    return service, timer


def _install_systemd_user(home: Path) -> list[str]:
    folder = _unit_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    timers = []
    for name, args, minute in JOBS:
        service, timer = _units(name, args, minute, logs_dir() / f"hb-{name}.log")
        (folder / f"hb-{name}.service").write_text(service, encoding="utf-8")
        (folder / f"hb-{name}.timer").write_text(timer, encoding="utf-8")
        timers.append(f"hb-{name}.timer")
    run(["systemctl", "--user", "daemon-reload"])
    out = run(["systemctl", "--user", "enable", "--now", *timers])
    if out.returncode != 0:
        raise RuntimeError(f"systemctl --user enable failed: {out.stderr or out.stdout}")
    return [f"systemd --user: {', '.join(timers)} ({folder})",
            "Hourly while you are logged in; `loginctl enable-linger` keeps them running after "
            "you log out."]


def _remove_systemd_user(home: Path) -> list[str]:
    folder = _unit_dir(home)
    present = [f"hb-{name}.timer" for name, _a, _m in JOBS if (folder / f"hb-{name}.timer").exists()]
    if not present:
        return []
    run(["systemctl", "--user", "disable", "--now", *present])
    for name, _args, _minute in JOBS:
        for suffix in (".service", ".timer"):
            path = folder / f"hb-{name}{suffix}"
            if path.exists():
                path.unlink()
    run(["systemctl", "--user", "daemon-reload"])
    return [f"systemd --user: removed {', '.join(present)}"]


# ---------------------------------------------------------------- Linux without systemd (cron)


def _cron_block() -> str:
    rows = [CRON_BEGIN]
    for name, args, minute in JOBS:
        log = logs_dir() / f"hb-{name}.log"
        rows.append(f"{minute} * * * * cd {shlex.quote(str(config._BACKEND_DIR))} && "
                    f"{shlex.join(command(args))} >> {shlex.quote(str(log))} 2>&1")
    rows.append(CRON_END)
    return "\n".join(rows)


def _without_block(text: str) -> str:
    kept, skipping = [], False
    for line in text.splitlines():
        if line.strip() == CRON_BEGIN:
            skipping = True
            continue
        if line.strip() == CRON_END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip("\n")


def _current_crontab() -> str:
    try:
        out = run(["crontab", "-l"])
    except FileNotFoundError as exc:
        raise RuntimeError("neither a systemd user instance nor crontab is available; see "
                           "ops/crontab.txt for the three jobs to schedule by hand") from exc
    return out.stdout if out.returncode == 0 else ""  # no crontab yet: exit 1


def _install_cron() -> list[str]:
    kept = _without_block(_current_crontab())
    text = (kept + "\n\n" if kept else "") + _cron_block() + "\n"
    out = run(["crontab", "-"], stdin=text)
    if out.returncode != 0:
        raise RuntimeError(f"crontab failed: {out.stderr or out.stdout}")
    return [f"crontab: 3 hourly entries between '{CRON_BEGIN}' and '{CRON_END}' "
            "(`crontab -l` shows them)",
            "cron runs them while the machine is up; a slot missed while it slept runs at the "
            "next whole hour after it wakes."]


def _remove_cron() -> list[str]:
    try:
        current = _current_crontab()
    except RuntimeError:
        return []
    if CRON_BEGIN not in current:
        return []
    kept = _without_block(current)
    if kept:
        run(["crontab", "-"], stdin=kept + "\n")
    else:
        run(["crontab", "-r"])
    return ["crontab: removed the home-buying block"]
