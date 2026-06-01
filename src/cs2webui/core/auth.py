"""Local user authentication and hashed browser sessions."""

from dataclasses import dataclass
from collections import deque
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
import sqlite3
from threading import Lock
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    role: str


class LoginRateLimiter:
    """Bound repeated login failures without requiring an external proxy."""

    def __init__(
        self, *, limit: int = 5, window_seconds: int = 60, max_keys: int = 4096
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allows(self, key: str) -> bool:
        with self._lock:
            failures = self._failures.get(key)
            if not failures:
                return True
            self._discard_expired(failures)
            if not failures:
                self._failures.pop(key, None)
                return True
            return len(failures) < self._limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._discard_empty_keys()
            if key not in self._failures and len(self._failures) >= self._max_keys:
                self._failures.pop(next(iter(self._failures)))
            failures = self._failures.setdefault(key, deque())
            self._discard_expired(failures)
            failures.append(monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _discard_expired(self, failures: deque[float]) -> None:
        cutoff = monotonic() - self._window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()

    def _discard_empty_keys(self) -> None:
        for key, failures in list(self._failures.items()):
            self._discard_expired(failures)
            if not failures:
                self._failures.pop(key, None)


class AuthStore:
    """Authenticate local users and persist only session token hashes."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def login(self, username: str, password: str) -> tuple[str, User] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, role, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row:
                return None
            try:
                _hasher.verify(row["password_hash"], password)
            except VerifyMismatchError:
                return None
            token = token_urlsafe(48)
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (
                    self._digest(token),
                    row["id"],
                    (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                ),
            )
        return token, User(id=row["id"], username=row["username"], role=row["role"])

    def create_user(self, username: str, password: str, role: str) -> User:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
                """,
                (username, _hasher.hash(password), role),
            )
        return User(id=cursor.lastrowid, username=username, role=role)

    def users(self) -> list[User]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role FROM users ORDER BY username"
            ).fetchall()
        return [User(**dict(row)) for row in rows]

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.role
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (self._digest(token), now),
            ).fetchone()
        if not row:
            return None
        return User(id=row["id"], username=row["username"], role=row["role"])

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (self._digest(token),)
            )

    @staticmethod
    def _digest(token: str) -> str:
        return sha256(token.encode()).hexdigest()
