"""Small encrypted secret store for instance credentials."""

from os import chmod
from pathlib import Path

from cryptography.fernet import Fernet


class SecretCipher:
    """Encrypt secrets at rest with a panel-local key file."""

    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._key_path.exists():
            self._key_path.write_bytes(Fernet.generate_key())
            chmod(self._key_path, 0o600)
        self._fernet = Fernet(self._key_path.read_bytes())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()
