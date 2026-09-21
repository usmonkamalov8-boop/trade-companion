"""Read-only look at how the API is exposed and whether backups leave the server. Changes nothing."""
import json, re, shutil, subprocess, time
from pathlib import Path

_cache = {"t": 0, "v": None}


def _run(cmd, t=3):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
        return p.returncode, (p.stdout or "").strip()
    except Exception:
        return 127, ""


def _port():
    try:
        m = re.search(r"--port\s+(\d+)", Path("/etc/systemd/system/companion.service").read_text())
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 8000


def status():
    if _cache["v"] and time.time() - _cache["t"] < 30:
        return _cache["v"]
    port = _port()
    inst = shutil.which("tailscale") is not None
    ip = None
    if inst:
        rc, out = _run(["tailscale", "ip", "-4"])
        ip = out.splitlines()[0].strip() if rc == 0 and out else None
    locked = False
    if shutil.which("iptables"):
        rc, _ = _run(["iptables", "-C", "INPUT", "-p", "tcp", "--dport", str(port), "!", "-i", "tailscale0", "!", "-i", "lo", "-j", "DROP"])
        locked = rc == 0
    off = {}
    try:
        off = json.loads((Path.home() / ".tc_offsite_state.json").read_text())
    except Exception:
        pass
    v = {"port": port, "tailscale_installed": inst, "tailscale_ip": ip, "locked": locked,
         "backup_timer": Path("/etc/systemd/system/tc-backup.timer").exists(),
         "offsite": {"provider": off.get("provider"), "last_ok": off.get("last_ok"), "last_error": off.get("last_error")}}
    _cache["t"], _cache["v"] = time.time(), v
    return v
