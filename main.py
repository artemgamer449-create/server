import asyncio
import hashlib
import json
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Подключаем uvloop для максимальной скорости асинхронности в Uvicorn
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

import httpx
import jwt
import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "visiongram.db")))
DB_DIR = DB_PATH.parent
PANEL_DIR = Path(os.getenv("PANEL_DIR", str(ROOT / "panel")))

TURNSTILE_SECRET = os.getenv(
    "TURNSTILE_SECRET",
    "0x4AAAAAAFi7N0fDNvk3lZQdJ1pn84WXiB4",
).strip()
TURNSTILE_SITE_KEY = os.getenv(
    "TURNSTILE_SITE_KEY",
    "0x4AAAAAAFi7N7hnSxXvj04S",
).strip()
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

KEEPALIVE_URL = os.getenv("KEEPALIVE_URL", "https://sayhost.online/health").strip()
KEEPALIVE_INTERVAL_SECONDS = int(os.getenv("KEEPALIVE_INTERVAL_SECONDS", "300"))

ACCESS_TOKEN_TTL_DAYS = 30
PBKDF2_ITERATIONS = 240_000
STARTED_AT = time.time()

OWNER_USERNAME = os.getenv("OWNER_USERNAME", "owner").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "chmchm333222111")


def build_engine():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
    )


engine = build_engine()


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)


class DbSession(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    device = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)


class Verified(Base):
    __tablename__ = "verified"
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, index=True)


class AvatarShape(Base):
    __tablename__ = "avatar_shapes"
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    shape = Column(String, nullable=False, default="circle")
    updated_at = Column(DateTime, nullable=False, index=True)


AVATAR_SHAPES = [
    "circle",
    "rounded",
    "squircle",
    "square",
    "diamond",
    "hexagon",
    "octagon",
    "star",
    "leaf",
    "none",
]


def utcnow():
    return datetime.now(timezone.utc)


def load_secret_key() -> str:
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    path = DB_DIR / ".jwt_secret"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        key = secrets.token_hex(32)
        path.write_text(key, encoding="utf-8")
        return key
    except OSError:
        # WHY: on ephemeral filesystems the file cannot persist; derive a
        # stable key from owner credentials so logins survive restarts.
        material = f"{OWNER_USERNAME}:{OWNER_PASSWORD}:visionpanel".encode("utf-8")
        return hashlib.pbkdf2_hmac(
            "sha256",
            material,
            b"visionpanel-static-jwt-salt",
            1,
        ).hex()


SECRET_KEY = load_secret_key()
JWT_ALGORITHM = "HS256"


def hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()


def initialize() -> None:
    Base.metadata.create_all(engine)
    if not OWNER_USERNAME or not OWNER_PASSWORD:
        return
    with SessionLocal() as db:
        existing = db.execute(
            select(User).where(User.username == OWNER_USERNAME)
        ).scalar_one_or_none()
        if existing is None:
            salt = secrets.token_hex(16)
            db.add(
                User(
                    username=OWNER_USERNAME,
                    password_hash=hash_password(OWNER_PASSWORD, salt),
                    password_salt=salt,
                    created_at=utcnow(),
                )
            )
            db.commit()


initialize()

app = FastAPI(
    title="VisionPanel API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_keepalive():
    if not KEEPALIVE_URL:
        return

    async def keepalive_loop():
        # WHY: periodic self-ping keeps proxies and free tiers from treating
        # the service as idle, so first responses stay fast.
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                try:
                    await client.get(KEEPALIVE_URL)
                except Exception:
                    pass
                await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)

    asyncio.create_task(keepalive_loop())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def now_iso() -> str:
    return utcnow().replace(tzinfo=None).isoformat(timespec="seconds")


def create_access_token(user_id: int, session_id: str) -> str:
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ACCESS_TOKEN_TTL_DAYS * 24 * 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def parse_device(user_agent: str | None) -> str:
    agent = (user_agent or "").lower()
    if not agent:
        return "Unknown"
    os_name = "Unknown"
    if "windows" in agent:
        os_name = "Windows"
    elif "android" in agent:
        os_name = "Android"
    elif "iphone" in agent or "ipad" in agent or "ios" in agent:
        os_name = "iOS"
    elif "mac os" in agent or "macintosh" in agent:
        os_name = "macOS"
    elif "linux" in agent:
        os_name = "Linux"
    client = "Other"
    if "edg" in agent:
        client = "Edge"
    elif "chrome" in agent and "chromium" not in agent:
        client = "Chrome"
    elif "firefox" in agent:
        client = "Firefox"
    elif "safari" in agent and "chrome" not in agent:
        client = "Safari"
    return f"{os_name} · {client}"


def require_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    session_id = payload.get("sid")
    user_id = payload.get("sub")
    if not session_id or not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    session = db.execute(
        select(DbSession).where(DbSession.id == session_id)
    ).scalar_one_or_none()
    if session is not None and session.revoked:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    if session is None:
        # WHY: valid token with no row means the database was reset; restore
        # the session so users are not logged out by a server restart.
        session = DbSession(
            id=session_id,
            user_id=int(user_id),
            created_at=utcnow(),
            last_seen_at=utcnow(),
            revoked=False,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    if str(session.user_id) != str(user_id):
        raise HTTPException(status_code=401, detail="Session mismatch")
    session.last_seen_at = utcnow()
    db.commit()
    user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_current_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> DbSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    session_id = payload.get("sid")
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    session = db.execute(
        select(DbSession).where(DbSession.id == session_id)
    ).scalar_one_or_none()
    if session is None or session.revoked:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    return session


async def verify_turnstile(token: str, remote_ip: str | None) -> bool:
    if not TURNSTILE_SECRET:
        return bool(token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                TURNSTILE_VERIFY_URL,
                data={
                    "secret": TURNSTILE_SECRET,
                    "response": token,
                    "remoteip": remote_ip or "",
                },
            )
            response.raise_for_status()
            data = response.json()
            return bool(data.get("success"))
    except httpx.HTTPError:
        return False


def is_owner(account: User) -> bool:
    return bool(OWNER_USERNAME) and account.username.strip().lower() == OWNER_USERNAME.strip().lower()


def public_user_view(account: User) -> dict:
    return {
        "id": account.id,
        "username": account.username,
        "created_at": account.created_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        "is_owner": is_owner(account),
    }


def require_owner(user: User = Depends(require_user)) -> User:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Owner only")
    return user


class AccountCreatePayload(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=256)


@app.get("/api/accounts")
def list_accounts(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return {"accounts": [public_user_view(row) for row in rows]}


@app.post("/api/accounts")
def create_account(
    payload: AccountCreatePayload,
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    existing = db.execute(
        select(User).where(func.lower(User.username) == username.lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username is already taken")
    salt = secrets.token_hex(16)
    user = User(
        username=username,
        password_hash=hash_password(payload.password, salt),
        password_salt=salt,
        created_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"ok": True, "account": public_user_view(user)}


@app.delete("/api/accounts/{user_id}")
def delete_account(
    user_id: int,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    row = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if is_owner(row):
        raise HTTPException(status_code=400, detail="Cannot delete the owner account")
    for session_row in db.execute(
        select(DbSession).where(DbSession.user_id == user_id)
    ).scalars().all():
        db.delete(session_row)
    db.delete(row)
    db.commit()
    return {"ok": True, "id": user_id, "by": owner.id}


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    turnstile_token: str = Field(min_length=1, max_length=4096)


@app.post("/api/auth/login")
async def login(payload: LoginPayload, request: Request):
    ip = request.client.host if request.client else None
    token = payload.turnstile_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Turnstile token is required")
    if not await verify_turnstile(token, ip):
        raise HTTPException(status_code=403, detail="Turnstile verification failed")

    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.username == payload.username.strip())
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        expected = hash_password(payload.password, user.password_salt)
        if not secrets.compare_digest(expected, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        session_id = uuid.uuid4().hex
        user_agent = request.headers.get("user-agent")
        db.add(
            DbSession(
                id=session_id,
                user_id=user.id,
                ip=ip,
                user_agent=user_agent,
                device=parse_device(user_agent),
                created_at=utcnow(),
                last_seen_at=utcnow(),
                revoked=False,
            )
        )
        db.commit()

    access_token = create_access_token(user.id, session_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_DAYS * 24 * 3600,
        "user": public_user_view(user),
    }


@app.post("/api/auth/logout")
def logout(
    session: DbSession = Depends(require_current_session),
    db: Session = Depends(get_db),
):
    session.revoked = True
    db.commit()
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(require_user)):
    return public_user_view(user)


class SessionView(BaseModel):
    id: str
    ip: str | None
    device: str | None
    user_agent: str | None
    created_at: str
    last_seen_at: str | None
    revoked: bool
    current: bool


def session_view(session: DbSession, current_session_id: str) -> dict:
    return {
        "id": session.id,
        "ip": session.ip,
        "device": session.device,
        "user_agent": session.user_agent,
        "created_at": session.created_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        "last_seen_at": session.last_seen_at.replace(tzinfo=None).isoformat(timespec="seconds")
        if session.last_seen_at
        else None,
        "revoked": bool(session.revoked),
        "current": session.id == current_session_id,
    }


@app.get("/api/sessions")
def list_sessions(
    user: User = Depends(require_user),
    session: DbSession = Depends(require_current_session),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(DbSession)
        .where(DbSession.user_id == user.id, DbSession.revoked == False)  # noqa: E712
        .order_by(DbSession.last_seen_at.desc())
    ).scalars().all()
    return {"sessions": [session_view(row, session.id) for row in rows]}


@app.delete("/api/sessions/{session_id}")
def terminate_session(
    session_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(DbSession).where(
            DbSession.id == session_id,
            DbSession.user_id == user.id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row.revoked = True
    db.commit()
    return {"ok": True, "id": session_id}


class SystemHealth(BaseModel):
    ram: dict
    disk: dict
    ping: dict
    uptime: int
    timestamp: str
    counts: dict


@app.get("/api/system")
def system_health(user: User = Depends(require_user), db: Session = Depends(get_db)):
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(str(DB_PATH.resolve().anchor or "/"))
    started = time.time()
    with engine.connect() as connection:
        connection.execute(select(func.count()).select_from(User))
        db_ping_ms = round((time.time() - started) * 1000, 2)
    users_count = db.execute(select(func.count()).select_from(User)).scalar_one()
    sessions_count = db.execute(
        select(func.count()).select_from(DbSession).where(DbSession.revoked == False)  # noqa: E712
    ).scalar_one()
    badges_count = db.execute(select(func.count()).select_from(Verified)).scalar_one()
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return SystemHealth(
        ram={
            "total": memory.total,
            "used": memory.used,
            "percent": memory.percent,
        },
        disk={
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": round((disk.used / disk.total) * 100, 1),
        },
        ping={
            "db_ms": db_ping_ms,
        },
        uptime=int(time.time() - STARTED_AT),
        timestamp=now_iso(),
        counts={
            "users": users_count,
            "active_sessions": sessions_count,
            "badges": badges_count,
            "db_size": db_size,
        },
    )


class VerifiedPayload(BaseModel):
    telegram_id: int = Field(gt=0)
    username: str | None = None
    display_name: str | None = None


class VerifiedBatchPayload(BaseModel):
    telegram_ids: list[int] = Field(default_factory=list, max_length=500)


def verified_view(row: Verified) -> dict:
    return {
        "telegram_id": row.telegram_id,
        "username": row.username,
        "display_name": row.display_name,
        "verified": True,
        "updated_at": row.updated_at.replace(tzinfo=None).isoformat(timespec="seconds"),
    }


@app.get("/api/verified")
def list_verified(
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    statement = select(Verified).order_by(Verified.updated_at.desc())
    if q:
        term = q.strip().lstrip("@").lower()
        statement = statement.where(
            (Verified.username == term)
            | (Verified.display_name.like(f"%{q.strip()}%"))
            | (Verified.telegram_id.cast(String).like(f"%{term}%"))
        )
    rows = db.execute(statement.limit(limit).offset(offset)).scalars().all()
    return {"verified": [verified_view(row) for row in rows]}


@app.post("/api/verified/set")
def set_verified(
    payload: VerifiedPayload,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(Verified).where(Verified.telegram_id == payload.telegram_id)
    ).scalar_one_or_none()
    if row is None:
        row = Verified(
            telegram_id=payload.telegram_id,
            username=(payload.username or "").strip().lstrip("@").lower() or None,
            display_name=(payload.display_name or "").strip() or None,
            updated_at=utcnow(),
        )
        db.add(row)
    else:
        row.username = (payload.username or "").strip().lstrip("@").lower() or None
        row.display_name = (payload.display_name or "").strip() or None
        row.updated_at = utcnow()
    db.commit()
    return {"ok": True, "verified": verified_view(row)}


@app.delete("/api/verified/{telegram_id}")
def revoke_verified(
    telegram_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(Verified).where(Verified.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not verified")
    db.delete(row)
    db.commit()
    return {"ok": True, "telegram_id": telegram_id}


@app.get("/api/public/verified/{telegram_id}")
def public_verified(telegram_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(Verified).where(Verified.telegram_id == telegram_id)
    ).scalar_one_or_none()
    return {
        "telegram_id": telegram_id,
        "verified": row is not None,
    }


@app.post("/api/public/verified")
def public_verified_batch(
    payload: VerifiedBatchPayload,
    db: Session = Depends(get_db),
):
    if not payload.telegram_ids:
        return {"verified": []}
    rows = db.execute(
        select(Verified.telegram_id).where(Verified.telegram_id.in_(payload.telegram_ids))
    ).scalars().all()
    return {"verified": list(dict.fromkeys(rows))}


class AvatarShapePayload(BaseModel):
    telegram_id: int = Field(gt=0)
    shape: str = Field(min_length=1, max_length=32)
    username: str | None = None
    display_name: str | None = None


class AvatarShapesBatchPayload(BaseModel):
    telegram_ids: list[int] = Field(default_factory=list, max_length=500)


@app.post("/api/public/avatar-shape/set")
def set_avatar_shape(payload: AvatarShapePayload, db: Session = Depends(get_db)):
    shape = payload.shape.strip()
    if shape not in AVATAR_SHAPES:
        raise HTTPException(status_code=422, detail="Unknown shape")
    row = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id == payload.telegram_id)
    ).scalar_one_or_none()
    if row is None:
        db.add(
            AvatarShape(
                telegram_id=payload.telegram_id,
                username=(payload.username or "").strip().lstrip("@").lower() or None,
                display_name=(payload.display_name or "").strip() or None,
                shape=shape,
                updated_at=utcnow(),
            )
        )
    else:
        row.username = (payload.username or "").strip().lstrip("@").lower() or None
        row.display_name = (payload.display_name or "").strip() or None
        row.shape = shape
        row.updated_at = utcnow()
    db.commit()
    return {"ok": True, "telegram_id": payload.telegram_id, "shape": shape}


@app.get("/api/public/avatar-shape/{telegram_id}")
def get_avatar_shape(telegram_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        return {"telegram_id": telegram_id, "shape": "circle"}
    return {
        "telegram_id": row.telegram_id,
        "username": row.username,
        "display_name": row.display_name,
        "shape": row.shape,
    }


@app.post("/api/public/avatar-shapes")
def get_avatar_shapes_batch(
    payload: AvatarShapesBatchPayload,
    db: Session = Depends(get_db),
):
    if not payload.telegram_ids:
        return {"shapes": []}
    rows = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id.in_(payload.telegram_ids))
    ).scalars().all()
    found = {row.telegram_id: row.shape for row in rows}
    shapes = [
        {"telegram_id": telegram_id, "shape": found.get(telegram_id, "circle")}
        for telegram_id in dict.fromkeys(payload.telegram_ids)
    ]
    return {"shapes": shapes}


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "visionpanel",
        "database": str(DB_PATH),
    }


if PANEL_DIR.is_dir():
    app.mount("/", StaticFiles(directory=PANEL_DIR, html=True), name="panel")
else:

    @app.get("/")
    def index():
        return {
            "ok": True,
            "service": "visionpanel",
            "panel": "not built",
            "panel_dir": str(PANEL_DIR),
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
        loop="uvloop",
    )