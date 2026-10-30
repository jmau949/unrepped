"""hb/schedule_install — the per-user OS schedule on every platform, with every
launchctl / systemctl / crontab / powershell call recorded instead of run, so the
suite never touches the machine it runs on."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hb import config
from hb import schedule_install as si
from hb.cli import app

runner = CliRunner()


class Calls(list):
    """Recorded (argv, stdin) pairs; `failing` substrings make a call exit 1 and
    `outputs` maps a command prefix to the stdout it should return."""

    def __init__(self):
        super().__init__()
        self.failing: set[str] = set()
        self.outputs: dict[str, str] = {}


@pytest.fixture
def calls(monkeypatch, tmp_path):
    recorded = Calls()

    def fake_run(argv, stdin=None):
        recorded.append((argv, stdin))
        line = " ".join(argv)
        rc = 1 if any(f in line for f in recorded.failing) else 0
        out = next((v for k, v in recorded.outputs.items() if line.startswith(k)), "")
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="nope" if rc else "")

    monkeypatch.setattr(si, "run", fake_run)
    monkeypatch.setattr(si.shutil, "which", lambda name: "/opt/uv/bin/uv")
    monkeypatch.setattr(config.settings, "data_dir", tmp_path / "data")
    return recorded


def _argvs(calls):
    return [" ".join(argv) for argv, _stdin in calls]


def test_macos_writes_launch_agents_and_loads_them(calls, tmp_path):
    lines = si.install("darwin", home=tmp_path)

    agents = tmp_path / "Library" / "LaunchAgents"
    plists = sorted(p.name for p in agents.glob("*.plist"))
    assert plists == ["com.home-buying.alerts.plist", "com.home-buying.daily.plist",
                      "com.home-buying.scan.plist"]
    scan = (agents / "com.home-buying.scan.plist").read_text(encoding="utf-8")
    assert "<string>/opt/uv/bin/uv</string><string>run</string><string>--no-sync</string>" in scan
    assert "<string>listing-scan</string><string>--catch-up</string>" in scan
    assert f"<string>{config._BACKEND_DIR}</string>" in scan  # WorkingDirectory
    assert "<key>Minute</key><integer>0</integer>" in scan
    assert "<key>Minute</key><integer>30</integer>" in (
        agents / "com.home-buying.alerts.plist").read_text(encoding="utf-8")
    assert (tmp_path / "data" / "logs").is_dir()
    argvs = _argvs(calls)
    assert any(a.startswith("launchctl bootout gui/") and a.endswith("/com.home-buying.scan")
               for a in argvs)
    assert any(a.startswith("launchctl bootstrap gui/") and a.endswith("com.home-buying.scan.plist")
               for a in argvs)
    assert any("missed while the Mac slept" in line for line in lines)

    calls.clear()
    assert si.remove("darwin", home=tmp_path) == [
        "launchd: removed com.home-buying.daily, com.home-buying.scan, com.home-buying.alerts"]
    assert list(agents.glob("*.plist")) == []
    assert sum(a.startswith("launchctl bootout") for a in _argvs(calls)) == 3


def test_macos_reports_a_failed_bootstrap(calls, tmp_path):
    calls.failing.add("bootstrap")
    with pytest.raises(RuntimeError, match="bootstrap failed"):
        si.install("darwin", home=tmp_path)


def test_linux_with_systemd_writes_user_timers(calls, tmp_path):
    lines = si.install("linux", home=tmp_path)

    units = tmp_path / ".config" / "systemd" / "user"
    assert sorted(p.name for p in units.iterdir()) == [
        "hb-alerts.service", "hb-alerts.timer", "hb-daily.service", "hb-daily.timer",
        "hb-scan.service", "hb-scan.timer"]
    service = (units / "hb-scan.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/uv/bin/uv run --no-sync hb pipeline listing-scan --catch-up" in service
    assert f"WorkingDirectory={config._BACKEND_DIR}" in service
    timer = (units / "hb-scan.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* *:00:00" in timer and "Persistent=true" in timer
    assert "OnCalendar=*-*-* *:30:00" in (units / "hb-alerts.timer").read_text(encoding="utf-8")
    argvs = _argvs(calls)
    assert "systemctl --user enable --now hb-daily.timer hb-scan.timer hb-alerts.timer" in argvs
    assert not any(a.startswith("crontab") for a in argvs)
    assert any("enable-linger" in line for line in lines)

    calls.clear()
    assert si.remove("linux", home=tmp_path) == [
        "systemd --user: removed hb-daily.timer, hb-scan.timer, hb-alerts.timer"]
    assert list(units.iterdir()) == []
    assert "systemctl --user disable --now hb-daily.timer hb-scan.timer hb-alerts.timer" in \
        _argvs(calls)


def test_linux_without_systemd_falls_back_to_a_marked_crontab_block(calls, tmp_path):
    calls.failing.add("daemon-reload")  # no systemd user instance here
    calls.outputs["crontab -l"] = ("0 9 * * * echo hi\n\n" + si.CRON_BEGIN +
                                   "\n0 * * * * old line\n" + si.CRON_END + "\n")

    si.install("linux", home=tmp_path)

    written = next(stdin for argv, stdin in calls if argv == ["crontab", "-"])
    assert written.startswith("0 9 * * * echo hi\n\n" + si.CRON_BEGIN)  # the rest is kept
    assert "old line" not in written  # the previous block is replaced, not stacked
    assert written.count(si.CRON_BEGIN) == 1
    assert "30 * * * * cd " in written and "hb alerts send" in written
    assert "0 * * * * cd " in written and "hb pipeline listing-scan --catch-up" in written
    assert not (tmp_path / ".config").exists()

    calls.clear()
    calls.outputs["crontab -l"] = written
    assert si.remove("linux", home=tmp_path) == ["crontab: removed the home-buying block"]
    assert next(stdin for argv, stdin in calls if argv == ["crontab", "-"]) == "0 9 * * * echo hi\n"


def test_windows_runs_the_tasks_script_without_elevation(calls):
    lines = si.install("win32")
    (argv, _stdin), = calls
    assert argv[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert argv[4] == "-File" and Path(argv[5]).name == "windows-tasks.ps1"
    assert any("no administrator" in line for line in lines)
    assert any("windows-lan.ps1" in line and "Administrator" in line for line in lines)

    calls.clear()
    si.remove("win32")
    (argv, _stdin), = calls
    assert "Unregister-ScheduledTask" in argv[-1] and "'HB Listing Scan'" in argv[-1]


def test_windows_reports_a_failed_script(calls):
    calls.failing.add("windows-tasks.ps1")
    with pytest.raises(RuntimeError, match="windows-tasks.ps1 failed"):
        si.install("win32")


def test_missing_uv_is_explained(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(si.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="uv is not on PATH"):
        si.install("darwin", home=tmp_path)


def test_cli_prints_what_was_done_and_fails_loudly(monkeypatch):
    monkeypatch.setattr(si, "install", lambda: ["launchd: three agents"])
    result = runner.invoke(app, ["schedule", "install"])
    assert result.exit_code == 0 and "schedule: launchd: three agents" in result.output

    def broken():
        raise RuntimeError("uv is not on PATH")

    monkeypatch.setattr(si, "install", broken)
    assert runner.invoke(app, ["schedule", "install"]).exit_code == 1

    monkeypatch.setattr(si, "remove", lambda: ["launchd: nothing installed"])
    assert "nothing installed" in runner.invoke(app, ["schedule", "remove"]).output
