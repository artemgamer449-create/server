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


class Badge(Base):
    __tablename__ = "badges"
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=True)
    role = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, index=True)


def utcnow():
    return datetime.now(timezone.utc)


def load_secret_key() -> str:
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    path = DB_DIR / ".jwt_secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


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
    if session is None or session.revoked:
        raise HTTPException(status_code=401, detail="Session expired or revoked")
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
    badges_count = db.execute(select(func.count()).select_from(Badge)).scalar_one()
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


class BadgePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    telegram_id: int = Field(gt=0)
    username: str | None = None
    display_name: str | None = None
    role: str = Field(default="coder", min_length=1, max_length=32)
    icon: str | None = None
    label: str | None = None
    fill: str | None = None
    outline: str | None = None
    text_color: str | None = None
    glow: bool = False
    title: str | None = None
    tagline: str | None = None
    description: str | None = None
    perks: list[str] = Field(default_factory=list)


def normalize_badge(data: dict) -> dict:
    payload = dict(data)
    payload["username"] = (payload.get("username") or "").strip().lstrip("@").lower() or None
    payload["display_name"] = (payload.get("display_name") or "").strip() or None
    payload["icon"] = (payload.get("icon") or "").strip() or None
    payload["label"] = (payload.get("label") or "").strip() or None
    payload["title"] = (payload.get("title") or "").strip() or None
    payload["tagline"] = (payload.get("tagline") or "").strip() or None
    payload["description"] = (payload.get("description") or "").strip() or None
    payload["perks"] = [
        item.strip()
        for item in payload.get("perks", [])
        if isinstance(item, str) and item.strip()
    ]
    return payload


@app.get("/api/badges")
def list_badges(
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if q:
        query = q.strip().lstrip("@").lower()
        rows = db.execute(
            select(Badge)
            .where(
                (Badge.username == query)
                | (Badge.display_name.like(f"%{q.strip()}%"))
                | (Badge.telegram_id.cast(String).like(f"%{query}%"))
            )
            .order_by(Badge.updated_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    else:
        rows = db.execute(
            select(Badge).order_by(Badge.updated_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
    return {"badges": [json.loads(row.payload) for row in rows]}


@app.get("/api/badges/{telegram_id}")
def get_badge(
    telegram_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(Badge).where(Badge.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Badge not found")
    return json.loads(row.payload)


@app.post("/api/badges/set")
def set_badge(
    payload: BadgePayload,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    data = normalize_badge(payload.model_dump(exclude_none=True))
    telegram_id = int(data["telegram_id"])
    updated_at = utcnow()
    row = db.execute(
        select(Badge).where(Badge.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        db.add(
            Badge(
                telegram_id=telegram_id,
                username=data.get("username"),
                display_name=data.get("display_name"),
                role=data.get("role", "coder"),
                payload=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                updated_at=updated_at,
            )
        )
    else:
        row.username = data.get("username")
        row.display_name = data.get("display_name")
        row.role = data.get("role", "coder")
        row.payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        row.updated_at = updated_at
    db.commit()
    return {"ok": True, "badge": data, "updated_at": now_iso()}


@app.delete("/api/badges/{telegram_id}")
def delete_badge(
    telegram_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(Badge).where(Badge.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Badge not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "telegram_id": telegram_id}


@app.get("/api/public/badge/{telegram_id}")
def public_badge(telegram_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(Badge).where(Badge.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Badge not found")
    return json.loads(row.payload)


@app.get("/api/public/badges")
def public_badges(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Badge).order_by(Badge.updated_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return {"badges": [json.loads(row.payload) for row in rows]}


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
