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
    arguments = parser.parse_args()
    username = input("Administrator username: ").strip()
    password = getpass.getpass("Administrator password: ")
    if not username or not password:
        print("Username and password are required.", file=sys.stderr)
        return 2
    settings = Settings.from_env()
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
