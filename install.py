#!/usr/bin/env python3
"""One-command installer for the Trade Companion backend (run as root on the VPS).

    python3 install.py
"""
import os, secrets, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BE = ROOT / "backend"
ENV = BE / ".env"


def sh(cmd):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True)


def read_env(p):
    d = {}
    try:
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except Exception:
        pass
    return d


def ask(label, default=""):
    shown = f" [{default}]" if default else ""
    return input(f"{label}{shown}: ").strip() or default


def main():
    if os.geteuid() != 0:
        sys.exit("Run this as root (you need systemd and apt).")
    prev = read_env(Path.home() / "companion" / ".env")  # settings from an earlier attempt, if any
    if not ENV.exists():
        print("\nBinance keys let the app show positions/PnL and use Close All.")
        print("Use a key with Futures enabled, withdrawals OFF, restricted to this VPS IP. Enter = skip.\n")
        key = ask("Binance API key", prev.get("BINANCE_API_KEY", ""))
        sec = ask("Binance API secret", prev.get("BINANCE_API_SECRET", ""))
        svc = ask("Bot systemd service name", prev.get("BOT_SERVICE", "crypto_bot"))
        port = ask("Port", "8000")
        token = prev.get("API_TOKEN") or secrets.token_urlsafe(32)
        ENV.write_text(f"API_TOKEN={token}\nBINANCE_API_KEY={key}\nBINANCE_API_SECRET={sec}\n"
                       f"BOT_SERVICE={svc}\nPORT={port}\n")
        ENV.chmod(0o600)
    env = read_env(ENV)
    port = env.get("PORT", "8000")

    sh("apt-get install -y -q python3-venv python3-pip curl")
    sh(f"cd {BE} && python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt")
    sh(f"cd {BE} && ./venv/bin/python -c 'from app import bot; bot.save(bot.load())'")

    unit = f"""[Unit]
Description=Trade Companion API
After=network-online.target

[Service]
WorkingDirectory={BE}
EnvironmentFile={ENV}
ExecStart={BE}/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port {port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/companion.service").write_text(unit)
    sh("systemctl daemon-reload && systemctl enable companion && systemctl restart companion")
    sh(f"ufw allow {port}/tcp")
    time.sleep(3)
    sh(f"curl -s localhost:{port}/ping")
    try:
        ip = subprocess.check_output("curl -s -m 5 https://api.ipify.org", shell=True, text=True).strip()
    except Exception:
        ip = "YOUR_VPS_IP"
    print(f"\n\nDONE\n  Host : {ip}:{port}\n  Token: {env['API_TOKEN']}\n")
    print("Enter both in the app under Settings.")
    print(f"Let the bot obey Halt / risk settings: cp {BE}/bot_gate.py <your bot folder> (see README).")


main()
