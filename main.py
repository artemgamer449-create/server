import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "badges.db")))
PANEL_DIR = Path(os.getenv("PANEL_DIR", str(ROOT / "panel")))
ADMIN_TOKEN = os.getenv("BADGE_ADMIN_TOKEN", "").strip()


@contextmanager
def database():
	DB_PATH.parent.mkdir(parents=True, exist_ok=True)
	connection = sqlite3.connect(DB_PATH)
	connection.row_factory = sqlite3.Row
	try:
		yield connection
		connection.commit()
	finally:
		connection.close()


def initialize():
	with database() as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS badges (
				telegram_id INTEGER PRIMARY KEY,
				username TEXT,
				display_name TEXT,
				role TEXT NOT NULL,
				payload TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)
			"""
		)
		connection.execute(
			"CREATE INDEX IF NOT EXISTS badges_username ON badges (username)"
		)


initialize()

app = FastAPI(title="VisionGram Badge API", version="1.0.0")
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=False,
	allow_methods=["*"],
	allow_headers=["*"],
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


def check_admin(token: str | None):
	if ADMIN_TOKEN and token != ADMIN_TOKEN:
		raise HTTPException(status_code=401, detail="Invalid admin token")


def normalize_badge(data: dict) -> dict:
	payload = dict(data)
	username = (payload.get("username") or "").strip().lstrip("@").lower()
	payload["username"] = username or None
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


def row_to_badge(row: sqlite3.Row) -> dict:
	return json.loads(row["payload"])


def require_badge(row: sqlite3.Row | None):
	if row is None:
		raise HTTPException(status_code=404, detail="Badge not found")


@app.get("/health")
def health():
	return {
		"ok": True,
		"service": "visiongram-badge-api",
		"database": str(DB_PATH),
	}


@app.get("/badges")
def list_badges(
	q: str | None = Query(default=None, max_length=64),
	limit: int = Query(default=200, ge=1, le=1000),
	x_admin_token: str | None = Header(default=None),
):
	check_admin(x_admin_token)
	with database() as connection:
		if q:
			query = q.strip().lstrip("@").lower()
			rows = connection.execute(
				"""
				SELECT payload FROM badges
				WHERE lower(coalesce(username, '')) = ?
					OR display_name LIKE ?
					OR CAST(telegram_id AS TEXT) LIKE ?
				ORDER BY updated_at DESC
				LIMIT ?
				""",
				(query, f"%{q.strip()}%", f"%{query}%", limit),
			).fetchall()
		else:
			rows = connection.execute(
				"SELECT payload FROM badges ORDER BY updated_at DESC LIMIT ?",
				(limit,),
			).fetchall()
	return {"badges": [row_to_badge(row) for row in rows]}


@app.get("/badges/{telegram_id}")
def get_badge(telegram_id: int):
	with database() as connection:
		row = connection.execute(
			"SELECT payload FROM badges WHERE telegram_id = ?",
			(telegram_id,),
		).fetchone()
	require_badge(row)
	return row_to_badge(row)


@app.post("/badges/set")
def set_badge(
	payload: BadgePayload,
	x_admin_token: str | None = Header(default=None),
):
	check_admin(x_admin_token)
	data = normalize_badge(payload.model_dump(exclude_none=True))
	telegram_id = int(data["telegram_id"])
	updated_at = datetime.now(timezone.utc).isoformat()
	with database() as connection:
		connection.execute(
			"""
			INSERT INTO badges (
				telegram_id,
				username,
				display_name,
				role,
				payload,
				updated_at
			) VALUES (?, ?, ?, ?, ?, ?)
			ON CONFLICT(telegram_id) DO UPDATE SET
				username = excluded.username,
				display_name = excluded.display_name,
				role = excluded.role,
				payload = excluded.payload,
				updated_at = excluded.updated_at
			""",
			(
				telegram_id,
				data.get("username"),
				data.get("display_name"),
				data["role"],
				json.dumps(data, ensure_ascii=False, separators=(",", ":")),
				updated_at,
			),
		)
	return {"ok": True, "badge": data, "updated_at": updated_at}


@app.delete("/badges/{telegram_id}")
def delete_badge(
	telegram_id: int,
	x_admin_token: str | None = Header(default=None),
):
	check_admin(x_admin_token)
	with database() as connection:
		cursor = connection.execute(
			"DELETE FROM badges WHERE telegram_id = ?",
			(telegram_id,),
		)
	if cursor.rowcount == 0:
		raise HTTPException(status_code=404, detail="Badge not found")
	return {"ok": True, "telegram_id": telegram_id}


if PANEL_DIR.is_dir():
	app.mount("/", StaticFiles(directory=PANEL_DIR, html=True), name="panel")
else:

	@app.get("/")
	def index():
		return {
			"ok": True,
			"service": "visiongram-badge-api",
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
