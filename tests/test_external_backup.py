from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from app.services.external_backup import (
    BACKUP_FILES,
    BackupError,
    LocalDirectoryStore,
    decrypt_backup,
    encrypt_backup,
    encryption_key,
    record_operation,
)
from scripts.monitor import api_check, critical_log_check, disk_check, docker_check, operation_check


def _backup_directory(path: Path) -> Path:
    path.mkdir()
    for name in BACKUP_FILES[:-1]:
        (path / name).write_bytes(f"disposable:{name}".encode())
    manifest = "".join(
        f"{hashlib.sha256((path / name).read_bytes()).hexdigest()}  {name}\n"
        for name in BACKUP_FILES[:-1]
    )
    (path / "SHA256SUMS").write_text(manifest, encoding="ascii")
    return path


def test_encrypted_backup_round_trip_verifies_hashes_and_authentication(tmp_path: Path) -> None:
    source = _backup_directory(tmp_path / "source")
    key = encryption_key(base64.b64encode(os.urandom(32)).decode())
    encrypted = tmp_path / "backup.nexo.enc"
    digest = encrypt_backup(source, encrypted, key)
    restored = tmp_path / "restored"

    decrypt_backup(encrypted, restored, key)

    assert hashlib.sha256(encrypted.read_bytes()).hexdigest() == digest
    assert {name: (source / name).read_bytes() for name in BACKUP_FILES} == {
        name: (restored / name).read_bytes() for name in BACKUP_FILES
    }

    damaged = tmp_path / "damaged.nexo.enc"
    ciphertext = bytearray(encrypted.read_bytes())
    ciphertext[-20] ^= 1
    damaged.write_bytes(ciphertext)
    failed_restore = tmp_path / "failed-restore"
    with pytest.raises(BackupError, match="authentication failed"):
        decrypt_backup(damaged, failed_restore, key)
    assert not failed_restore.exists()


def test_publish_storage_retention_and_backup_failure_monitoring(tmp_path: Path) -> None:
    store = LocalDirectoryStore(tmp_path / "external")
    local_file = tmp_path / "encrypted.nexo.enc"
    local_file.write_bytes(b"encrypted disposable backup")
    backup_id = "backup-20260101T000000Z-0123456789ab.nexo.enc"
    stored = store.put(local_file, backup_id)
    assert store.get(backup_id).read_bytes() == local_file.read_bytes()

    old = tmp_path / "external" / "backup-20250101T000000Z-0123456789ab.nexo.enc"
    old.write_bytes(b"old")
    os.utime(old, (0, 0))
    assert store.prune(30, now=2_000_000_000) == 2
    assert not stored.exists()

    log_path = tmp_path / "operations.jsonl"
    now = datetime.now(timezone.utc)
    record_operation(log_path, action="backup", status="success", timestamp=now.isoformat())
    record_operation(log_path, action="backup", status="failed", timestamp=now.isoformat())
    record_operation(log_path, action="restore", status="failed", timestamp=now.isoformat())
    assert operation_check(log_path, "backup", now)["status"] == "error"
    assert operation_check(log_path, "restore", now)["status"] == "error"


def test_monitoring_detects_expired_backup_and_low_storage(tmp_path: Path) -> None:
    log_path = tmp_path / "operations.jsonl"
    now = datetime.now(timezone.utc)
    record_operation(
        log_path,
        action="backup",
        status="success",
        timestamp=(now - timedelta(hours=25)).isoformat(),
    )

    assert operation_check(log_path, "backup", now, timedelta(hours=24))["status"] == "error"
    assert disk_check(tmp_path, 10**30)["status"] == "error"


def test_monitoring_reports_api_database_and_critical_log_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class HealthResponse:
        def __enter__(self) -> HealthResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ok","database":"ok"}'

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise URLError("unavailable")

    monkeypatch.setattr("scripts.monitor.urllib.request.urlopen", unavailable)
    assert api_check("http://127.0.0.1:8000/api/v1/health")["status"] == "error"
    monkeypatch.setattr(
        "scripts.monitor.urllib.request.urlopen",
        lambda *_args, **_kwargs: HealthResponse(),
    )
    assert api_check("http://127.0.0.1:8000/api/v1/health")["status"] == "ok"

    stopped_database = docker_check(
        ["docker", "compose", "exec", "db", "pg_isready"],
        "PostgreSQL unavailable",
        run=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert stopped_database["status"] == "error"
    recovered_database = docker_check(
        ["docker", "compose", "exec", "db", "pg_isready"],
        "PostgreSQL unavailable",
        run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert recovered_database["status"] == "ok"

    critical = critical_log_check(
        run=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="FATAL password=must-not-be-recorded",
            stderr="",
        )
    )
    assert critical == {
        "status": "error",
        "detail": "critical error markers found in the last five minutes",
    }
    assert critical_log_check(
        run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="healthy", stderr="")
    )["status"] == "ok"
