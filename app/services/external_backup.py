"""Cifrado autenticado y almacenamiento desacoplado de backups."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import AEADEncryptionContext

BACKUP_FILES = ("metadata.env", "postgres.dump", "documents.tar.gz", "SHA256SUMS")
MANIFEST_FILES = BACKUP_FILES[:-1]
MAGIC = b"NEXO-ENC-1\n"
BACKUP_ID = re.compile(r"backup-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.nexo\.enc\Z")


class BackupError(RuntimeError):
    """Un backup está incompleto, dañado o tiene una configuración inválida."""


def encryption_key(value: str | None = None) -> bytes:
    encoded = value if value is not None else os.environ.get("NEXO_BACKUP_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise BackupError("NEXO_BACKUP_ENCRYPTION_KEY must be base64-encoded 32-byte key") from error
    if len(key) != 32:
        raise BackupError("NEXO_BACKUP_ENCRYPTION_KEY must be base64-encoded 32-byte key")
    return key


def verify_backup(directory: Path) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise BackupError("Backup source must be a regular directory")
    manifest_path = directory / "SHA256SUMS"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupError("Backup checksum manifest is missing or unsafe")
    entries: dict[str, str] = {}
    try:
        lines = manifest_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise BackupError("Backup checksum manifest is unreadable") from error
    for line in lines:
        match = re.fullmatch(r"([0-9a-fA-F]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None or match[2] in entries:
            raise BackupError("Backup checksum manifest is invalid")
        entries[match[2]] = match[1].lower()
    if set(entries) != set(MANIFEST_FILES):
        raise BackupError("Backup checksum manifest has unexpected files")
    for name in BACKUP_FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise BackupError(f"Backup file is missing or unsafe: {name}")
        if name in entries and sha256_file(path) != entries[name]:
            raise BackupError(f"Backup checksum mismatch: {name}")


class _EncryptingWriter:
    def __init__(self, output: BinaryIO, encryptor: AEADEncryptionContext) -> None:
        self.output = output
        self.encryptor = encryptor

    def write(self, data: bytes) -> int:
        self.output.write(self.encryptor.update(data))
        return len(data)


def encrypt_backup(source: Path, destination: Path, key: bytes) -> str:
    verify_backup(source)
    if len(key) != 32:
        raise BackupError("Encryption key must contain 32 bytes")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise BackupError("Encrypted backup destination already exists")

    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(MAGIC)
            output.write(nonce)
            writer = _EncryptingWriter(output, encryptor)
            with tarfile.open(fileobj=writer, mode="w|gz") as archive:
                for name in BACKUP_FILES:
                    archive.add(source / name, arcname=name, recursive=False)
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decrypt_backup(encrypted: Path, destination: Path, key: bytes) -> None:
    if encrypted.is_symlink() or not encrypted.is_file():
        raise BackupError("Encrypted backup is missing or unsafe")
    if len(key) != 32:
        raise BackupError("Encryption key must contain 32 bytes")
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    completed = False
    try:
        with encrypted.open("rb") as source, tempfile.TemporaryFile(mode="w+b") as plaintext:
            header = source.read(len(MAGIC) + 12)
            if len(header) != len(MAGIC) + 12 or not header.startswith(MAGIC):
                raise BackupError("Encrypted backup header is invalid")
            source.seek(0, os.SEEK_END)
            payload_length = source.tell() - len(header) - 16
            if payload_length < 0:
                raise BackupError("Encrypted backup is truncated")
            source.seek(len(header))
            source.seek(payload_length, os.SEEK_CUR)
            tag = source.read(16)
            source.seek(len(header))
            decryptor = Cipher(
                algorithms.AES(key),
                modes.GCM(header[len(MAGIC) :], tag),
            ).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            remaining = payload_length
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise BackupError("Encrypted backup is truncated")
                plaintext.write(decryptor.update(chunk))
                remaining -= len(chunk)
            try:
                plaintext.write(decryptor.finalize())
            except InvalidTag as error:
                raise BackupError("Encrypted backup authentication failed") from error
            plaintext.seek(0)
            _extract_backup(plaintext, destination)
        verify_backup(destination)
        completed = True
    finally:
        if not completed:
            shutil.rmtree(destination, ignore_errors=True)


def _extract_backup(archive_file: BinaryIO, destination: Path) -> None:
    extracted: set[str] = set()
    try:
        with tarfile.open(fileobj=archive_file, mode="r|gz") as archive:
            for member in archive:
                if member.name not in BACKUP_FILES or member.name in extracted or not member.isfile():
                    raise BackupError("Encrypted backup archive contains an unexpected entry")
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError("Encrypted backup archive contains an unreadable file")
                target = destination / member.name
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output, source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                extracted.add(member.name)
    except (OSError, tarfile.TarError) as error:
        raise BackupError("Encrypted backup archive is invalid") from error
    if extracted != set(BACKUP_FILES):
        raise BackupError("Encrypted backup archive is incomplete")


class LocalDirectoryStore:
    """Implementación local de la interfaz de almacenamiento de backups."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise BackupError("Backup storage directory must not be a symbolic link")
        self.root = root.resolve()

    def put(self, source: Path, backup_id: str) -> Path:
        if BACKUP_ID.fullmatch(backup_id) is None:
            raise BackupError("Backup identifier is invalid")
        target = self.root / backup_id
        temporary = self.root / f".{backup_id}.{uuid.uuid4().hex}.tmp"
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                os.chmod(temporary, 0o600)
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def get(self, backup_id: str) -> Path:
        if BACKUP_ID.fullmatch(backup_id) is None:
            raise BackupError("Backup identifier is invalid")
        path = self.root / backup_id
        if path.is_symlink() or not path.is_file():
            raise BackupError("Encrypted backup was not found in storage")
        return path

    def prune(self, retention_days: int, now: float | None = None) -> int:
        if retention_days < 1:
            raise BackupError("Backup retention must be at least one day")
        cutoff = (time.time() if now is None else now) - timedelta(days=retention_days).total_seconds()
        removed = 0
        for path in self.root.iterdir():
            if BACKUP_ID.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
        return removed


def operation_log_path() -> Path:
    configured = os.environ.get("NEXO_BACKUP_LOG")
    if configured:
        return Path(configured)
    return Path(os.environ.get("NEXO_BACKUP_DIR", "backups")) / "operations.jsonl"


def record_operation(log_path: Path, **fields: object) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **fields}
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "ab") as log_file:
        log_file.write(encoded)
        log_file.flush()
        os.fsync(log_file.fileno())


def new_backup_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"backup-{stamp}-{uuid.uuid4().hex[:12]}.nexo.enc"


def configured_store() -> LocalDirectoryStore:
    root = os.environ.get("NEXO_EXTERNAL_BACKUP_DIR")
    if not root:
        raise BackupError("NEXO_EXTERNAL_BACKUP_DIR must point to an authorized storage location")
    return LocalDirectoryStore(Path(root))


def configured_retention_days() -> int:
    try:
        value = int(os.environ.get("NEXO_BACKUP_RETENTION_DAYS", "30"))
    except ValueError as error:
        raise BackupError("NEXO_BACKUP_RETENTION_DAYS must be a positive integer") from error
    if value < 1:
        raise BackupError("NEXO_BACKUP_RETENTION_DAYS must be a positive integer")
    return value
