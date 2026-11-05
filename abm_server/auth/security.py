import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def generate_api_key() -> tuple[str, str, str]:
    """Return public prefix, plaintext key, and digest."""
    public_prefix = f"abm_{secrets.token_hex(6)}"
    plaintext = f"{public_prefix}_{secrets.token_urlsafe(32)}"
    return public_prefix, plaintext, digest_token(plaintext)


def api_key_prefix(plaintext: str) -> str | None:
    parts = plaintext.split("_", 2)
    if len(parts) != 3 or parts[0] != "abm" or not parts[1]:
        return None
    return f"abm_{parts[1]}"


def mask_api_key(prefix: str) -> str:
    return f"{prefix}***" if prefix else ""
