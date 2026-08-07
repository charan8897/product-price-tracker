#!/usr/bin/env python3
"""
Simple PostgreSQL Configuration Tool
=====================================
Automates basic PostgreSQL setup: install, configure, create user/db.

Usage:
    python3 pg_setup.py                  # Interactive mode
    python3 pg_setup.py --quick          # Quick setup with defaults
    python3 pg_setup.py --status         # Check current config
"""

import argparse
import os
import subprocess

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG DEFAULTS
# ──────────────────────────────────────────────────────────────────────────────

DEFAULTS = {
    "pg_version": "16",
    "port": 5432,
    "listen_address": "localhost",       # or '*' for remote access
    "max_connections": 100,
    "shared_buffers": "256MB",           # ~25% of RAM
    "work_mem": "4MB",
    "maintenance_work_mem": "64MB",
    "effective_cache_size": "1GB",       # ~75% of RAM
    "wal_level": "replica",
    "max_wal_size": "1GB",
    "min_wal_size": "80MB",
    "timezone": "Asia/Kolkata",
    "log_timezone": "Asia/Kolkata",
    "encoding": "UTF8",
    "db_name": "myapp",
    "db_user": "myuser",
    "db_password": "",
    "allow_remote": False,               # pg_hba.conf: allow remote connections?
}


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def run(cmd, check=True, capture=False, sudo=False):
    """Run a shell command."""
    if sudo and os.geteuid() != 0:
        cmd = f"sudo {cmd}"
    print(f"  → {cmd}")
    return subprocess.run(
        cmd, shell=True, check=check and not capture,
        capture_output=capture, text=True,
    )


def service_name():
    """Detect PostgreSQL service name."""
    for name in ["postgresql", "postgresql@16-main", "postgresql@16-main"]:
        r = subprocess.run(f"systemctl is-active {name}", shell=True,
                           capture_output=True, text=True)
        if r.stdout.strip() == "active":
            return name
    # Try pg_lsclusters
    r = subprocess.run("pg_lsclusters", shell=True, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return "postgresql"
    return "postgresql"


def find_config_dir():
    """Find PostgreSQL config directory."""
    # Try pg_lsclusters
    r = subprocess.run("pg_lsclusters -h", shell=True, capture_output=True, text=True)
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 6:
                return parts[5]  # config directory
    # Common paths
    for ver in ["16", "15", "14", "13"]:
        path = f"/etc/postgresql/{ver}/main"
        if os.path.isdir(path):
            return path
    return "/etc/postgresql/16/main"


def find_data_dir():
    """Find PostgreSQL data directory."""
    r = subprocess.run("pg_lsclusters -h", shell=True, capture_output=True, text=True)
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 6:
                return parts[5].replace("/etc/postgresql", "/var/lib/postgresql").replace("/main", "/main")
    return "/var/lib/postgresql/16/main"


# ──────────────────────────────────────────────────────────────────────────────
# CORE FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def install_postgresql(version="16"):
    """Install PostgreSQL."""
    print(f"\n{'='*50}")
    print(f"  Installing PostgreSQL {version}")
    print(f"{'='*50}")

    run("apt-get update -qq", sudo=True)
    run(f"apt-get install -y -qq postgresql postgresql-contrib", sudo=True)
    print("  ✅ PostgreSQL installed\n")


def configure_postgresql(cfg):
    """Apply configuration to postgresql.conf."""
    config_dir = find_config_dir()
    conf_file = os.path.join(config_dir, "postgresql.conf")
    hba_file = os.path.join(config_dir, "pg_hba.conf")

    print(f"\n{'='*50}")
    print(f"  Configuring PostgreSQL")
    print(f"  Config: {config_dir}")
    print(f"{'='*50}")

    # ── postgresql.conf ──
    settings = f"""
# ── Connection Settings ──
listen_addresses = '{cfg["listen_address"]}'
port = {cfg["port"]}
max_connections = {cfg["max_connections"]}

# ── Memory ──
shared_buffers = '{cfg["shared_buffers"]}'
work_mem = '{cfg["work_mem"]}'
maintenance_work_mem = '{cfg["maintenance_work_mem"]}'
effective_cache_size = '{cfg["effective_cache_size"]}'

# ── WAL ──
wal_level = '{cfg["wal_level"]}'
max_wal_size = '{cfg["max_wal_size"]}'
min_wal_size = '{cfg["min_wal_size"]}'

# ── Logging ──
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_statement = 'ddl'
log_min_duration_statement = 1000

# ── Locale ──
timezone = '{cfg["timezone"]}'
log_timezone = '{cfg["log_timezone"]}'
lc_messages = 'en_US.UTF-8'
"""

    # Write config snippet
    snippet_file = os.path.join(config_dir, "conf.d", "custom.conf")
    run(f"mkdir -p {os.path.join(config_dir, 'conf.d')}", sudo=True)
    run(f"bash -c 'cat > {snippet_file} << \"PGEOF\"\n{settings}\nPGEOF'", sudo=True)

    # Include conf.d in main config if not already
    include_line = "include_dir = 'conf.d'"
    r = run(f"grep -q \"include_dir.*conf.d\" {conf_file}", capture=True)
    if r.returncode != 0:
        run(f"bash -c 'echo \"{include_line}\" >> {conf_file}'", sudo=True)

    print("  ✅ postgresql.conf updated")

    # ── pg_hba.conf ──
    if cfg["allow_remote"]:
        hba_lines = [
            "host    all    all    0.0.0.0/0    md5",
            "host    all    all    ::/0         md5",
        ]
        for line in hba_lines:
            r = run(f"grep -qF \"{line}\" {hba_file}", capture=True)
            if r.returncode != 0:
                run(f"bash -c 'echo \"{line}\" >> {hba_file}'", sudo=True)
        print("  ✅ pg_hba.conf: remote access enabled (md5)")
    else:
        print("  ✅ pg_hba.conf: localhost only (default)")

    # ── Restart ──
    svc = service_name()
    run(f"systemctl restart {svc}", sudo=True)
    run(f"systemctl enable {svc}", sudo=True)
    print(f"  ✅ PostgreSQL restarted and enabled\n")


def create_user_and_db(cfg):
    """Create a database user and database."""
    db_user = cfg["db_user"]
    db_name = cfg["db_name"]
    db_pass = cfg["db_password"]

    print(f"\n{'='*50}")
    print(f"  Creating User & Database")
    print(f"{'='*50}")

    # Create user
    if db_pass:
        run(
            f"sudo -u postgres psql -c \"CREATE USER {db_user} WITH PASSWORD '{db_pass}';\"",
            check=False,
        )
        run(
            f"sudo -u postgres psql -c \"ALTER USER {db_user} CREATEDB;\"",
            check=False,
        )
    else:
        # Peer auth — no password
        run(
            f"sudo -u postgres createuser --createdb {db_user}",
            check=False,
        )
    print(f"  ✅ User '{db_user}' created")

    # Create database
    run(
        f"sudo -u postgres createdb -O {db_user} {db_name}",
        check=False,
    )
    print(f"  ✅ Database '{db_name}' created (owner: {db_user})")

    # Grant privileges
    run(
        f"sudo -u postgres psql -c \"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};\"",
        check=False,
    )
    print(f"  ✅ Privileges granted\n")


def show_status():
    """Show current PostgreSQL status and config."""
    print(f"\n{'='*50}")
    print(f"  PostgreSQL Status")
    print(f"{'='*50}")

    svc = service_name()
    r = run(f"systemctl is-active {svc}", capture=True)
    status = r.stdout.strip() if r.returncode == 0 else "inactive"
    icon = "🟢" if status == "active" else "🔴"
    print(f"  {icon} Service: {status}")

    # Version
    r = run("psql --version", capture=True)
    if r.returncode == 0:
        print(f"  📦 Version: {r.stdout.strip()}")

    # Port
    r = run("sudo -u postgres psql -t -c \"SHOW port;\"", capture=True)
    if r.returncode == 0:
        print(f"  🔌 Port: {r.stdout.strip()}")

    # Databases
    r = run("sudo -u postgres psql -t -c \"SELECT datname FROM pg_database WHERE datistemplate = false;\"", capture=True)
    if r.returncode == 0:
        dbs = [d.strip() for d in r.stdout.strip().splitlines() if d.strip()]
        print(f"  🗄️  Databases: {', '.join(dbs)}")

    # Connections
    r = run("sudo -u postgres psql -t -c \"SELECT count(*) FROM pg_stat_activity;\"", capture=True)
    if r.returncode == 0:
        print(f"  🔗 Active connections: {r.stdout.strip()}")

    # Config dir
    config_dir = find_config_dir()
    print(f"  📁 Config: {config_dir}")
    print(f"{'='*50}\n")


def verify_connection(cfg):
    """Test the connection with the new user."""
    db_user = cfg["db_user"]
    db_name = cfg["db_name"]

    print(f"\n{'='*50}")
    print(f"  Verifying Connection")
    print(f"{'='*50}")

    r = run(
        f"sudo -u postgres psql -c \"\\conninfo\"",
        capture=True,
    )
    if r.returncode == 0:
        print(f"  ✅ postgres superuser: OK")

    r = run(
        f"psql -U {db_user} -d {db_name} -c \"SELECT current_user, current_database();\"",
        capture=True,
    )
    if r.returncode == 0:
        print(f"  ✅ {db_user}@{db_name}: OK")
        print(f"     {r.stdout.strip()}")
    else:
        print(f"  ⚠️  {db_user}@{db_name}: Could not connect (may need password)")
        print(f"     Try: psql -U {db_user} -d {db_name}")

    print()


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def interactive_config():
    """Interactive configuration wizard."""
    cfg = DEFAULTS.copy()

    print(f"\n{'='*50}")
    print("  PostgreSQL Configuration Wizard")
    print(f"{'='*50}\n")

    print("Press Enter to accept defaults shown in [brackets]\n")

    cfg["port"] = int(input(f"  Port [{DEFAULTS['port']}]: ").strip() or DEFAULTS["port"])
    cfg["listen_address"] = input(f"  Listen address [{DEFAULTS['listen_address']}]: ").strip() or DEFAULTS["listen_address"]
    cfg["max_connections"] = int(input(f"  Max connections [{DEFAULTS['max_connections']}]: ").strip() or DEFAULTS["max_connections"])
    cfg["shared_buffers"] = input(f"  Shared buffers [{DEFAULTS['shared_buffers']}]: ").strip() or DEFAULTS["shared_buffers"]
    cfg["work_mem"] = input(f"  Work mem [{DEFAULTS['work_mem']}]: ").strip() or DEFAULTS["work_mem"]
    cfg["effective_cache_size"] = input(f"  Effective cache size [{DEFAULTS['effective_cache_size']}]: ").strip() or DEFAULTS["effective_cache_size"]
    cfg["timezone"] = input(f"  Timezone [{DEFAULTS['timezone']}]: ").strip() or DEFAULTS["timezone"]
    cfg["db_name"] = input(f"  Database name [{DEFAULTS['db_name']}]: ").strip() or DEFAULTS["db_name"]
    cfg["db_user"] = input(f"  Database user [{DEFAULTS['db_user']}]: ").strip() or DEFAULTS["db_user"]

    pwd = input(f"  Password (blank = peer auth): ").strip()
    cfg["db_password"] = pwd

    remote = input(f"  Allow remote connections? [y/N]: ").strip().lower()
    cfg["allow_remote"] = remote in ("y", "yes")
    if cfg["allow_remote"]:
        cfg["listen_address"] = "*"

    return cfg


def quick_setup():
    """Quick setup with sensible defaults."""
    cfg = DEFAULTS.copy()
    cfg["db_password"] = "changeme123"
    cfg["allow_remote"] = False
    return cfg


def main():
    parser = argparse.ArgumentParser(description="Simple PostgreSQL Configuration Tool")
    parser.add_argument("--quick", action="store_true", help="Quick setup with defaults")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--install-only", action="store_true", help="Just install, don't configure")
    parser.add_argument("--no-create-db", action="store_true", help="Skip user/db creation")
    args = parser.parse_args()

    # Status check
    if args.status:
        show_status()
        return

    # Determine config
    if args.quick:
        cfg = quick_setup()
        print("\n⚡ Quick setup with defaults")
    else:
        cfg = interactive_config()

    # Install
    install_postgresql()

    if args.install_only:
        print("✅ Installation complete. Run without --install-only to configure.\n")
        return

    # Configure
    configure_postgresql(cfg)

    # Create user & DB
    if not args.no_create_db:
        create_user_and_db(cfg)
        verify_connection(cfg)

    # Final status
    show_status()

    # Print connection string
    if cfg["db_password"]:
        print(f"  📋 Connection string:")
        print(f"     postgresql://{cfg['db_user']}:{cfg['db_password']}@localhost:{cfg['port']}/{cfg['db_name']}")
    else:
        print(f"  📋 Connect with:")
        print(f"     psql -U {cfg['db_user']} -d {cfg['db_name']}")
    print()


if __name__ == "__main__":
    main()
