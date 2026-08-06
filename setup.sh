#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  First-time Setup Script
#  Installs PostgreSQL, Python deps, and configures the database.
#  Safe to run multiple times — skips steps already done.
# ═══════════════════════════════════════════════════════════════

set -e

DB_NAME="myapp"
DB_USER="myuser"
DB_PASS="changeme123"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "  ${RED}❌ $1${NC}"; exit 1; }
info() { echo -e "  → $1"; }

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Product Tracker — First-Time Setup"
echo "════════════════════════════════════════════════════════════"
echo ""

# ──────────────────────────────────────────────────────────────
# Step 1: Python dependencies
# ──────────────────────────────────────────────────────────────
echo "[1/3] Installing Python dependencies..."
if pip3 install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null; then
    ok "Python packages installed"
else
    pip3 install -q psycopg2-binary curl_cffi cloudscraper lxml apscheduler beautifulsoup4 requests matplotlib
    ok "Python packages installed (fallback)"
fi

# ──────────────────────────────────────────────────────────────
# Step 2: PostgreSQL installation
# ──────────────────────────────────────────────────────────────
echo ""
echo "[2/3] Setting up PostgreSQL..."

# Check if postgresql is installed
if ! command -v psql &>/dev/null; then
    info "Installing PostgreSQL..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq postgresql postgresql-contrib
    ok "PostgreSQL installed"
else
    ok "PostgreSQL already installed ($(psql --version | grep -oP '\d+\.\d+'))"
fi

# Start PostgreSQL
if pg_isready &>/dev/null; then
    ok "PostgreSQL is running"
else
    info "Starting PostgreSQL..."
    sudo pg_ctlcluster 17 main start 2>/dev/null || \
    sudo pg_ctlcluster 16 main start 2>/dev/null || \
    sudo pg_ctlcluster 15 main start 2>/dev/null || \
    sudo service postgresql start
    sleep 2
    if pg_isready &>/dev/null; then
        ok "PostgreSQL started"
    else
        fail "Could not start PostgreSQL"
    fi
fi

# ──────────────────────────────────────────────────────────────
# Step 3: Database & User
# ──────────────────────────────────────────────────────────────
echo ""
echo "[3/3] Configuring database..."

# Check if user exists
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    ok "User '$DB_USER' already exists"
else
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" > /dev/null 2>&1
    sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;" > /dev/null 2>&1
    ok "User '$DB_USER' created"
fi

# Check if database exists
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    ok "Database '$DB_NAME' already exists"
else
    sudo -u postgres createdb -O "$DB_USER" "$DB_NAME" > /dev/null 2>&1
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" > /dev/null 2>&1
    ok "Database '$DB_NAME' created"
fi

# Test connection
if PGPASSWORD="$DB_PASS" psql -h localhost -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1; then
    ok "Connection verified"
else
    warn "Connection test failed — may need pg_hba.conf update for password auth"
fi

# ──────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Setup Complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  DB:    postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
echo ""
echo "  Usage:"
echo "    python3 product_tracker.py <URL>        # Scrape & save"
echo "    python3 product_tracker.py --list       # View saved products"
echo "    python3 scheduler.py                    # Start scheduler"
echo ""
