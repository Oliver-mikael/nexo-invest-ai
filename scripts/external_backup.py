#!/usr/bin/env python3
"""Crea backups cifrados y los almacena localmente para probar el flujo externo."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.external_backup import (  # noqa: E402
    BackupError,
    configured_retention_days,
    configured_store,
    decrypt_backup,
    encrypt_backup,
    encryption_key,
    new_backup_id,
    operation_log_path,
    record_operation,
    sha256_file,
    verify_backup,
)

def publish(source: Path, *, log: bool = True) -> str:
    started = time.monotonic()
    backup_id = new_backup_id()
    digest = ""
    size_bytes = 0
    try:
        store = configured_store()
        verify_backup(source)
        key = encryption_key()
        with tempfile.TemporaryDirectory(prefix=".nexo-encrypt-", dir=store.root) as temporary:
            encrypted = Path(temporary) / backup_id
            digest = encrypt_backup(source, encrypted, key)
            size_bytes = encrypted.stat().st_size
            stored = store.put(encrypted, backup_id)
            if sha256_file(stored) != digest:
                raise BackupError("Stored backup SHA-256 verification failed")
        pruned = store.prune(configured_retention_days())
        if log:
            record_operation(
                operation_log_path(),
                action="backup",
                status="success",
                backup_id=backup_id,
                sha256=digest,
                size_bytes=size_bytes,
                pruned=pruned,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        return backup_id
    except (BackupError, OSError, ValueError) as error:
        if log:
            record_operation(
                operation_log_path(),
                action="backup",
                status="failed",
                backup_id=backup_id,
                sha256=digest or None,
                duration_ms=round((time.monotonic() - started) * 1000),
                error=type(error).__name__,
            )
        raise


def run_backup() -> str:
    backup_root = Path(os.environ.get("NEXO_BACKUP_DIR", "backups")).resolve()
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "backup_compose.sh")],
            cwd=REPO_ROOT,
            env={key: value for key, value in os.environ.items() if key != "NEXO_BACKUP_ENCRYPTION_KEY"},
            check=True,
            capture_output=True,
            text=True,
        )
        marker = "Backup verified: "
        backup_paths = [line.removeprefix(marker) for line in result.stdout.splitlines() if line.startswith(marker)]
        if len(backup_paths) != 1:
            raise BackupError("Local backup command did not return exactly one verified backup path")
        source = Path(backup_paths[0]).resolve()
        if source.parent != backup_root:
            raise BackupError("Local backup was created outside NEXO_BACKUP_DIR")
        backup_id = publish(source, log=False)
        stored = configured_store().get(backup_id)
        record_operation(
            operation_log_path(),
            action="backup",
            status="success",
            backup_id=backup_id,
            sha256=sha256_file(stored),
            size_bytes=stored.stat().st_size,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return backup_id
    except (BackupError, OSError, subprocess.SubprocessError) as error:
        record_operation(
            operation_log_path(),
            action="backup",
            status="failed",
            duration_ms=round((time.monotonic() - started) * 1000),
            error=type(error).__name__,
        )
        raise


def restore(backup_id: str) -> None:
    started = time.monotonic()
    try:
        store = configured_store()
        encrypted = store.get(backup_id)
        key = encryption_key()
        with tempfile.TemporaryDirectory(prefix="nexo-external-restore-") as temporary:
            staged = Path(temporary) / "backup"
            decrypt_backup(encrypted, staged, key)
            result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_compose.sh"), str(staged)],
                cwd=REPO_ROOT,
                env={key: value for key, value in os.environ.items() if key != "NEXO_BACKUP_ENCRYPTION_KEY"},
                check=True,
                capture_output=True,
                text=True,
            )
        record_operation(
            operation_log_path(),
            action="restore",
            status="success",
            backup_id=backup_id,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        print(result.stdout, end="")
    except (BackupError, OSError, subprocess.SubprocessError, ValueError) as error:
        record_operation(
            operation_log_path(),
            action="restore",
            status="failed",
            backup_id=backup_id,
            duration_ms=round((time.monotonic() - started) * 1000),
            error=type(error).__name__,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="crear un backup local, cifrarlo y guardarlo en el directorio autorizado")
    upload = commands.add_parser("publish", help="cifrar y guardar un backup local ya creado")
    upload.add_argument("source", type=Path)
    restore_parser = commands.add_parser("restore", help="descifrar y restaurar un backup almacenado")
    restore_parser.add_argument("backup_id")
    arguments = parser.parse_args()

    try:
        if arguments.command == "run":
            print(f"Backup cifrado verificado: {run_backup()}")
        elif arguments.command == "publish":
            print(f"Backup cifrado verificado: {publish(arguments.source.absolute())}")
        else:
            restore(arguments.backup_id)
    except (BackupError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"Backup operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
