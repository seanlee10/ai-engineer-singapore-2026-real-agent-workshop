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

# --- check mode --------------------------------------------------------------
mode_check() {
  detect_compose
  check_uv
  check_python
  check_deps "agent" "agent"
  check_deps "index" "index"
  print_summary
}

# --- fix mode ----------------------------------------------------------------
mode_fix() {
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
