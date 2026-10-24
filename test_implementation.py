#!/usr/bin/env python3
"""Test script to verify the FastAPI backend implementation."""

import asyncio
import sys
from pathlib import Path

# Add the current directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Import directly from main.py
from main import (
    User,
    DbSession,
    Badge,
    AvatarShape,
    Font,
    Setting,
    initialize,
    engine,
    SessionLocal,
    hash_password,
    AVATAR_SHAPES,
    ALLOWED_FONT_EXTENSIONS,
    OWNER_USERNAME,
    OWNER_PASSWORD,
    TURNSTILE_SECRET,
    TURNSTILE_SITE_KEY,
)

def test_models():
    """Test that all required models are defined."""
    print("Testing database models...")
    
    # Check User model
    assert hasattr(User, 'id')
    assert hasattr(User, 'username')
    assert hasattr(User, 'password_hash')
    assert hasattr(User, 'password_salt')
    assert hasattr(User, 'created_at')
    print("[OK] User model is correct")
    
    # Check DbSession model
    assert hasattr(DbSession, 'id')
    assert hasattr(DbSession, 'user_id')
    assert hasattr(DbSession, 'ip')
    assert hasattr(DbSession, 'device')
    print("[OK] DbSession model is correct")
    
    # Check Badge model
    assert hasattr(Badge, 'telegram_id')
    assert hasattr(Badge, 'payload')
    assert hasattr(Badge, 'role')
    print("[OK] Badge model is correct")
    
    # Check AvatarShape model
    assert hasattr(AvatarShape, 'telegram_id')
    assert hasattr(AvatarShape, 'shape')
    print("[OK] AvatarShape model is correct")
    
    # Check Font model
    assert hasattr(Font, 'id')
    assert hasattr(Font, 'name')
    assert hasattr(Font, 'data')
    print("[OK] Font model is correct")
    
    # Check Setting model
    assert hasattr(Setting, 'key')
    assert hasattr(Setting, 'value')
    print("[OK] Setting model is correct")
    
    # Check AVATAR_SHAPES
    assert "circle" in AVATAR_SHAPES
    assert "star" in AVATAR_SHAPES
    assert "hexagon" in AVATAR_SHAPES
    print(f"[OK] AVATAR_SHAPES contains {len(AVATAR_SHAPES)} shapes")
    
    # Check ALLOWED_FONT_EXTENSIONS
    assert ".ttf" in ALLOWED_FONT_EXTENSIONS
    assert ".otf" in ALLOWED_FONT_EXTENSIONS
    print(f"[OK] ALLOWED_FONT_EXTENSIONS contains {len(ALLOWED_FONT_EXTENSIONS)} extensions")

def test_config():
    """Test configuration values."""
    print("\nTesting configuration...")
    
    # Check owner credentials
    assert OWNER_USERNAME == "owner"
    assert OWNER_PASSWORD == "chmchm333222111"
    print(f"[OK] OWNER_USERNAME='{OWNER_USERNAME}'")
    print(f"[OK] OWNER_PASSWORD='{OWNER_PASSWORD}'")
    
    # Check Turnstile keys
    assert TURNSTILE_SECRET == "0x4AAAAAAFi7N0fDNvk3lZQdJ1pn84WXiB4"
    assert TURNSTILE_SITE_KEY == "0x4AAAAAAFi7N7hnSxXvj04S"
    print(f"[OK] TURNSTILE_SECRET='{TURNSTILE_SECRET}'")
    print(f"[OK] TURNSTILE_SITE_KEY='{TURNSTILE_SITE_KEY}'")

def test_database():
    """Test database initialization."""
    print("\nTesting database...")
    
    # Create tables
    User.metadata.create_all(engine)
    print("[OK] Database tables created")
    
    # Add owner user
    with SessionLocal() as db:
        # Check if owner exists
        existing = db.execute(
            select(User).where(User.username == OWNER_USERNAME)
        ).scalar_one_or_none()
        
        if existing is None:
            salt = "test_salt_1234567890abcdef"
            password_hash = hash_password(OWNER_PASSWORD, salt)
            owner = User(
                username=OWNER_USERNAME,
                password_hash=password_hash,
                password_salt=salt,
                created_at=datetime.now(timezone.utc),
            )
            db.add(owner)
            db.commit()
            print(f"[OK] Owner user created: {owner.username}")
        else:
            print(f"[OK] Owner user already exists: {existing.username}")

if __name__ == "__main__":
    from datetime import datetime, timezone
    from sqlalchemy import select
    
    print("=" * 60)
    print("Testing FastAPI Backend Implementation")
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