"""
AetherCloud-L — Admin: Create User
Run from the project root: python scripts/create_user.py
"""

import json
import getpass
import sys
from pathlib import Path

try:
    import bcrypt
except ImportError:
    print("bcrypt not installed. Run: pip install bcrypt")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = PROJECT_ROOT / "config" / "credentials.json"


def load_credentials() -> dict:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_credentials(creds: dict) -> None:
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(creds, f, indent=2)


def create_user_dirs(username: str) -> None:
    base = PROJECT_ROOT / "data" / "users" / username
    dirs = [
        base,
        base / "tasks" / "history",
        base / "tasks" / "qopc",
        base / "agents" / "tone_profiles",
        PROJECT_ROOT / "vault_data" / username,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    profile = base / "profile.json"
    if not profile.exists():
        with open(profile, "w") as f:
            json.dump({"username": username, "created": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)


def main():
    print("=== AetherCloud-L User Creation ===\n")

    creds = load_credentials()

    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    if username in creds:
        print(f"User '{username}' already exists.")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    if len(password) < 6:
        print("Password must be at least 6 characters.")
        sys.exit(1)

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode(), salt).decode()
    creds[username] = {"password_hash": hashed}

    save_credentials(creds)
    create_user_dirs(username)

    print(f"\nUser '{username}' created successfully.")
    print(f"Credentials saved to: {CREDENTIALS_FILE}")
    print("\nLog in via the AetherCloud-L app to get a session token.")


if __name__ == "__main__":
    main()
