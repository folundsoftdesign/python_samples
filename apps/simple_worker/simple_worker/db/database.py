"""
Database configuration for the task worker.

This module sets up the database connection and session management for the application.
"""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# SQLite connection setup
sqlite_file = Path(__file__).parent.parent.parent / "data" / "database.db"
sqlite_url = f"sqlite:///{sqlite_file}"

engine = create_engine(
    sqlite_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
)


def initialize_db():
    """
    Initialize the database by creating all tables defined in SQLModel.

    This function should be called once at application startup.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    Create and yield a new database session.

    This function is designed to be used as a FastAPI dependency.
    """
    with Session(engine) as session:
        yield session
