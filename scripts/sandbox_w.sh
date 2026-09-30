#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/backend"

export DATABASE_URL="${DATABASE_URL:-sqlite:///./app.sandbox.db}"
export DEMO_USER_ID="${DEMO_USER_ID:-overhaul-test}"
export MEMORY_READ_ONLY="${MEMORY_READ_ONLY:-false}"

resolved="$(uv run python -c 'from app.config import settings; from app.memory.memory_service import BANK_ID; print(f"DATABASE_URL={settings.database_url}\nBANK_ID={BANK_ID}\nMEMORY_READ_ONLY={str(settings.memory_read_only).lower()}")')"
printf '%s\n' "$resolved"
if ! grep -Fxq 'DATABASE_URL=sqlite:///./app.sandbox.db' <<<"$resolved" \
  || ! grep -Fxq 'BANK_ID=ae-overhaul-test' <<<"$resolved" \
  || ! grep -Fxq 'MEMORY_READ_ONLY=false' <<<"$resolved"; then
  printf '%s\n' 'Refusing Sandbox-W: resolved settings do not match the write-sandbox guard.' >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  exit 0
elif [[ $# -ne 0 ]]; then
  printf 'Usage: %s [--check]\n' "$0" >&2
  exit 2
fi

exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
