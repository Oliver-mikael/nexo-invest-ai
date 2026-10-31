"""Motor de base de datos: SQLite en desarrollo, PostgreSQL en producción.

El backend nunca crea el esquema a ciegas en producción: `NEXO_AUTO_CREATE_SCHEMA=0`
deja esa responsabilidad a Alembic (`alembic upgrade head`).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, load_settings


class Base(DeclarativeBase):
    pass


_settings: Optional[Settings] = None
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def configure(settings: Optional[Settings] = None) -> None:
    """Reconfigura el motor (usado por pruebas y por el arranque de la app)."""
    global _settings, _engine, _session_factory
    _settings = settings or load_settings()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def _build_engine(settings: Settings) -> Engine:
    dsn = settings.database_dsn
    kwargs = {"echo": settings.sql_echo, "future": True, "pool_pre_ping": True}
    if dsn.startswith("sqlite"):
        if dsn.startswith("sqlite:///") and not dsn.endswith(":memory:"):
            raw_path = dsn.replace("sqlite:///", "", 1)
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(dsn, **kwargs)
    if dsn.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def init_db() -> None:
    """Crea el esquema si la configuración lo permite (desarrollo y pruebas)."""
    from app import models  # noqa: F401  (registra las tablas en Base.metadata)

    settings = get_settings()
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición, con commit al terminar.

    Sin el commit explícito, un `flush` dentro del manejador se perdería al cerrar
    la sesión (fue un error real detectado por las pruebas: el registro devolvía
    201 y la sesión recién creada no existía en la siguiente petición).
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
