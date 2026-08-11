"""
RF001 - Autenticação (sem cadastro - apenas 3 contas fixas, ver database.py).
JWT simples, foco em seguranca conforme pedido:
  - senha com hash bcrypt (nunca texto puro)
  - token com expiracao
  - segredo lido de variavel de ambiente (nunca hardcoded em producao)
"""
import os
import datetime
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db, pwd_context
from .models import User

def _load_or_create_secret_key():
    """
    A chave precisa ser ESTAVEL entre reinicios do servidor, senao todo mundo
    e deslogado a cada deploy/restart. Prioridade:
      1) variavel de ambiente ROTAHUB_SECRET_KEY (recomendado em producao)
      2) arquivo local .secret_key (gerado uma vez, deve ir no gitignore)
    """
    env_key = os.environ.get("ROTAHUB_SECRET_KEY")
    if env_key:
        return env_key
    key_path = os.path.join(os.path.dirname(__file__), "..", ".secret_key")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    new_key = os.urandom(32).hex()
    with open(key_path, "w") as f:
        f.write(new_key)
    return new_key


SECRET_KEY = _load_or_create_secret_key()
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def authenticate_user(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.password_hash):
        return None
    return user


def create_access_token(user: User):
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": user.username, "uid": user.id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais invalidas ou expiradas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("uid")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user
