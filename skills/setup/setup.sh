#!/usr/bin/env bash
# setup.sh — verify and auto-fix the dev environment for this repo.
#
# Usage:
#   bash skills/setup/setup.sh check   Read-only. Prints a pass/fail summary. Exits non-zero on failure.
#   bash skills/setup/setup.sh fix     Runs project-level auto-fixes. Idempotent.
set -uo pipefail
# -e is intentionally omitted: check functions are expected to return non-zero on failure.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OS_IMAGE="opensearchproject/opensearch:2.19.0"
PYTHON_MIN="3.13"
NODE_MIN="20"

# --- reporting ---------------------------------------------------------------
ROWS=()
OVERALL_OK=1

record() {
  ROWS+=("${1}"$'\x1f'"${2}"$'\x1f'"${3}")
  if [ "$1" = "FAIL" ]; then
    OVERALL_OK=0
  fi
}
pass() { record "PASS" "$1" "$2"; }
fail() { record "FAIL" "$1" "$2"; }
warn() { record "WARN" "$1" "$2"; }
skip() { record "SKIP" "$1" "$2"; }

print_summary() {
  echo
  echo "=== Environment summary ==="
  for row in "${ROWS[@]+"${ROWS[@]}"}"; do
    IFS=$'\x1f' read -r status component detail <<< "$row"
    printf "  [%-4s] %-22s %s\n" "$status" "$component" "$detail"
  done
  echo
  if [ "$OVERALL_OK" -eq 1 ]; then
    echo "All checks passed."
    return 0
  fi
  echo "Some checks failed. Run: bash skills/setup/setup.sh fix"
  return 1
}

# --- compose detection -------------------------------------------------------
COMPOSE=""
detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  fi
}

# --- component checks --------------------------------------------------------
check_uv() {
  if command -v uv >/dev/null 2>&1; then
    pass "uv" "$(uv --version 2>/dev/null)"
  else
    fail "uv" "not installed — https://docs.astral.sh/uv/getting-started/installation/"
  fi
}

check_python() {
  if ! command -v uv >/dev/null 2>&1; then
    skip "Python ${PYTHON_MIN}+" "uv not installed"
    return 0
  fi
  local found
  if found="$(uv python find ">=${PYTHON_MIN}" 2>/dev/null)"; then
    pass "Python ${PYTHON_MIN}+" "$found"
  else
    fail "Python ${PYTHON_MIN}+" "no interpreter >=${PYTHON_MIN} (fix: uv python install ${PYTHON_MIN})"
  fi
}

check_deps() {  # args: label dir
  local label="$1" dir="$2"
  if ! command -v uv >/dev/null 2>&1; then
    skip "${label} deps" "uv not installed"
    return 0
  fi
  if (cd "$dir" && uv sync --dev --check >/dev/null 2>&1); then
    pass "${label} deps" "synced"
  else
    fail "${label} deps" "venv missing or out of sync"
  fi
}

check_node() {
  if ! command -v node >/dev/null 2>&1; then
    fail "Node ${NODE_MIN}+" "not installed — https://nodejs.org/"
    return 0
  fi
  local major
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
  if [ -n "$major" ] && [ "$major" -ge "$NODE_MIN" ] 2>/dev/null; then
    pass "Node ${NODE_MIN}+" "$(node --version)"
  else
    fail "Node ${NODE_MIN}+" "found $(node --version 2>/dev/null), need >=${NODE_MIN}"
  fi
}

check_npm() {
  if [ ! -f package.json ]; then
    skip "npm packages" "no package.json yet"
    return 0
  fi
  if [ -d node_modules ]; then
    pass "npm packages" "installed"
  else
    fail "npm packages" "node_modules missing"
  fi
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker daemon" "docker not installed — https://docs.docker.com/get-docker/"
    return 0
  fi
  if docker info >/dev/null 2>&1; then
    pass "Docker daemon" "running"
  else
    fail "Docker daemon" "not running — start Docker Desktop"
  fi
}

check_os_image() {
  if ! docker info >/dev/null 2>&1; then
    skip "OpenSearch image" "Docker not running"
    return 0
  fi
  if docker image inspect "$OS_IMAGE" >/dev/null 2>&1; then
    pass "OpenSearch image" "$OS_IMAGE present"
  else
    fail "OpenSearch image" "$OS_IMAGE not pulled"
  fi
}

check_os_container() {
  if ! docker info >/dev/null 2>&1; then
    skip "OpenSearch container" "Docker not running"
    return 0
  fi
  if curl -fs http://localhost:9200 >/dev/null 2>&1; then
    pass "OpenSearch container" "responding on :9200"
  else
    fail "OpenSearch container" "not responding on :9200"
  fi
}

check_env_files() {
  local missing=0 placeholder=0 f
  for f in agent/.env index/.env; do
    if [ ! -f "$f" ]; then
      missing=1
    elif grep -qE "sk-[a-z-]*\.\.\.|your-" "$f" 2>/dev/null; then
      placeholder=1
    fi
  done
  if [ "$missing" -eq 1 ]; then
    fail ".env files" "agent/.env or index/.env missing"
  elif [ "$placeholder" -eq 1 ]; then
    warn ".env files" "present but contain placeholder values — fill in API keys"
  else
    pass ".env files" "present"
  fi
}

# --- check mode --------------------------------------------------------------
mode_check() {
  detect_compose
  check_uv
  check_python
  check_deps "agent" "agent"
  check_deps "index" "index"
  check_node
  check_npm
  check_docker
  check_os_image
  check_os_container
  check_env_files
  print_summary
}

# --- fix functions -----------------------------------------------------------
fix_python() {
  command -v uv >/dev/null 2>&1 || { echo "skip: uv not installed"; return 0; }
  if uv python find ">=${PYTHON_MIN}" >/dev/null 2>&1; then
    echo "ok: Python ${PYTHON_MIN}+ already available"
    return 0
  fi
  echo "fixing: installing Python ${PYTHON_MIN}..."
  uv python install "$PYTHON_MIN"
}

fix_deps() {  # args: label dir
  local label="$1" dir="$2"
  command -v uv >/dev/null 2>&1 || { echo "skip: uv not installed"; return 0; }
  echo "fixing: syncing ${label} dependencies..."
  (cd "$dir" && uv sync --dev)
}

fix_env_files() {
  local f
  for f in agent index; do
    if [ ! -f "${f}/.env" ] && [ -f "${f}/.env.example" ]; then
      echo "fixing: creating ${f}/.env from .env.example..."
      cp "${f}/.env.example" "${f}/.env"
    fi
  done
}

fix_os_image() {
  detect_compose
  docker info >/dev/null 2>&1 || { echo "skip: Docker not running"; return 0; }
  [ -n "$COMPOSE" ] || { echo "skip: no docker compose command found"; return 0; }
  echo "fixing: pulling OpenSearch image..."
  $COMPOSE pull
}

fix_os_container() {
  detect_compose
  docker info >/dev/null 2>&1 || { echo "skip: Docker not running"; return 0; }
  [ -n "$COMPOSE" ] || { echo "skip: no docker compose command found"; return 0; }
  echo "fixing: starting OpenSearch container..."
  $COMPOSE up -d
  echo "waiting for OpenSearch on :9200..."
  local i
  for i in $(seq 1 30); do
    if curl -fs http://localhost:9200 >/dev/null 2>&1; then
      echo "ok: OpenSearch responding"
      return 0
    fi
    sleep 2
  done
  echo "warning: OpenSearch did not respond within 60s"
}

fix_npm() {
  [ -f package.json ] || { echo "skip: no package.json yet"; return 0; }
  command -v npm >/dev/null 2>&1 || { echo "skip: npm not installed"; return 0; }
  if [ -f package-lock.json ]; then
    echo "fixing: npm ci..."
    npm ci
  else
    echo "fixing: npm install..."
    npm install
  fi
}

# --- fix mode ----------------------------------------------------------------
mode_fix() {
  fix_python
  fix_deps "agent" "agent"
  fix_deps "index" "index"
  fix_env_files
  fix_os_image
  fix_os_container
  fix_npm
  echo
  echo "Fixes applied. Re-run: bash skills/setup/setup.sh check"
}

# --- entrypoint --------------------------------------------------------------
main() {
  case "${1:-}" in
    check) mode_check ;;
    fix)   mode_fix ;;
    *)
      echo "Usage: bash skills/setup/setup.sh {check|fix}"
      exit 2
      ;;
  esac
}
main "$@"
