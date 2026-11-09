#!/usr/bin/env bash
set -Eeuo pipefail

backup_root=${NEXO_BACKUP_DIR:-backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="$backup_root/$timestamp"

mkdir -p "$backup_root"
if [[ -e "$destination" ]]; then
  printf 'Backup destination already exists: %s\n' "$destination" >&2
  exit 1
fi

temporary_dir=$(mktemp -d "$backup_root/.nexo-backup.XXXXXX")
api_was_running=0

cleanup() {
  result=$?
  trap - EXIT
  if [[ "$api_was_running" == 1 ]]; then
    docker compose start api || result=1
  fi
  if [[ "$result" != 0 ]]; then
    rm -rf -- "$temporary_dir"
  fi
  exit "$result"
}
trap cleanup EXIT

if docker compose ps --status running --services | grep -Fxq api; then
  api_was_running=1
  docker compose stop api
fi

docker compose exec -T db sh -c \
  'exec pg_dump --format=custom --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$temporary_dir/postgres.dump"
docker compose exec -T db pg_restore --list \
  < "$temporary_dir/postgres.dump" > /dev/null

docker compose run --rm --no-deps -T --entrypoint tar api \
  -C /app/var/documents -czf - . > "$temporary_dir/documents.tar.gz"
tar -tzf "$temporary_dir/documents.tar.gz" > /dev/null

(cd "$temporary_dir" && sha256sum postgres.dump documents.tar.gz > SHA256SUMS)
(cd "$temporary_dir" && sha256sum -c SHA256SUMS)
mv "$temporary_dir" "$destination"
printf 'Backup verified: %s\n' "$destination"