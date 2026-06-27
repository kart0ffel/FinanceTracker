import os
from sqlmodel import SQLModel, Session, create_engine

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "finance.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

os.makedirs(DATA_DIR, exist_ok=True)

# check_same_thread=False is safe here because SQLite + FastAPI's threadpool
# combined with a single-worker setup; SQLModel/SQLAlchemy handles locking.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
