#!/usr/bin/env python
"""Local development PostgreSQL in user space - no system install, no service.

    python scripts/devdb.py start     # first run: npm install + initdb + create databases, then start
    python scripts/devdb.py status | stop | createdb

Uses the official PostgreSQL 17 binaries packaged as ``@embedded-postgres/<platform>`` (npm) under
``tools/devdb``; the cluster lives in ``tools/devdb/pgdata`` (git-ignored) and listens on 127.0.0.1:5433.
The databases ``supportnova`` (app) and ``supportnova_test`` (pytest) are created for the local user
``supportnova`` - development credentials only (DEVDB_PASSWORD, default "postgres").
Deployments use a managed PostgreSQL instead (docker-compose.yml, render.yaml).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVDB = ROOT / "tools" / "devdb"
PGDATA = DEVDB / "pgdata"
PORT = int(os.environ.get("DEVDB_PORT", "5433"))
USER = "supportnova"
PASSWORD = os.environ.get("DEVDB_PASSWORD", "postgres")
DATABASES = ("supportnova", "supportnova_test")
VERSION = "17.10.0-beta.17"


def package() -> str:
    system = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return f"@embedded-postgres/{system}-{arch}"


def binary(name: str) -> str:
    exe = DEVDB / "node_modules" / package() / "native" / "bin" / (name + (".exe" if os.name == "nt" else ""))
    return str(exe)


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), check=check, text=True, capture_output=True)  # noqa: S603 - fixed local binaries


def install() -> None:
    if Path(binary("pg_ctl")).exists():
        return
    npm = shutil.which("npm")
    if not npm:
        sys.exit("npm is required to download the PostgreSQL binaries (https://nodejs.org).")
    print(f"Installing {package()}@{VERSION} into tools/devdb ...")
    subprocess.run([npm, "install", "--no-audit", "--no-fund", f"{package()}@{VERSION}"], cwd=DEVDB, check=True)  # noqa: S603


def init() -> None:
    install()  # also when a copied data folder is already in place - the binaries are not part of it
    if (PGDATA / "PG_VERSION").exists():
        return
    print("Initialising the cluster in tools/devdb/pgdata ...")
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw") as fh:
        fh.write(PASSWORD)
    try:
        run(binary("initdb"), "-D", str(PGDATA), "-U", USER, f"--pwfile={fh.name}", "-E", "UTF8", "--locale=C",
            "-A", "scram-sha-256")
    finally:
        os.unlink(fh.name)


def running() -> bool:
    return run(binary("pg_ctl"), "-D", str(PGDATA), "status", check=False).returncode == 0


def start() -> None:
    init()
    if not running():
        # No captured pipes: the server inherits pg_ctl's handles and keeps them open, so waiting for the
        # output to end would never return. The server logs to server.log instead.
        subprocess.run([binary("pg_ctl"), "-D", str(PGDATA), "-o", f"-p {PORT} -c listen_addresses=127.0.0.1",  # noqa: S603
                        "-l", str(PGDATA / "server.log"), "-w", "start"],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    createdb()
    print(f"PostgreSQL running on 127.0.0.1:{PORT} - DATABASE_URL=postgresql+psycopg://{USER}:***@127.0.0.1:{PORT}/supportnova")


def stop() -> None:
    if running():
        run(binary("pg_ctl"), "-D", str(PGDATA), "-m", "fast", "-w", "stop")
    print("stopped")


def createdb() -> None:
    import psycopg  # the backend's driver; run this script with the backend virtualenv

    with psycopg.connect(host="127.0.0.1", port=PORT, user=USER, password=PASSWORD, dbname="postgres", autocommit=True) as conn:
        existing = {r[0] for r in conn.execute("SELECT datname FROM pg_database")}
        for name in DATABASES:
            if name not in existing:
                conn.execute(f'CREATE DATABASE "{name}" OWNER "{USER}" ENCODING \'UTF8\'')
                print(f"created database {name}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    actions = {"start": start, "stop": stop, "createdb": createdb, "install": install, "init": init,
               "status": lambda: print("running" if running() else "stopped")}
    if cmd not in actions:
        sys.exit(__doc__)
    actions[cmd]()


if __name__ == "__main__":
    main()
