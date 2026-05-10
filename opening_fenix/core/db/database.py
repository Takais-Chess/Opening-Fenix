import os
from typing import Type
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm.decl_api import DeclarativeMeta
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.exc import DatabaseError
from opening_fenix.core.db.models import Base, UserBase

class DatabaseCorruptedException(Exception):
    """Raised when a SQLite database is physically corrupted or malformed."""
    pass

class DatabaseManager:
    """
    Manages SQLite database connections, configuration, and migrations.

    This class handles the creation of the SQLAlchemy engine, configures
    SQLite PRAGMAS for optimal performance (e.g., WAL mode), and applies
    schema migrations automatically on startup.
    """

    def __init__(self, db_filename: str, base: Type = Base) -> None:
        """
        Initialize the DatabaseManager.

        Args:
            db_filename: The file path to the SQLite database.
            base: The declarative base class containing the metadata to create tables.
        """
        if db_filename == ":memory:":
            self.engine = create_engine('sqlite://', echo=False, connect_args={'check_same_thread': False}, poolclass=StaticPool)
        else:
            os.makedirs(os.path.dirname(db_filename) if os.path.dirname(db_filename) else ".", exist_ok=True)
            self.engine = create_engine(f'sqlite:///{db_filename}', echo=False, connect_args={'timeout': 15}, poolclass=NullPool)
        
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            _ = connection_record
            cursor = dbapi_connection.cursor()
            # Reverted to WAL for maximum performance
            cursor.execute("PRAGMA journal_mode=WAL")
            # FULL synchronous provides maximum safety against corruption during crashes
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()
        
        try:
            base.metadata.create_all(self.engine)
            self._check_integrity()
            self._migrate_schema(base)
        except DatabaseError as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Database error during initialization: {e}")
            raise DatabaseCorruptedException(f"Database is corrupted or malformed: {e}")
        except Exception as e:
            # Check if it's the raw sqlite3 DatabaseError which sometimes escapes SQLAlchemy
            import sqlite3
            if isinstance(e, sqlite3.DatabaseError):
                from opening_fenix.core.logger import logger
                logger.error(f"SQLite error during initialization: {e}")
                raise DatabaseCorruptedException(f"Database is corrupted or malformed: {e}")
            raise

    def _check_integrity(self) -> None:
        """Verifies the physical integrity of the database file."""
        try:
            with self.engine.connect() as conn:
                # Use quick_check for startup to avoid long delays on large DBs
                result = conn.execute(text("PRAGMA quick_check")).scalar()
                if result != "ok":
                    from opening_fenix.core.logger import logger
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
                if base is Base:
                    result = conn.execute(text("PRAGMA table_info(moves)"))
                    columns = [row[1] for row in result.fetchall()]
                    
                    if columns and 'nag' not in columns:
                        conn.execute(text("ALTER TABLE moves ADD COLUMN nag INTEGER DEFAULT 0"))
                        conn.commit()
                    
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
                            conn.commit()

                    # Check for new RepertoireLevel columns
                    result = conn.execute(text("PRAGMA table_info(repertoire_levels)"))
                    rl_columns = [row[1] for row in result.fetchall()]
                    if rl_columns and 'target_elo' not in rl_columns:
                        conn.execute(text("ALTER TABLE repertoire_levels ADD COLUMN target_elo INTEGER DEFAULT 1500"))
                        conn.commit()

                    # Check for new RepertoireMove columns
                    result = conn.execute(text("PRAGMA table_info(repertoire_moves)"))
                    rm_columns = [row[1] for row in result.fetchall()]
                    if rm_columns and 'is_active' not in rm_columns:
                        conn.execute(text("ALTER TABLE repertoire_moves ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                        conn.commit()
                
                elif base is UserBase:
                    result = conn.execute(text("PRAGMA table_info(user_repertoire_settings)"))
                    urs_columns = [row[1] for row in result.fetchall()]
                    if urs_columns:
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
        return sessionmaker(bind=self.engine, autoflush=False)()

    def close(self) -> None:
        """Disposes the underlying SQLAlchemy engine and connection pool."""
        self.engine.dispose()
