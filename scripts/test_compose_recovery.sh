#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
test_root=$(mktemp -d)
project_name="nexo-recovery-test-$(date -u +%Y%m%d%H%M%S)-${RANDOM}${RANDOM}"
export COMPOSE_PROJECT_NAME=$project_name
export COMPOSE_FILE="$repo_root/tests/ops/compose-recovery.yml"
export POSTGRES_USER=recovery_user
export POSTGRES_DB=recovery_db
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
export NEXO_BACKUP_DIR="$test_root/backups"
export NEXO_RESTORE_DIR="$test_root/restores"
export NEXO_EXTERNAL_BACKUP_DIR="$test_root/external"
export NEXO_BACKUP_LOG="$test_root/backups/operations.jsonl"
export NEXO_BACKUP_ENCRYPTION_KEY
NEXO_BACKUP_ENCRYPTION_KEY=$(python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')

cleanup() {
  local result=$?
  trap - EXIT
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ -d "$NEXO_RESTORE_DIR" ]]; then
    for restore_dir in "$NEXO_RESTORE_DIR"/nexo-restore-*; do
      [[ -d "$restore_dir" ]] || continue
      restore_project=${restore_dir##*/}
      docker compose --project-name "$restore_project" \
        --file "$restore_dir/compose.yml" --env-file "$restore_dir/.env" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    done
  fi
  rm -rf -- "$test_root"
  exit "$result"
}
trap cleanup EXIT

restore_count() {
  find "$NEXO_RESTORE_DIR" -mindepth 1 -maxdepth 1 -type d -name 'nexo-restore-*' \
    | wc -l
}

docker compose up -d --wait --wait-timeout 90
database_port=$(docker compose port db 5432 | sed 's/.*://')
export NEXO_DATABASE_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:$database_port/$POSTGRES_DB"
NEXO_AUTO_CREATE_SCHEMA=0 python3 -m alembic upgrade head
python3 - <<'PY'
from app.db import configure, session_scope
from app.config import load_settings
from app.models import Document, User
from app.security import hash_password

configure(load_settings())
with session_scope() as session:
  user = User(
    email="restore@nexo.invalid",
    password_hash=hash_password("restore-test-password"),
    display_name="Recovery test",
  )
  session.add(user)
  session.flush()
  session.add(
    Document(
      user_id=user.id,
      filename="receipt.txt",
      content_type="text/plain",
      size_bytes=len(b"document restored"),
      sha256="70be0b6d5bb195b41a832b9d9440986a9f40d4d5f6b6d6f73ba2fa43051d28fb",
      storage_key="7/0123456789abcdef0123456789abcdef.pdf",
      status="uploaded",
    )
  )
PY
docker compose exec -T api sh -c \
  'mkdir -p /app/var/documents/7 && printf "%s" "document restored" > /app/var/documents/7/0123456789abcdef0123456789abcdef.pdf'
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'CREATE TABLE recovery_probe (value text NOT NULL)' \
  -c "INSERT INTO recovery_probe VALUES ('present_at_backup')"

backup_output=$(bash "$repo_root/scripts/backup_compose.sh")
backup_dir=${backup_output##*Backup verified: }
[[ -s "$backup_dir/postgres.dump" && -s "$backup_dir/documents.tar.gz" ]]
backup_completed_ns=$(date +%s%N)
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "INSERT INTO recovery_probe VALUES ('created_after_backup')"
simulated_failure_ns=$(date +%s%N)
encrypted_output=$(python3 "$repo_root/scripts/external_backup.py" publish "$backup_dir")
backup_id=${encrypted_output##*Backup cifrado verificado: }
encrypted_backup="$NEXO_EXTERNAL_BACKUP_DIR/$backup_id"
[[ -s "$encrypted_backup" ]]
! grep -aFq 'document restored' "$encrypted_backup"

restore_started_ns=$(date +%s%N)
restore_output=$(python3 "$repo_root/scripts/external_backup.py" restore "$backup_id")
restore_project=$(sed -n 's/^Recovery verified in isolated project: //p' <<< "$restore_output")
restore_dir="$NEXO_RESTORE_DIR/$restore_project"
[[ -n "$restore_project" && -f "$restore_dir/RESTORE_RESULT.txt" ]]
restored_value=$(docker compose --project-name "$restore_project" \
  --file "$restore_dir/compose.yml" --env-file "$restore_dir/.env" \
  exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Atc "SELECT display_name FROM users WHERE email = 'restore@nexo.invalid'")
restored_document=$(docker compose --project-name "$restore_project" \
  --file "$restore_dir/compose.yml" --env-file "$restore_dir/.env" \
  exec -T documents cat /restore/7/0123456789abcdef0123456789abcdef.pdf)
restored_document_record=$(docker compose --project-name "$restore_project" \
  --file "$restore_dir/compose.yml" --env-file "$restore_dir/.env" \
  exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Atc "SELECT storage_key FROM documents WHERE filename = 'receipt.txt'")
restored_probe=$(docker compose --project-name "$restore_project" \
  --file "$restore_dir/compose.yml" --env-file "$restore_dir/.env" \
  exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Atc "SELECT string_agg(value, ',' ORDER BY value) FROM recovery_probe")
[[ "$restored_value" == 'Recovery test' ]]
[[ "$restored_document" == 'document restored' ]]
[[ "$restored_document_record" == '7/0123456789abcdef0123456789abcdef.pdf' ]]
[[ "$restored_probe" == 'present_at_backup' ]]
restore_finished_ns=$(date +%s%N)
recovery_rpo_seconds=$(python3 - "$backup_completed_ns" "$simulated_failure_ns" <<'PY'
import sys
print(f"{(int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000:.3f}")
PY
)
recovery_rto_seconds=$(python3 - "$restore_started_ns" "$restore_finished_ns" <<'PY'
import sys
print(f"{(int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000:.3f}")
PY
)
recovery_log=$(python3 - "$NEXO_BACKUP_LOG" "$backup_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as log_file:
    events = [json.loads(line) for line in log_file]
matches = [event for event in events if event.get("action") == "restore" and event.get("backup_id") == sys.argv[2]]
assert matches and matches[-1]["status"] == "success", "successful restore not recorded"
print(matches[-1]["duration_ms"])
PY
)
[[ "$recovery_log" =~ ^[0-9]+$ ]]

collision_dir="$NEXO_BACKUP_DIR/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -- "$collision_dir"
printf 'keep this backup' > "$collision_dir/sentinel"
if bash "$repo_root/scripts/backup_compose.sh"; then
  printf 'Backup overwrote an existing destination.\n' >&2
  exit 1
fi
[[ $(<"$collision_dir/sentinel") == 'keep this backup' ]]
docker compose ps --status running --services | grep -Fxq api

corrupt_dir="$test_root/corrupt"
cp -a -- "$backup_dir" "$corrupt_dir"
printf 'corrupt' >> "$corrupt_dir/documents.tar.gz"
if bash "$repo_root/scripts/restore_compose.sh" "$corrupt_dir"; then
  printf 'Corrupt backup was accepted.\n' >&2
  exit 1
fi

incomplete_dir="$test_root/incomplete"
mkdir -- "$incomplete_dir"
cp -- "$backup_dir/SHA256SUMS" "$backup_dir/metadata.env" "$backup_dir/postgres.dump" "$incomplete_dir/"
if bash "$repo_root/scripts/restore_compose.sh" "$incomplete_dir"; then
  printf 'Incomplete backup was accepted.\n' >&2
  exit 1
fi

unsafe_dir="$test_root/unsafe-path"
cp -a -- "$backup_dir" "$unsafe_dir"
python3 - "$unsafe_dir/documents.tar.gz" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w:gz") as archive:
    member = tarfile.TarInfo("../escape.txt")
    member.size = 4
    archive.addfile(member, io.BytesIO(b"evil"))
PY
(cd "$unsafe_dir" && sha256sum metadata.env postgres.dump documents.tar.gz > SHA256SUMS)
restores_before=$(restore_count)
if bash "$repo_root/scripts/restore_compose.sh" "$unsafe_dir"; then
  printf 'Archive path traversal was accepted.\n' >&2
  exit 1
fi
[[ $(restore_count) == "$restores_before" && ! -e "$test_root/escape.txt" ]]

link_dir="$test_root/unsafe-link"
cp -a -- "$backup_dir" "$link_dir"
python3 - "$link_dir/documents.tar.gz" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "w:gz") as archive:
    member = tarfile.TarInfo("escape-link")
    member.type = tarfile.SYMTYPE
    member.linkname = "../../etc/passwd"
    archive.addfile(member)
PY
(cd "$link_dir" && sha256sum metadata.env postgres.dump documents.tar.gz > SHA256SUMS)
restores_before=$(restore_count)
if bash "$repo_root/scripts/restore_compose.sh" "$link_dir"; then
  printf 'Archive symlink was accepted.\n' >&2
  exit 1
fi
[[ $(restore_count) == "$restores_before" ]]

failed_restore_dir="$test_root/failed-restore"
cp -a -- "$backup_dir" "$failed_restore_dir"
printf 'not a postgres archive' > "$failed_restore_dir/postgres.dump"
(cd "$failed_restore_dir" && sha256sum metadata.env postgres.dump documents.tar.gz > SHA256SUMS)
restores_before=$(restore_count)
if bash "$repo_root/scripts/restore_compose.sh" "$failed_restore_dir"; then
  printf 'Invalid database archive was accepted.\n' >&2
  exit 1
fi
[[ $(restore_count) == "$restores_before" ]]

corrupt_encrypted_id="backup-20260101T000000Z-abcdef012345.nexo.enc"
cp -- "$encrypted_backup" "$NEXO_EXTERNAL_BACKUP_DIR/$corrupt_encrypted_id"
printf '\001' | dd of="$NEXO_EXTERNAL_BACKUP_DIR/$corrupt_encrypted_id" bs=1 seek=30 conv=notrunc status=none
restores_before=$(restore_count)
if python3 "$repo_root/scripts/external_backup.py" restore "$corrupt_encrypted_id" >/dev/null 2>&1; then
  printf 'Tampered encrypted backup was accepted.\n' >&2
  exit 1
fi
[[ $(restore_count) == "$restores_before" ]]
python3 - "$NEXO_BACKUP_LOG" "$corrupt_encrypted_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as log_file:
    events = [json.loads(line) for line in log_file]
matches = [
    event for event in events
    if event.get("action") == "restore" and event.get("backup_id") == sys.argv[2]
]
assert matches and matches[-1]["status"] == "failed", "failed restore was not recorded"
PY

docker compose stop db
if NEXO_BACKUP_DIR="$test_root/failed-backup" bash "$repo_root/scripts/backup_compose.sh"; then
  printf 'Backup unexpectedly succeeded with PostgreSQL stopped.\n' >&2
  exit 1
fi
docker compose ps --status running --services | grep -Fxq api
if find "$test_root/failed-backup" -mindepth 1 -maxdepth 1 -name '.nexo-backup.*' -print -quit | grep -q .; then
  printf 'Failed backup left a temporary artifact.\n' >&2
  exit 1
fi

printf 'Recovery integration checks passed (encrypted local storage, PostgreSQL, documents, consistency, controlled loss=1 post-backup record, RPO=%ss, RTO=%ss, restore flow=%sms, collision, corruption, incomplete backup, unsafe archive, cleanup, API restart).\n' \
  "$recovery_rpo_seconds" "$recovery_rto_seconds" "$recovery_log"