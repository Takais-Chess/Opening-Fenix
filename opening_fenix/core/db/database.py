import os
import threading
import time
import sqlite3
import weakref
from typing import Type
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm.decl_api import DeclarativeMeta
from sqlalchemy.pool import QueuePool, StaticPool
from sqlalchemy.exc import DatabaseError, OperationalError
from opening_fenix.core.db.models import Base, UserBase

_db_init_lock = threading.RLock()
_verified_db_keys: set[tuple[str, int]] = set()
_REPO_SCHEMA_VERSION = 2
_USER_SCHEMA_VERSION = 2

def commit_with_retry(session: Session, max_retries: int = 15, initial_delay: float = 0.1) -> None:
    """
    Commits a SQLAlchemy session, retrying automatically with exponential backoff if 
    a SQLite database lock error ('database is locked' / 'database is busy') occurs.
    """
    from sqlalchemy.exc import PendingRollbackError, InvalidRequestError
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            session.commit()
            return
        except (OperationalError, DatabaseError, sqlite3.OperationalError, PendingRollbackError, InvalidRequestError) as e:
            err_str = str(e).lower()
            if "database is locked" in err_str or "locked" in err_str or "busy" in err_str or "pendingrollbackerror" in err_str or "transaction has been rolled back" in err_str:
                if attempt == max_retries - 1:
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    raise
                # On Qt main thread, process non-input events during retry delay so GUI stays responsive and doesn't freeze
                try:
                    from PyQt6.QtCore import QCoreApplication, QThread, QEventLoop
                    from PyQt6.QtWidgets import QApplication
                    app = QApplication.instance()
                    is_main_thread = app is not None and QThread.currentThread() == app.thread()
                except Exception:
                    is_main_thread = False

                if is_main_thread:
                    t_end = time.perf_counter() + delay
                    while time.perf_counter() < t_end:
                        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                        time.sleep(0.005)
                else:
                    time.sleep(delay)
                delay = min(delay * 1.5, 2.0)
            else:
                try:
                    session.rollback()
                except Exception:
                    pass
                raise

def _is_orphaned_pages_only(result: str) -> bool:
    """Returns True if PRAGMA quick_check reported only unused/orphaned pages."""
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return False
    has_page_warning = False
    for line in lines:
        if line.startswith("*** in database ") and line.endswith("***"):
            continue
        if line.startswith("Page ") and line.endswith(": never used"):
            has_page_warning = True
            continue
        return False
    return has_page_warning


class DatabaseCorruptedException(Exception):
    """Raised when a SQLite database is physically corrupted or malformed."""
    pass

class DatabaseManager:
    """
    Manages SQLite database connections, configuration, and migrations.

    This class handles the creation of the SQLAlchemy engine, configures
    SQLite PRAGMAS for optimal performance (e.g., WAL mode, 60s busy_timeout),
    and applies schema migrations automatically on startup.
    """
    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, db_filename: str, base: Type = Base) -> None:
        """
        Initialize the DatabaseManager.

        Args:
            db_filename: The file path to the SQLite database.
            base: The declarative base class containing the metadata to create tables.
        """
        self.db_filename = db_filename
        with _db_init_lock:
            DatabaseManager._instances.add(self)
            if db_filename == ":memory:":
                self.engine = create_engine('sqlite://', echo=False, connect_args={'check_same_thread': False}, poolclass=StaticPool)
            else:
                os.makedirs(os.path.dirname(db_filename) if os.path.dirname(db_filename) else ".", exist_ok=True)
                self.engine = create_engine(
                    f'sqlite:///{db_filename}',
                    echo=False,
                    connect_args={'timeout': 60, 'check_same_thread': False},
                    poolclass=QueuePool,
                    pool_size=2,
                    max_overflow=4,
                )
            self._session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

            if db_filename != ":memory:":
                is_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
                @event.listens_for(self.engine, "connect")
                def _set_sqlite_pragmas(dbapi_connection, connection_record):
                    try:
                        dbapi_connection.execute("PRAGMA busy_timeout=60000")
                        dbapi_connection.execute("PRAGMA synchronous=OFF" if is_pytest else "PRAGMA synchronous=NORMAL")
                        dbapi_connection.execute("PRAGMA cache_size=-64000")
                        dbapi_connection.execute("PRAGMA mmap_size=268435456")
                        dbapi_connection.execute("PRAGMA temp_store=MEMORY")
                    except Exception:
                        pass

            try:
                norm_key = (os.path.abspath(db_filename), id(base)) if db_filename != ":memory:" else None
                had_existing_db = (
                    norm_key is not None
                    and os.path.exists(db_filename)
                    and os.path.getsize(db_filename) > 0
                )
                if had_existing_db and norm_key in _verified_db_keys:
                    return
                base.metadata.create_all(self.engine)
                if db_filename != ":memory:":
                    try:
                        with self.engine.begin() as conn:
                            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                    except Exception:
                        pass
                if had_existing_db:
                    self._check_integrity()
                    self._migrate_schema(base)
                elif db_filename != ":memory:":
                    try:
                        ver = _REPO_SCHEMA_VERSION if base is Base else _USER_SCHEMA_VERSION
                        with self.engine.begin() as conn:
                            conn.exec_driver_sql(f"PRAGMA user_version = {ver}")
                    except Exception:
                        pass
                if norm_key is not None:
                    _verified_db_keys.add(norm_key)
            except DatabaseError as e:
                from opening_fenix.core.logger import logger
                logger.error(f"Database error during initialization: {e}")
                self.close()
                raise DatabaseCorruptedException(f"Database is corrupted or malformed: {e}")
            except Exception as e:
                # Check if it's the raw sqlite3 DatabaseError which sometimes escapes SQLAlchemy
                import sqlite3
                if isinstance(e, sqlite3.DatabaseError):
                    from opening_fenix.core.logger import logger
                    logger.error(f"SQLite error during initialization: {e}")
                    self.close()
                    raise DatabaseCorruptedException(f"Database is corrupted or malformed: {e}")
                raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def invalidate_verified_key(cls, db_filename: str) -> None:
        if not db_filename or db_filename == ":memory:":
            return
        abs_p = os.path.abspath(db_filename)
        with _db_init_lock:
            for k in list(_verified_db_keys):
                if k[0] == abs_p:
                    _verified_db_keys.discard(k)

    def _check_integrity(self) -> None:
        """Verifies the physical integrity of the database file."""
        try:
            with self.engine.connect() as conn:
                # Use quick_check for startup to avoid long delays on large DBs
                rows = conn.execute(text("PRAGMA quick_check")).fetchall()
                result = "\n".join(str(r[0]) for r in rows if r and r[0] is not None)
                if result != "ok":
                    from opening_fenix.core.logger import logger
                    if _is_orphaned_pages_only(result):
                        logger.warning(
                            "Database integrity check found only orphaned pages; "
                            "attempting automatic VACUUM repair..."
                        )
                        try:
                            conn.rollback()
                            conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
                            rows = conn.execute(text("PRAGMA quick_check")).fetchall()
                            result = "\n".join(str(r[0]) for r in rows if r and r[0] is not None)
                            if result == "ok":
                                logger.info("Automatic VACUUM repair succeeded.")
                                return
                        except Exception as vacuum_err:
                            logger.error(f"Automatic VACUUM repair failed: {vacuum_err}")
                    logger.error(f"Database integrity check failed: {result}")
                    raise DatabaseCorruptedException(f"Integrity check failed: {result}")
        except DatabaseCorruptedException:
            raise
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Error during integrity check: {e}")
            import sqlite3
            if isinstance(e, sqlite3.DatabaseError) or "database disk image is malformed" in str(e).lower():
                raise DatabaseCorruptedException(f"Database is corrupted or malformed: {e}")

    def _migrate_schema(self, base: Type) -> None:
        """
        Performs automatic schema migrations for existing databases to ensure 
        compatibility with new models.

        Args:
            base: The declarative base class whose schema needs migration.
        """
        try:
            with self.engine.connect() as conn:
                target_ver = _REPO_SCHEMA_VERSION if base is Base else _USER_SCHEMA_VERSION
                cur_ver_row = conn.execute(text("PRAGMA user_version")).fetchone()
                cur_ver = cur_ver_row[0] if cur_ver_row else 0
                if cur_ver >= target_ver:
                    return

                if base is Base:
                    result = conn.execute(text("PRAGMA table_info(moves)"))
                    columns = [row[1] for row in result.fetchall()]
                    
                    if columns and 'nag' not in columns:
                        conn.execute(text("ALTER TABLE moves ADD COLUMN nag INTEGER DEFAULT 0"))
                    
                    # Check for new Position columns
                    result = conn.execute(text("PRAGMA table_info(positions)"))
                    pos_columns = [row[1] for row in result.fetchall()]
                    
                    for col in ['variation_3', 'cached_v1', 'cached_v2', 'cached_v3', 'last_overhaul_review', 'is_hole_exempt']:
                        if col not in pos_columns:
                            type_map = {
                                'last_overhaul_review': "DATETIME",
                                'is_hole_exempt': "BOOLEAN DEFAULT 0"
                            }
                            type_str = type_map.get(col, "VARCHAR")
                            conn.execute(text(f"ALTER TABLE positions ADD COLUMN {col} {type_str}"))

                    # Ensure indexes on Position, Move, RepertoireMove, LichessData for existing databases
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_positions_analysis_depth ON positions (analysis_depth)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_positions_is_hole_exempt ON positions (is_hole_exempt)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_moves_to_pos_prio ON moves (to_position_id, priority_score)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rep_moves_active_level_move ON repertoire_moves (is_active, level, move_id)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lichess_data_elo_range ON lichess_data (elo_range)"))

                    # Check for new RepertoireLevel columns
                    result = conn.execute(text("PRAGMA table_info(repertoire_levels)"))
                    rl_columns = [row[1] for row in result.fetchall()]
                    if rl_columns and 'target_elo' not in rl_columns:
                        conn.execute(text("ALTER TABLE repertoire_levels ADD COLUMN target_elo INTEGER DEFAULT 1500"))

                    # Check for new RepertoireMove columns
                    result = conn.execute(text("PRAGMA table_info(repertoire_moves)"))
                    rm_columns = [row[1] for row in result.fetchall()]
                    if rm_columns and 'is_active' not in rm_columns:
                        conn.execute(text("ALTER TABLE repertoire_moves ADD COLUMN is_active BOOLEAN DEFAULT 1"))

                    # Check for new LichessData columns
                    result = conn.execute(text("PRAGMA table_info(lichess_data)"))
                    ld_columns = [row[1] for row in result.fetchall()]
                    if ld_columns and 'fetched_at' not in ld_columns:
                        conn.execute(text("ALTER TABLE lichess_data ADD COLUMN fetched_at DATETIME"))

                    conn.execute(text(f"PRAGMA user_version = {_REPO_SCHEMA_VERSION}"))
                    conn.commit()
                
                elif base is UserBase:
                    result = conn.execute(text("PRAGMA table_info(user_repertoire_settings)"))
                    urs_columns = [row[1] for row in result.fetchall()]
                    if urs_columns:
                        if 'comment_language' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN comment_language VARCHAR DEFAULT 'auto'"))
                        if 'rating' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN rating FLOAT DEFAULT 800.0"))
                        if 'last_rating_update' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN last_rating_update DATETIME"))
                        if 'last_new_count' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN last_new_count INTEGER DEFAULT 0"))
                        if 'last_due_count' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN last_due_count INTEGER DEFAULT 0"))
                        if 'last_dist_json' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN last_dist_json VARCHAR"))
                        if 'stats_updated_at' not in urs_columns:
                            conn.execute(text("ALTER TABLE user_repertoire_settings ADD COLUMN stats_updated_at DATETIME"))

                    # Ensure composite index on TrainingData(repertoire_name, next_due) for existing user databases
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_training_data_repo_due ON training_data (repertoire_name, next_due)"))
                    conn.execute(text(f"PRAGMA user_version = {_USER_SCHEMA_VERSION}"))
                    conn.commit()

        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.warning(f"Migration warning: {e}")

    def get_session(self) -> Session:
        """
        Creates and returns a new SQLAlchemy Session bound to this engine.

        Returns:
            A new SQLAlchemy Session instance.
        """
        return self._session_factory()

    def close(self) -> None:
        """Disposes the underlying SQLAlchemy engine and connection pool."""
        try:
            self.engine.dispose()
        except Exception:
            pass
        finally:
            DatabaseManager._instances.discard(self)

    @classmethod
    def close_all_for_path(cls, db_filename: str) -> None:
        """Disposes all active DatabaseManager engines bound to the given file path."""
        if not db_filename:
            return
        try:
            cls.invalidate_verified_key(db_filename)
            target_abs = os.path.abspath(db_filename).lower()
            for inst in list(cls._instances):
                try:
                    if inst.db_filename and inst.db_filename != ":memory:":
                        inst_abs = os.path.abspath(inst.db_filename).lower()
                        if inst_abs == target_abs:
                            inst.close()
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def close_all_for_directory(cls, dir_path: str) -> None:
        """Disposes all active DatabaseManager engines bound to any DB within the given directory."""
        if not dir_path:
            return
        try:
            dir_abs = os.path.abspath(dir_path).lower()
            prefix = dir_abs if dir_abs.endswith(os.sep) else dir_abs + os.sep
            for inst in list(cls._instances):
                try:
                    if inst.db_filename and inst.db_filename != ":memory:":
                        inst_abs = os.path.abspath(inst.db_filename).lower()
                        if inst_abs == dir_abs or inst_abs.startswith(prefix):
                            cls.invalidate_verified_key(inst.db_filename)
                            inst.close()
                except Exception:
                    pass
        except Exception:
            pass
