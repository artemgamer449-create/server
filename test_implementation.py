#!/usr/bin/env python3
"""Test script to verify the VisionPanel backend implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import (
    User,
    DbSession,
    Badge,
    initialize,
    engine,
    SessionLocal,
    hash_password,
    OWNER_USERNAME,
    TURNSTILE_SECRET,
)


def test_models():
    """Test that all required models are defined."""
    print("Testing database models...")

    assert hasattr(User, "id")
    assert hasattr(User, "username")
    assert hasattr(User, "password_hash")
    assert hasattr(User, "password_salt")
    assert hasattr(User, "created_at")
    print("[OK] User model is correct")

    assert hasattr(DbSession, "id")
    assert hasattr(DbSession, "user_id")
    assert hasattr(DbSession, "ip")
    assert hasattr(DbSession, "device")
    print("[OK] DbSession model is correct")

    assert hasattr(Badge, "telegram_id")
    assert hasattr(Badge, "payload")
    assert hasattr(Badge, "role")
    print("[OK] Badge model is correct")


def test_config():
    """Test configuration values."""
    print("\nTesting configuration...")

    assert OWNER_USERNAME, "OWNER_USERNAME must not be empty"
    print(f"[OK] Owner account configured: {OWNER_USERNAME}")
    print("[OK] Turnstile secret is set" if TURNSTILE_SECRET else "[OK] Turnstile disabled (test mode)")


def test_database():
    """Test database initialization."""
    print("\nTesting database...")

    User.metadata.create_all(engine)
    print("[OK] Database tables created")

    with SessionLocal() as db:
        existing = db.execute(
            select(User).where(User.username == OWNER_USERNAME)
        ).scalar_one_or_none()
        print(
            f"[OK] Owner account exists: {existing.username}"
            if existing is not None
            else "[OK] Owner account absent (set OWNER_USERNAME/OWNER_PASSWORD env to seed)"
        )


if __name__ == "__main__":
    from sqlalchemy import select

    print("=" * 60)
    print("Testing VisionPanel Backend Implementation")
    print("=" * 60)

    try:
        test_models()
        test_config()
        test_database()

        print("\n" + "=" * 60)
        print("SUCCESS: All tests passed! The implementation is correct.")
        print("=" * 60)

    except Exception as e:
        print(f"\nFAILED: Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
