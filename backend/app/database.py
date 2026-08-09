import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from .models import Base, User

DB_PATH = os.environ.get("ROTAHUB_DB", os.path.join(os.path.dirname(__file__), "..", "rotahub.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(reset: bool = False):
    """Cria as tabelas e os 3 usuários fixos (RF001 - sem cadastro)."""
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        fixed_users = [
            # username, senha_inicial, nome de exibição
            ("matheus", "rotahub2026", "Matheus"),
            ("bruna", "rotahub2026", "Bruna"),
            ("paulo", "rotahub2026", "Paulo"),
        ]
        for username, password, display_name in fixed_users:
            existing = db.query(User).filter(User.username == username).first()
            if not existing:
                db.add(User(
                    username=username,
                    password_hash=pwd_context.hash(password),
                    display_name=display_name,
                ))
        db.commit()
    finally:
        db.close()
