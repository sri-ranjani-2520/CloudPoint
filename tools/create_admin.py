"""Create an administrator credential record for future local auth work."""

import getpass
import hashlib
import os
import sys
import argparse

from cloudpoint.config import Settings
from cloudpoint.repository import DuplicateAdministratorError, Repository
from cloudpoint.dynamodb_repository import DynamoDBRepository


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${derived.hex()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an administrator credential in the selected store.")
    parser.add_argument("--dynamodb", action="store_true", help="Use the configured existing DynamoDB table")
    parser.add_argument(
        "--reset-local-demo-admin",
        action="store_true",
        help="Explicitly create or reset the local SQLite demo admin; never use this for production",
    )
    arguments = parser.parse_args()
    if arguments.dynamodb and arguments.reset_local_demo_admin:
        parser.error("--reset-local-demo-admin is SQLite-only and cannot be combined with --dynamodb")
    if arguments.reset_local_demo_admin:
        print("WARNING: LOCAL DEVELOPMENT ONLY. The requested demo password is weak and must never be used in production.")
        if input("Type RESET LOCAL DEMO ADMIN to continue: ") != "RESET LOCAL DEMO ADMIN":
            print("Reset cancelled.", file=sys.stderr)
            return 2
        username = input("Administrator username [admin]: ").strip() or "admin"
        if username.casefold() != "admin":
            print("This local demo reset is restricted to the admin username.", file=sys.stderr)
            return 2
        username = "admin"
        password = getpass.getpass("Temporary local demo password: ")
        if password != getpass.getpass("Confirm temporary local demo password: "):
            print("Passwords did not match.", file=sys.stderr)
            return 2
    else:
        username = input("Administrator username: ").strip()
        password = getpass.getpass("Administrator password: ")
    if not username or not password:
        print("Username and password are required.", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    if arguments.reset_local_demo_admin:
        repository = Repository(settings.database_path)
        repository.initialize()
        password_hash = hash_password(password)
        if repository.reset_administrator_password(username, password_hash):
            print("Local demo administrator password reset; existing sessions revoked.")
        else:
            repository.add_administrator(username, password_hash)
            print("Local demo administrator credential created.")
        return 0
    if arguments.dynamodb:
        repository = DynamoDBRepository.from_settings(settings)
    else:
        repository = Repository(settings.database_path)
        repository.initialize()
    try:
        repository.add_administrator(username, hash_password(password))
    except DuplicateAdministratorError:
        print("That administrator username already exists.", file=sys.stderr)
        return 2
    print("Administrator credential record created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
