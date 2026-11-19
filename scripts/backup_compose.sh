#!/usr/bin/env bash
set -Eeuo pipefail

backup_root=${NEXO_BACKUP_DIR:-backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p -- "$backup_root"
backup_root=$(cd -- "$backup_root" && pwd -P)
destination="$backup_root/$timestamp"
if [[ -e "$destination" ]]; then
  printf 'Backup destination already exists: %s\n' "$destination" >&2
  exit 1
fi

temporary_dir=$(mktemp -d -- "$backup_root/.nexo-backup.XXXXXX")
api_was_running=0

cleanup() {
  result=$?
  trap - EXIT
  if [[ "$api_was_running" == 1 ]]; then
    if ! docker compose start api; then
      printf 'Failed to restart the API service.\n' >&2
      result=1
    fi
  fi
  if [[ "$result" != 0 ]]; then
    rm -rf -- "$temporary_dir" || result=1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if docker compose ps --status running --services | grep -Fxq api; then
  api_was_running=1
  docker compose stop api
fi

docker compose exec -T db sh -c \
  'exec pg_dump --format=custom --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$temporary_dir/postgres.dump"
docker compose exec -T db pg_restore --list \
  < "$temporary_dir/postgres.dump" > /dev/null

docker compose exec -T db sh -c \
  'printf "%s\n%s\n" "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$temporary_dir/.database-identity"
mapfile -t database_identity < "$temporary_dir/.database-identity"
rm -- "$temporary_dir/.database-identity"
if [[ ${#database_identity[@]} -ne 2 ]] \
  || [[ ! ${database_identity[0]} =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] \
  || [[ ! ${database_identity[1]} =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  printf 'Database user or name contains unsupported characters.\n' >&2
  exit 1
fi
printf 'NEXO_BACKUP_FORMAT=1\nDB_USER=%s\nDB_NAME=%s\n' \
  "${database_identity[0]}" "${database_identity[1]}" \
  > "$temporary_dir/metadata.env"

docker compose run --rm --no-deps -T --entrypoint tar api \
  -C /app/var/documents -czf - . > "$temporary_dir/documents.tar.gz"
tar -tzf "$temporary_dir/documents.tar.gz" > /dev/null

(cd "$temporary_dir" && sha256sum metadata.env postgres.dump documents.tar.gz > SHA256SUMS)
(cd "$temporary_dir" && sha256sum -c SHA256SUMS)
mv --no-clobber --no-target-directory -- "$temporary_dir" "$destination"
if [[ -e "$temporary_dir" ]]; then
  printf 'Backup destination was created concurrently: %s\n' "$destination" >&2
  exit 1
fi
printf 'Backup verified: %s\n' "$destination"