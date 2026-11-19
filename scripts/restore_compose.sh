#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'Usage: %s BACKUP_DIRECTORY\n' "${0##*/}" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

backup_input=$1
if [[ -L "$backup_input" ]]; then
  printf 'Backup directory must not be a symbolic link.\n' >&2
  exit 1
fi
backup_dir=$(cd -- "$backup_input" 2>/dev/null && pwd -P) || {
  printf 'Backup directory does not exist.\n' >&2
  exit 1
}

for name in SHA256SUMS metadata.env postgres.dump documents.tar.gz; do
  if [[ ! -f "$backup_dir/$name" || -L "$backup_dir/$name" ]]; then
    printf 'Backup is incomplete or contains an unsafe file: %s\n' "$name" >&2
    exit 1
  fi
done

mapfile -t manifest_files < <(awk 'NF == 2 { print $2 }' "$backup_dir/SHA256SUMS")
expected_files=(metadata.env postgres.dump documents.tar.gz)
if [[ ${#manifest_files[@]} -ne ${#expected_files[@]} ]]; then
  printf 'Backup manifest has an unexpected number of entries.\n' >&2
  exit 1
fi
for name in "${expected_files[@]}"; do
  if ! printf '%s\n' "${manifest_files[@]}" | grep -Fxq -- "$name"; then
    printf 'Backup manifest is missing: %s\n' "$name" >&2
    exit 1
  fi
done
if ! (cd -- "$backup_dir" && sha256sum --check --strict --status SHA256SUMS); then
  printf 'Backup checksum verification failed.\n' >&2
  exit 1
fi

mapfile -t metadata < "$backup_dir/metadata.env"
if [[ ${#metadata[@]} -ne 3 ]] \
  || [[ ${metadata[0]} != NEXO_BACKUP_FORMAT=1 ]] \
  || [[ ${metadata[1]} != DB_USER=* ]] \
  || [[ ${metadata[2]} != DB_NAME=* ]]; then
  printf 'Backup metadata is invalid or unsupported.\n' >&2
  exit 1
fi
database_user=${metadata[1]#DB_USER=}
database_name=${metadata[2]#DB_NAME=}
if [[ ! "$database_user" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] \
  || [[ ! "$database_name" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  printf 'Backup database identity contains unsupported characters.\n' >&2
  exit 1
fi

document_count=$(python3 - "$backup_dir/documents.tar.gz" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

seen = set()
regular_files = 0
try:
    with tarfile.open(sys.argv[1], "r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            parts = tuple(part for part in path.parts if part not in {"", "."})
            if path.is_absolute() or ".." in parts or "\\" in member.name:
                raise ValueError("unsafe archive path")
            if parts in seen:
                raise ValueError("duplicate archive path")
            seen.add(parts)
            if not (member.isdir() or member.isfile()):
                raise ValueError("links and special files are not allowed")
            if member.isfile():
                regular_files += 1
except (OSError, tarfile.TarError, ValueError) as error:
    print(f"Invalid documents archive: {error}", file=sys.stderr)
    raise SystemExit(1)
print(regular_files)
PY
) || exit 1

restore_root=${NEXO_RESTORE_DIR:-var/restores}
mkdir -p -- "$restore_root"
restore_root=$(cd -- "$restore_root" && pwd -P)
project_name="nexo-restore-$(date -u +%Y%m%d%H%M%S)-${RANDOM}${RANDOM}"
restore_dir="$restore_root/$project_name"
umask 077
mkdir -- "$restore_dir"
compose_file="$restore_dir/compose.yml"
env_file="$restore_dir/.env"
completed=0

compose() {
  docker compose --project-name "$project_name" \
    --file "$compose_file" --env-file "$env_file" "$@"
}

cleanup() {
  result=$?
  trap - EXIT
  if [[ "$completed" != 1 ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$restore_dir"
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

restore_password=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
printf 'RESTORE_PROJECT=%s\nRESTORE_DB_USER=%s\nRESTORE_DB_NAME=%s\nRESTORE_DB_PASSWORD=%s\n' \
  "$project_name" "$database_user" "$database_name" "$restore_password" \
  > "$env_file"
unset restore_password
cat > "$compose_file" <<'YAML'
services:
  db:
    image: postgres:16-alpine
    restart: "no"
    environment:
      POSTGRES_USER: ${RESTORE_DB_USER:?}
      POSTGRES_PASSWORD: ${RESTORE_DB_PASSWORD:?}
      POSTGRES_DB: ${RESTORE_DB_NAME:?}
    volumes:
      - database:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$$POSTGRES_USER\" -d \"$$POSTGRES_DB\""]
      interval: 2s
      timeout: 3s
      retries: 30
  documents:
    image: postgres:16-alpine
    restart: "no"
    command: ["sh", "-c", "while true; do sleep 3600; done"]
    volumes:
      - documents:/restore
volumes:
  database:
    name: ${RESTORE_PROJECT:?}_database
  documents:
    name: ${RESTORE_PROJECT:?}_documents
YAML

compose up -d --wait --wait-timeout 90 db documents
compose exec -T db pg_restore --list < "$backup_dir/postgres.dump" > /dev/null
compose exec -T db pg_restore --exit-on-error --no-owner --no-acl \
  --username="$database_user" --dbname="$database_name" \
  < "$backup_dir/postgres.dump"
compose exec -T documents tar -xz -f - -C /restore \
  < "$backup_dir/documents.tar.gz"

schema_version=$(compose exec -T db psql -v ON_ERROR_STOP=1 \
  --username="$database_user" --dbname="$database_name" \
  --tuples-only --no-align \
  --command='SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1' \
  | tr -d '\r')
if [[ -z "$schema_version" ]]; then
  printf 'Restored database has no Alembic schema version.\n' >&2
  exit 1
fi
restored_document_count=$(compose exec -T documents sh -c 'find /restore -type f | wc -l' | tr -d '[:space:]')
if [[ "$restored_document_count" != "$document_count" ]]; then
  printf 'Document count mismatch: expected %s, restored %s.\n' \
    "$document_count" "$restored_document_count" >&2
  exit 1
fi
document_records="$restore_dir/document-records.txt"
compose exec -T db psql -v ON_ERROR_STOP=1 \
  --username="$database_user" --dbname="$database_name" \
  --tuples-only --no-align --field-separator='|' \
  --command="SELECT encode(convert_to(storage_key, 'UTF8'), 'base64') || '|' || sha256 || '|' || size_bytes::text FROM documents ORDER BY id" \
  > "$document_records"
verified_document_count=0
while IFS='|' read -r encoded_key expected_hash expected_size; do
  [[ -n "$encoded_key" ]] || continue
  storage_key=$(printf '%s' "$encoded_key" | base64 --decode) || {
    printf 'A restored document has an invalid storage key.\n' >&2
    exit 1
  }
  if [[ ! "$storage_key" =~ ^[0-9]+/[0-9a-f]{32}\.(jpg|png|webp|pdf)$ ]] \
    || [[ ! "$expected_hash" =~ ^[[:xdigit:]]{64}$ ]] \
    || [[ ! "$expected_size" =~ ^[0-9]+$ ]]; then
    printf 'A restored document record has invalid integrity metadata.\n' >&2
    exit 1
  fi
  file_info=$(compose exec -T documents sh -c '
    set -eu
    path="/restore/$1"
    test -f "$path"
    test ! -L "$path"
    sha256sum "$path" | cut -d " " -f 1
    wc -c < "$path"
  ' sh "$storage_key") || {
    printf 'Restored document file is missing or unsafe: %s\n' "$storage_key" >&2
    exit 1
  }
  actual_hash=$(printf '%s\n' "$file_info" | sed -n '1p')
  actual_size=$(printf '%s\n' "$file_info" | sed -n '2p' | tr -d '[:space:]')
  if [[ "$actual_hash" != "${expected_hash,,}" || "$actual_size" != "$expected_size" ]]; then
    printf 'Restored document integrity mismatch: %s\n' "$storage_key" >&2
    exit 1
  fi
  verified_document_count=$((verified_document_count + 1))
done < "$document_records"
rm -- "$document_records"
if [[ "$verified_document_count" != "$document_count" ]]; then
  printf 'Document database/archive mismatch: expected %s records, found %s.\n' \
    "$document_count" "$verified_document_count" >&2
  exit 1
fi
table_count=$(compose exec -T db psql -v ON_ERROR_STOP=1 \
  --username="$database_user" --dbname="$database_name" \
  --tuples-only --no-align \
  --command="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'" \
  | tr -d '\r')
if [[ ! "$table_count" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Restored database contains no usable tables.\n' >&2
  exit 1
fi

cat > "$restore_dir/RESTORE_RESULT.txt" <<EOF
result=PASS
completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
backup=$(basename -- "$backup_dir")
database_schema_version=$schema_version
database_table_count=$table_count
document_file_count=$restored_document_count
document_record_count=$verified_document_count
project=$project_name
EOF
completed=1
printf 'Recovery verified in isolated project: %s\n' "$project_name"
printf 'Recovery record: %s\n' "$restore_dir/RESTORE_RESULT.txt"
printf 'Inspect: docker compose --project-name %s --file %s --env-file %s exec db psql -U %s -d %s\n' \
  "$project_name" "$compose_file" "$env_file" "$database_user" "$database_name"
printf 'Delete isolated restore: docker compose --project-name %s --file %s --env-file %s down --volumes\n' \
  "$project_name" "$compose_file" "$env_file"