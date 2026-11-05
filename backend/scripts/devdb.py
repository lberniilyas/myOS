"""Manage a project-local PostgreSQL cluster for development and tests.

The cluster lives in backend/.devdb and listens on localhost only, so it never
touches a system-wide PostgreSQL installation.

Usage:
    python scripts/devdb.py init     # create the cluster, role and databases, then start it
    python scripts/devdb.py start
    python scripts/devdb.py stop
    python scripts/devdb.py status

Environment:
    PG_BIN       folder containing pg_ctl/initdb/psql (auto-detected when unset)
    DEVDB_PORT   port to listen on (default 5433)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEVDB_DIR = BACKEND_DIR / ".devdb"
DATA_DIR = DEVDB_DIR / "data"
LOG_FILE = DEVDB_DIR / "postgres.log"
PORT = int(os.environ.get("DEVDB_PORT", "5433"))
ROLE = "personal_os"
PASSWORD = "personal_os"
DATABASES = ("personal_os", "personal_os_test")


def find_pg_bin() -> Path:
    if env_bin := os.environ.get("PG_BIN"):
        return Path(env_bin)
    if found := shutil.which("pg_ctl"):
        return Path(found).parent
    if os.name == "nt":
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
        candidates = [p for p in root.glob("*") if (p / "bin" / "pg_ctl.exe").exists()]
        candidates.sort(key=lambda p: int(p.name) if p.name.isdigit() else 0)
        if candidates:
            return candidates[-1] / "bin"
    sys.exit("PostgreSQL binaries not found. Set PG_BIN to the folder that contains pg_ctl.")


PG_BIN = find_pg_bin()


def tool(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    return str(PG_BIN / f"{name}{suffix}")


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PGPASSWORD": PASSWORD}
    return subprocess.run(args, check=check, text=True, capture_output=True, env=env)


def is_running() -> bool:
    if not (DATA_DIR / "PG_VERSION").exists():
        return False
    return run([tool("pg_ctl"), "-D", str(DATA_DIR), "status"], check=False).returncode == 0


def start() -> None:
    if is_running():
        print(f"Dev database already running on localhost:{PORT}")
        return
    DEVDB_DIR.mkdir(parents=True, exist_ok=True)
    platform_kwargs: dict = {}
    if os.name == "nt":
        # Without a console of its own, the server can no longer spawn backends once the
        # launching terminal closes (they fail with 0xC0000142), so give it a hidden one.
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        platform_kwargs = {
            "creationflags": subprocess.CREATE_NEW_CONSOLE,
            "startupinfo": startupinfo,
        }
    # The server inherits pg_ctl's stdout/stderr, so capturing them would block until it exits.
    returncode = subprocess.call(
        [
            tool("pg_ctl"),
            "-D",
            str(DATA_DIR),
            "-l",
            str(LOG_FILE),
            "-o",
            f"-p {PORT} -c listen_addresses=localhost",
            "-w",
            "start",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **platform_kwargs,
    )
    if returncode != 0:
        sys.exit(f"Could not start the dev database. See {LOG_FILE}")
    print(f"Dev database started on localhost:{PORT}")


def stop() -> None:
    if not is_running():
        print("Dev database is not running")
        return
    run([tool("pg_ctl"), "-D", str(DATA_DIR), "-m", "fast", "-w", "stop"])
    print("Dev database stopped")


def create_databases() -> None:
    for database in DATABASES:
        exists = run(
            [
                tool("psql"),
                "-h",
                "localhost",
                "-p",
                str(PORT),
                "-U",
                ROLE,
                "-d",
                "postgres",
                "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname = '{database}'",
            ]
        ).stdout.strip()
        if exists == "1":
            print(f"Database {database} already exists")
            continue
        run([tool("createdb"), "-h", "localhost", "-p", str(PORT), "-U", ROLE, database])
        print(f"Created database {database}")


def init() -> None:
    if (DATA_DIR / "PG_VERSION").exists():
        print(f"Cluster already initialized in {DATA_DIR}")
    else:
        DEVDB_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw") as pwfile:
            pwfile.write(PASSWORD)
        try:
            result = run(
                [
                    tool("initdb"),
                    "-D",
                    str(DATA_DIR),
                    "-U",
                    ROLE,
                    f"--pwfile={pwfile.name}",
                    "--auth=scram-sha-256",
                    "--encoding=UTF8",
                    "--no-locale",
                ],
                check=False,
            )
        finally:
            os.unlink(pwfile.name)
        if result.returncode != 0:
            print(result.stdout, result.stderr, sep="\n")
            sys.exit("initdb failed")
        print(f"Initialized cluster in {DATA_DIR}")
    start()
    create_databases()
    print(f"DATABASE_URL=postgresql+psycopg://{ROLE}:{PASSWORD}@localhost:{PORT}/personal_os")


def status() -> None:
    state = "running" if is_running() else "stopped"
    print(f"Dev database is {state} (data: {DATA_DIR}, port: {PORT}, binaries: {PG_BIN})")


COMMANDS = {"init": init, "start": start, "stop": stop, "status": status}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()
