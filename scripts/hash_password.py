#!/usr/bin/env python3
"""Generate a bcrypt hash for use in ADMIN_PASSWORD_HASH env var.

Usage:
    python scripts/hash_password.py <password>
    python scripts/hash_password.py   # prompts for password
"""

import sys
from getpass import getpass

import bcrypt

if __name__ == "__main__":
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass("Enter password to hash: ")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print(f"\nADMIN_PASSWORD_HASH={hashed}")
    print("\nAdd this to your .env file.")
