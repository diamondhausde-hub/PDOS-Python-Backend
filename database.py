import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Use DATABASE_URL from environment if available, otherwise default to local SQLite
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./pdos.db")
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
pool_kwargs = {}
if not is_sqlite:
    pool_kwargs = {
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_pre_ping": True,
    }
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args, **pool_kwargs
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
