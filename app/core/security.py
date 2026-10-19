from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from pwdlib import PasswordHash
from app.core.config import settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)

def create_access_token(subject: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    return jwt.encode({"sub": subject, "exp": expires}, settings.jwt_secret_key, algorithm=ALGORITHM)

def decode_subject(token: str) -> str:
    try:
        subject = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM]).get("sub")
        if not subject: raise ValueError("Missing subject")
        return subject
    except (JWTError, ValueError) as exc:
        raise ValueError("Invalid access token") from exc
