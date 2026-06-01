from subprocess import CompletedProcess

from cs2webui.host.diagnostics import LinuxDiagnostics


def test_linux_diagnostics_reads_available_ufw_rules(monkeypatch) -> None:
    monkeypatch.setattr(
        "cs2webui.host.diagnostics.shutil.which",
        lambda command: "/usr/sbin/ufw" if command == "ufw" else None,
    )
    monkeypatch.setattr(
        "cs2webui.host.diagnostics.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(
            args[0],
            0,
            "Status: active\n27015/udp ALLOW Anywhere\n",
            "",
        ),
    )

    firewall, rules = LinuxDiagnostics._firewall_report()

    assert firewall == "ufw"
    assert rules == ("Status: active", "27015/udp ALLOW Anywhere")
