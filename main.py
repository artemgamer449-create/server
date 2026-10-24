import base64
import hashlib
import json
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import jwt
import psutil
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, String, Text, create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "visiongram.db")))
DB_DIR = DB_PATH.parent
PANEL_DIR = Path(os.getenv("PANEL_DIR", str(ROOT / "panel")))

OWNER_USERNAME = os.getenv("OWNER_USERNAME", "owner").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "chmchm333222111")

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

MAX_FONT_SIZE = 8 * 1024 * 1024
ALLOWED_FONT_EXTENSIONS = {".ttf", ".otf"}
FONT_SIGNATURES = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")

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
    username = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    role = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class AvatarShape(Base):
    __tablename__ = "avatar_shapes"
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    shape = Column(String, nullable=False, default="circle")
    payload = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class Font(Base):
    __tablename__ = "fonts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    mime = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, nullable=False)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)


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
    title="VisionGram Preference API",
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


def get_setting(db: Session, key: str, default=None):
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return default


def set_setting(db: Session, key: str, value) -> None:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if row is None:
        db.add(Setting(key=key, value=encoded, updated_at=utcnow()))
    else:
        row.value = encoded
        row.updated_at = utcnow()
    db.commit()


def public_user_view(account: User) -> dict:
    return {
        "username": account.username,
        "created_at": account.created_at.replace(tzinfo=None).isoformat(timespec="seconds"),
    }


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


@app.get("/api/system")
def system_health(user: User = Depends(require_user), db: Session = Depends(get_db)):
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(str(DB_PATH.resolve().anchor or "/"))
    started = time.time()
    with engine.connect() as connection:
        result = connection.execute(select(Setting).limit(0))
        db_ping_ms = round((time.time() - started) * 1000, 2)
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
    )


ROLE_LABELS = {
    "owner": "Owner",
    "coder": "Developer",
    "admin": "Admin",
    "tester": "Tester",
}


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
        ).scalars().all()
    else:
        rows = db.execute(
            select(Badge).order_by(Badge.updated_at.desc()).limit(limit)
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


class AvatarShapePayload(BaseModel):
    telegram_id: int = Field(gt=0)
    username: str | None = None
    display_name: str | None = None
    shape: str = Field(default="circle", min_length=1, max_length=32)


@app.get("/api/avatar-shapes")
def list_avatar_shapes(
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if q:
        query = q.strip().lstrip("@").lower()
        rows = db.execute(
            select(AvatarShape)
            .where(
                (AvatarShape.username == query)
                | (AvatarShape.display_name.like(f"%{q.strip()}%"))
                | (AvatarShape.telegram_id.cast(String).like(f"%{query}%"))
            )
            .order_by(AvatarShape.updated_at.desc())
            .limit(limit)
        ).scalars().all()
    else:
        rows = db.execute(
            select(AvatarShape).order_by(AvatarShape.updated_at.desc()).limit(limit)
        ).scalars().all()
    return {"shapes": [json.loads(row.payload) for row in rows]}


@app.post("/api/avatar-shapes/set")
def set_avatar_shape(
    payload: AvatarShapePayload,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if payload.shape not in AVATAR_SHAPES:
        raise HTTPException(status_code=422, detail="Unknown shape")
    data = {
        "telegram_id": int(payload.telegram_id),
        "username": (payload.username or "").strip().lstrip("@").lower() or None,
        "display_name": (payload.display_name or "").strip() or None,
        "shape": payload.shape,
    }
    updated_at = utcnow()
    row = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id == data["telegram_id"])
    ).scalar_one_or_none()
    if row is None:
        db.add(
            AvatarShape(
                telegram_id=data["telegram_id"],
                username=data["username"],
                display_name=data["display_name"],
                shape=data["shape"],
                payload=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                updated_at=updated_at,
            )
        )
    else:
        row.username = data["username"]
        row.display_name = data["display_name"]
        row.shape = data["shape"]
        row.payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        row.updated_at = updated_at
    db.commit()
    return {"ok": True, "shape": data, "updated_at": now_iso()}


@app.delete("/api/avatar-shapes/{telegram_id}")
def delete_avatar_shape(
    telegram_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Avatar shape not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "telegram_id": telegram_id}


class TelegramCustomization(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_animations: bool = True
    animation_style: str = "slide"
    animation_duration: int = 220
    send_effect: str = "scale"
    view_effect: str = "fade"
    reduce_motion: bool = False
    enable_reactions_effects: bool = True
    chat_list_style: str = "default"
    bubble_style: str = "rounded"
    accent_color: str = "#e4e4e7"
    compact_message_spacing: bool = False


@app.get("/api/telegram")
def get_telegram_customization(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    return {
        "customization": get_setting(
            db,
            "telegram.customization",
            TelegramCustomization().model_dump(),
        )
    }


@app.put("/api/telegram")
def put_telegram_customization(
    payload: TelegramCustomization,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    value = payload.model_dump(exclude_unset=True)
    set_setting(db, "telegram.customization", value)
    return {"ok": True, "customization": value}


class FontView(BaseModel):
    id: int
    name: str
    mime: str
    size: int
    created_at: str


MIME_BY_EXT = {".ttf": "font/ttf", ".otf": "font/otf"}


def font_view(font: Font) -> dict:
    return FontView(
        id=font.id,
        name=font.name,
        mime=font.mime,
        size=font.size,
        created_at=font.created_at.replace(tzinfo=None).isoformat(timespec="seconds"),
    ).model_dump()


@app.get("/api/fonts")
def list_fonts(user: User = Depends(require_user), db: Session = Depends(get_db)):
    active_font_id = get_setting(db, "active_font_id")
    rows = db.execute(select(Font).order_by(Font.created_at.desc())).scalars().all()
    return {
        "fonts": [font_view(row) for row in rows],
        "active_font_id": active_font_id,
    }


@app.post("/api/fonts")
async def upload_font(
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    name = Path(file.filename or "").name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Filename is required")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_FONT_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Only .ttf and .otf are allowed")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(data) > MAX_FONT_SIZE:
        raise HTTPException(status_code=422, detail="File too large (max 8 MB)")
    if not data.startswith(FONT_SIGNATURES):
        raise HTTPException(status_code=422, detail="File content is not a valid TTF/OTF font")
    font = Font(
        name=name,
        mime=MIME_BY_EXT[suffix],
        size=len(data),
        data=data,
        created_at=utcnow(),
    )
    db.add(font)
    db.commit()
    db.refresh(font)
    return {"ok": True, "font": font_view(font)}


def font_file_response(font: Font) -> Response:
    disposition = f"inline; filename*=UTF-8''{quote(font.name)}"
    return Response(
        content=font.data,
        media_type=font.mime,
        headers={"Content-Disposition": disposition},
    )


@app.get("/api/fonts/{font_id}/file")
def get_font_file(
    font_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    font = db.execute(select(Font).where(Font.id == font_id)).scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font not found")
    return font_file_response(font)


@app.delete("/api/fonts/active")
def deactivate_font(user: User = Depends(require_user), db: Session = Depends(get_db)):
    set_setting(db, "active_font_id", None)
    return {"ok": True, "active_font_id": None}


@app.delete("/api/fonts/{font_id}")
def delete_font(
    font_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    font = db.execute(select(Font).where(Font.id == font_id)).scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font not found")
    db.delete(font)
    if get_setting(db, "active_font_id") == font_id:
        set_setting(db, "active_font_id", None)
    db.commit()
    return {"ok": True, "id": font_id}


@app.post("/api/fonts/{font_id}/activate")
def activate_font(
    font_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    font = db.execute(select(Font).where(Font.id == font_id)).scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font not found")
    set_setting(db, "active_font_id", font_id)
    return {"ok": True, "active_font_id": font_id}


@app.get("/api/public/avatar-shape/{telegram_id}")
def public_avatar_shape(telegram_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(AvatarShape).where(AvatarShape.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        return {"telegram_id": telegram_id, "shape": "circle"}
    return json.loads(row.payload)


@app.get("/api/public/badge/{telegram_id}")
def public_badge(telegram_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(Badge).where(Badge.telegram_id == telegram_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Badge not found")
    return json.loads(row.payload)


@app.get("/api/public/badges")
def public_badges(db: Session = Depends(get_db)):
    rows = db.execute(select(Badge).order_by(Badge.updated_at.desc())).scalars().all()
    return {"badges": [json.loads(row.payload) for row in rows]}


def active_font(db: Session) -> Font | None:
    font_id = get_setting(db, "active_font_id")
    if font_id is None:
        return None
    return db.execute(select(Font).where(Font.id == font_id)).scalar_one_or_none()


@app.get("/api/public/font")
def public_font(db: Session = Depends(get_db)):
    font = active_font(db)
    return {"font": font_view(font) if font else None}


@app.get("/api/public/font/file")
def public_font_file(db: Session = Depends(get_db)):
    font = active_font(db)
    if font is None:
        raise HTTPException(status_code=404, detail="No active font")
    return font_file_response(font)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "visiongram-preference",
        "database": str(DB_PATH),
    }


if PANEL_DIR.is_dir():
    app.mount("/", StaticFiles(directory=PANEL_DIR, html=True), name="panel")
else:

    @app.get("/")
    def index():
        return {
            "ok": True,
            "service": "visiongram-preference",
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
    )