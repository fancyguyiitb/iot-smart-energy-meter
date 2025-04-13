import jwt
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer


from config import settings

security = HTTPBearer()


SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 3600


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def create_access_token(device_id: str, username: str) -> str:
    """Generate a JWT token with expiration"""

    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"uname": username, "device_id": device_id, "exp": expire}

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
    """Verify JWT token and return decoded payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload  # Contains device_id & uname
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
