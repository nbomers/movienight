from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

# SQLite: check_same_thread=False nötig weil FastAPI mehrere Threads nutzen kann
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """
    FastAPI Dependency: Gibt eine DB-Session zurück und schließt sie nach dem Request.
    Wird per `Depends(get_db)` in Endpunkten verwendet.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
