import hashlib
import secrets
import unicodedata
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Request

from .database import now
from .logic import fail

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(20))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def username(value):
    name = unicodedata.normalize("NFKC", value).strip()
    if not 2 <= len(name) <= 40 or any(not (c.isalnum() or c in "_-") for c in name):
        fail("用户名需为 2 至 40 个字母、汉字、数字、下划线或短横线")
    return name, name.casefold()


def verify(hash_value, password):
    try:
        return hasher.verify(hash_value, password)
    except VerificationError:
        return False


def create_session(db, user_id):
    token = secrets.token_urlsafe(32)
    db.sessions.insert_one({"tokenHash": digest(token), "userId": user_id,
                            "createdAt": now(), "expiresAt": now() + timedelta(hours=12), "schemaVersion": 1})
    return token


def current_user(request: Request):
    token = request.cookies.get("survey_session")
    if not token:
        fail("请先登录", 401)
    session = request.app.state.db.sessions.find_one({"tokenHash": digest(token), "expiresAt": {"$gt": now()}})
    if not session:
        fail("登录已过期，请重新登录", 401)
    user = request.app.state.db.users.find_one({"_id": session["userId"]})
    if not user:
        fail("账号不存在", 401)
    return user
