#!/usr/bin/env python3
"""Comprobaciones operativas locales que no publican datos ni credenciales."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.external_backup import operation_log_path  # noqa: E402


def api_check(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read())
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return {"status": "error", "detail": "API unavailable or returned invalid health data"}
    if not isinstance(data, dict):
        return {"status": "error", "detail": "API unavailable or returned invalid health data"}
    if data.get("status") != "ok" or data.get("database") != "ok":
        return {"status": "error", "detail": "API or database health endpoint reports degraded"}
    return {"status": "ok", "detail": "API and health endpoint database check passed"}


def docker_check(command: list[str], failure_detail: str, *, run=subprocess.run) -> dict[str, Any]:
    try:
        result = run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {"status": "error", "detail": failure_detail}
    if result.returncode:
        return {"status": "error", "detail": failure_detail}
    return {"status": "ok", "detail": "check passed"}


def operation_check(
    log_path: Path,
    action: str,
    now: datetime,
    max_age: timedelta | None = None,
) -> dict[str, Any]:
    if not log_path.is_file():
        return {"status": "error" if action == "backup" else "unknown", "detail": "no execution record"}
    latest = None
    try:
        with log_path.open(encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    return {"status": "error", "detail": "operation log contains an invalid record"}
                if not isinstance(event, dict):
                    return {"status": "error", "detail": "operation log contains an invalid record"}
                if event.get("action") == action:
                    latest = event
    except OSError:
        return {"status": "error", "detail": "operation log cannot be read"}
    if latest is None:
        return {"status": "error" if action == "backup" else "unknown", "detail": "no execution record"}
    if latest.get("status") != "success":
        return {"status": "error", "detail": f"last {action} execution failed"}
    if max_age is not None:
        try:
            completed = datetime.fromisoformat(latest["timestamp"])
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "detail": "last backup timestamp is invalid"}
        age = now - completed.astimezone(timezone.utc)
        if age > max_age:
            return {"status": "error", "detail": "last backup exceeds configured maximum age"}
        return {"status": "ok", "detail": f"last backup age is {max(0, int(age.total_seconds()))} seconds"}
    return {"status": "ok", "detail": f"last {action} execution succeeded"}


def disk_check(path: Path, minimum_free_bytes: int) -> dict[str, Any]:
    try:
        while not path.exists():
            if path.parent == path:
                raise OSError("no existing storage path")
            path = path.parent
        free_bytes = shutil.disk_usage(path).free
    except OSError:
        return {"status": "error", "detail": "storage capacity could not be checked"}
    if free_bytes < minimum_free_bytes:
        return {"status": "error", "detail": f"free storage below threshold ({free_bytes} bytes available)"}
    return {"status": "ok", "detail": f"{free_bytes} bytes available"}


def critical_log_check(*, run=subprocess.run) -> dict[str, Any]:
    try:
        logs = run(
            ["docker", "compose", "logs", "--since", "5m", "--no-color", "api", "db"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "error", "detail": "container logs could not be checked"}
    if logs.returncode:
        return {"status": "error", "detail": "container logs could not be checked"}
    if re.search(r"\b(CRITICAL|FATAL|PANIC|Traceback)\b", logs.stdout, re.IGNORECASE):
        return {"status": "error", "detail": "critical error markers found in the last five minutes"}
    return {"status": "ok", "detail": "no critical error markers in the last five minutes"}


def send_optional_alert(checks: dict[str, dict[str, Any]]) -> dict[str, str]:
    webhook = os.environ.get("NEXO_ALERT_WEBHOOK_URL")
    if not webhook:
        return {"status": "disabled"}
    failures = [name for name, result in checks.items() if result["status"] == "error"]
    body = json.dumps(
        {"status": "degraded" if failures else "ok", "failed_checks": failures},
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if 200 <= response.status < 300:
                return {"status": "sent"}
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        pass
    return {"status": "failed"}


def main() -> int:
    backup_dir = Path(os.environ.get("NEXO_BACKUP_DIR", "backups"))
    try:
        minimum_free_mb = int(os.environ.get("NEXO_MIN_FREE_STORAGE_MB", "1024"))
        max_backup_age_hours = int(os.environ.get("NEXO_BACKUP_MAX_AGE_HOURS", "24"))
    except ValueError:
        print("Monitoring thresholds must be integers.", file=sys.stderr)
        return 2
    if minimum_free_mb < 0 or max_backup_age_hours < 1:
        print("Monitoring thresholds are out of range.", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    checks = {
        "api": api_check(os.environ.get("NEXO_HEALTH_URL", "http://127.0.0.1:8000/api/v1/health")),
        "postgres": docker_check(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "sh",
                "-c",
                'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
            ],
            "PostgreSQL is unavailable",
        ),
        "last_backup": operation_check(
            operation_log_path(),
            "backup",
            now,
            timedelta(hours=max_backup_age_hours),
        ),
        "local_storage": disk_check(backup_dir, minimum_free_mb * 1024 * 1024),
        "external_storage": (
            disk_check(
                Path(os.environ["NEXO_EXTERNAL_BACKUP_DIR"]),
                minimum_free_mb * 1024 * 1024,
            )
            if os.environ.get("NEXO_EXTERNAL_BACKUP_DIR")
            else {"status": "unknown", "detail": "no external storage is configured"}
        ),
        "critical_errors": critical_log_check(),
        "last_restore": operation_check(operation_log_path(), "restore", now),
    }
    alert = send_optional_alert(checks)
    report = {
        "checked_at": now.isoformat(),
        "status": "ok" if all(check["status"] != "error" for check in checks.values()) else "degraded",
        "checks": checks,
        "external_alert": alert["status"],
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
