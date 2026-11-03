"""The factory's Ed25519 signing keys (spec 2.2 "Keys", 3 Security).

Files, in the key folder (`keys_dir()`):

    signing.key     the private key, PEM (PKCS#8, unencrypted). Readable only by the seller's own account:
                    mode 0600 on Linux/macOS, a user-only ACL (icacls) on Windows. `.gitignore` blocks *.key.
    public.pem      the public key, PEM (SubjectPublicKeyInfo); always re-derived from the private key on load.
    backup.json     where and when the private key was last copied (`copy_backup`), for the backup banner.

The key folder is `%APPDATA%\\<Product>Factory\\keys` on Windows and `$XDG_CONFIG_HOME/<Product>Factory/keys`
(default ~/.config) elsewhere; `<PRODUCT>_FACTORY_KEYS` or a `folder=` argument overrides it (tests use tmp).

The private key never goes into the repo, a package or a Shipments folder: every write of key material goes
through `assert_not_inside`, with the repo always forbidden and the caller adding the Shipments folder. The key's
bytes are never logged, and never part of a code (codes carry only the payload and the signature).

The hub trusts the public keys in hub/simtelemetry/licence_pubkey.py; `write_public_key_py(repo_root, keys)`
(the app's "Set up keys" step) keeps every key already there and adds the new one, so codes from an earlier key
still verify after a key change.

API (errors are KeysError, a plain-English message for the factory window):
- `keys_dir(folder=None)`, `has_keys(folder=None)`
- `create_keys(folder=None, forbidden=()) -> Keys`     refuses to replace existing keys
- `load_private(folder=None) -> Keys`
- `public_key_py(public, existing=())`, `read_trusted_keys(path)`, `write_public_key_py(repo_root, keys)`
- `backup_state(folder=None) -> BackupState | None`, `backed_up(folder=None)`, `copy_backup(dest, folder, forbidden)`
- `assert_not_inside(path, forbidden_roots)`, `is_trusted(keys, trusted=None)`
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption, PrivateFormat, PublicFormat,
                                                          load_pem_private_key, load_pem_public_key)

from simtelemetry import brand, licence_pubkey
from simtelemetry.provision import write_atomic

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTORY_DIR_NAME = f"{brand.EXE_NAME}Factory"                    # PitwallFactory
KEYS_ENV = f"{brand.EXE_NAME.upper()}_FACTORY_KEYS"               # PITWALL_FACTORY_KEYS
PRIVATE_FILE = "signing.key"
PUBLIC_FILE = "public.pem"
STATE_FILE = "backup.json"
PUBKEY_MODULE = Path("hub") / "simtelemetry" / "licence_pubkey.py"
MAX_KEY_FILE = 4096                                               # a PEM Ed25519 key is about 120 bytes

NO_KEYS = "There's no signing key on this PC yet. Use Set up keys first."
DAMAGED = ("The signing key file is damaged. Copy it back from your backup (for example your USB drive) "
           "into {folder}.")
ALREADY = "There are signing keys in {folder} already. They were not replaced."
NO_ACCESS = ("This Windows account can't open the signing key in {folder}. Sign in with the account that made "
             "the keys, or copy the key back from your backup.")
ONLY_PUBLIC = ("There's a {public} in {folder} but no {private}. If you have a backup, copy {private} back into that "
               "folder. If the signing key is lost, delete {public} there and use Set up keys again.")
NOT_PRIVATE = ("The signing key couldn't be made private to your Windows account, so no key was made. "
               "Try again; if it keeps happening, restart the PC.")


class KeysError(ValueError):
    """Something the seller has to fix; the message is plain English for the factory window."""


@dataclass(frozen=True)
class Keys:
    folder: Path
    private: Ed25519PrivateKey = field(repr=False)
    public: bytes                                                 # raw 32-byte public key, as licence_pubkey holds

    @property
    def fingerprint(self) -> str:
        """A short id of the key pair for the window and backup.json, e.g. "3f2a-91c0-7be4-0d18"."""
        return fingerprint(self.public)


@dataclass(frozen=True)
class BackupState:
    backed_up_to: str
    date: dt.date
    fingerprint: str


def fingerprint(public: bytes) -> str:
    h = hashlib.sha256(public).hexdigest()[:16]
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


# --- where the keys live -------------------------------------------------------------------------

def default_dir(env: dict[str, str] | None = None, windows: bool | None = None) -> Path:
    env = os.environ if env is None else env
    windows = _is_windows() if windows is None else windows
    if env.get(KEYS_ENV):
        return Path(env[KEYS_ENV])
    if windows:
        base = Path(env["APPDATA"]) if env.get("APPDATA") else Path.home() / "AppData" / "Roaming"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / FACTORY_DIR_NAME / "keys"


def keys_dir(folder: Path | None = None) -> Path:
    return Path(folder) if folder is not None else default_dir()


def has_keys(folder: Path | None = None) -> bool:
    return (keys_dir(folder) / PRIVATE_FILE).exists()


# --- the guard -----------------------------------------------------------------------------------

def _norm(path: Path) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def is_inside(path: Path, root: Path) -> bool:
    """True when `path` is `root` or anywhere under it (symlinks resolved; case-insensitive on Windows)."""
    p, r = _norm(path), _norm(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:                                            # different drives on Windows
        return False


def assert_not_inside(path: Path, forbidden_roots: Iterable[Path | None]) -> None:
    """Refuse to write key material into the repo, a Shipments folder or any other forbidden folder."""
    for root in forbidden_roots:
        if root is not None and is_inside(path, root):
            raise KeysError(f"The signing key can't be kept in {root}, because everything there is shared or "
                            "shipped. Choose another folder, such as a USB drive.")


def _forbidden(extra: Iterable[Path | None]) -> list[Path]:
    return [REPO_ROOT, *(Path(r) for r in extra if r is not None)]


# --- making the private key file private ---------------------------------------------------------

def _is_windows() -> bool:
    return os.name == "nt"


_run: Callable[..., subprocess.CompletedProcess] = subprocess.run     # tests replace this; never runs on Linux


def windows_user(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    user = env.get("USERNAME", "")
    if not user:
        raise KeysError(NOT_PRIVATE)
    return f"{env['USERDOMAIN']}\\{user}" if env.get("USERDOMAIN") else user


def icacls_exe(env: dict[str, str] | None = None) -> str:
    """The real icacls.exe in System32 (not whatever "icacls" is first on PATH)."""
    env = os.environ if env is None else env
    root = env.get("SystemRoot") or env.get("SYSTEMROOT")
    return str(Path(root) / "System32" / "icacls.exe") if root else "icacls"


def icacls_command(path: Path, user: str, folder: bool = False) -> list[str]:
    """Remove inherited rights and give only `user` full control (a folder passes it on to new files)."""
    grant = f"{user}:(OI)(CI)F" if folder else f"{user}:F"
    return [icacls_exe(), str(path), "/inheritance:r", "/grant:r", grant]


def _protect(path: Path, folder: bool = False) -> None:
    """User-only access: 0600/0700 on POSIX; icacls on Windows (only there: never on the developer's Linux)."""
    if _is_windows():
        cmd = icacls_command(path, windows_user(), folder)
        try:
            # Output is not read: icacls prints in the console code page, and decoding it could fail on
            # a non-English path. No console window flashes up from the windowed factory app.
            done = _run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            raise KeysError(NOT_PRIVATE) from None
        if done.returncode != 0:
            raise KeysError(NOT_PRIVATE)
    else:
        os.chmod(path, 0o700 if folder else 0o600)


def _write_new(path: Path, data: bytes, private: bool) -> None:
    """Write a file that must not exist yet. The temporary file is made private before any key byte goes in,
    and the final name is taken with a hard link, which never replaces an existing file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        os.close(fd)
        if private:
            _protect(tmp)
        with open(tmp, "r+b") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            _link_new(tmp, path, data)
        except FileExistsError:
            raise KeysError(ALREADY.format(folder=path.parent)) from None
    finally:
        tmp.unlink(missing_ok=True)


def _link_new(tmp: Path, path: Path, data: bytes) -> None:
    """Give `tmp` the name `path` without ever replacing a file there (FileExistsError if one is).
    A hard link first; on a drive without hard links, a rename on Windows (which never replaces a file) or an
    exclusive create elsewhere."""
    try:
        os.link(tmp, path)
        return
    except FileExistsError:
        raise
    except (OSError, NotImplementedError):
        if path.exists():
            raise FileExistsError(path) from None
    if _is_windows():
        os.rename(tmp, path)                                       # keeps tmp's private ACL
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _write_private_copy(path: Path, data: bytes) -> None:
    """Like write_atomic, but the temporary file is 0600 from the start (POSIX; on Windows the folder's rights)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            if not _is_windows():
                os.chmod(tmp, 0o600)                               # an old tmp may have had other rights
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


# --- create and load -----------------------------------------------------------------------------

def _pem_private(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())


def _raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def create_keys(folder: Path | None = None, forbidden: Iterable[Path | None] = ()) -> Keys:
    """Make a new key pair in the key folder. Refuses when keys (or either key file) are there already, and when
    the folder is inside the repo or a forbidden folder (pass the Shipments folder)."""
    folder = keys_dir(folder)
    assert_not_inside(folder, _forbidden(forbidden))
    if (folder / PRIVATE_FILE).exists():
        raise KeysError(ALREADY.format(folder=folder))
    if (folder / PUBLIC_FILE).exists():
        raise KeysError(ONLY_PUBLIC.format(folder=folder, public=PUBLIC_FILE, private=PRIVATE_FILE))
    try:
        new_folder = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if new_folder:
            _protect(folder, folder=True)
        key = Ed25519PrivateKey.generate()
        _write_new(folder / PRIVATE_FILE, _pem_private(key), private=True)
        public = _raw_public(key)
        write_atomic(folder / PUBLIC_FILE,
                     key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
        (folder / STATE_FILE).unlink(missing_ok=True)             # an old backup record is for another key
    except OSError:
        raise KeysError(f"The signing keys couldn't be saved in {folder}. Check the folder and try again.") from None
    log.info("Signing keys made in %s (key %s)", folder, fingerprint(public))
    return Keys(folder=folder, private=key, public=public)


def load_private(folder: Path | None = None) -> Keys:
    folder = keys_dir(folder)
    path = folder / PRIVATE_FILE
    if not path.exists():
        raise KeysError(NO_KEYS)
    damaged = KeysError(DAMAGED.format(folder=folder))
    try:
        if path.stat().st_size > MAX_KEY_FILE:
            raise damaged
        data = path.read_bytes()
    except PermissionError:
        raise KeysError(NO_ACCESS.format(folder=folder)) from None
    except OSError:
        raise damaged from None
    try:
        key = load_pem_private_key(data, password=None)
    except (ValueError, TypeError):
        raise damaged from None
    if not isinstance(key, Ed25519PrivateKey):
        raise damaged
    public = _raw_public(key)
    pub_path = folder / PUBLIC_FILE
    if pub_path.exists():                                         # a public file from another key = a mixed-up copy
        try:
            stored = load_pem_public_key(pub_path.read_bytes())
            ok = isinstance(stored, Ed25519PublicKey) and stored.public_bytes(Encoding.Raw, PublicFormat.Raw) == public
        except (OSError, ValueError, TypeError):
            ok = False
        if not ok:
            raise KeysError(f"The two key files in {folder} don't belong together. Copy both back from your backup.")
    return Keys(folder=folder, private=key, public=public)


# --- the hub's public key module -----------------------------------------------------------------

def _valid_public(raw: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(raw)
        return len(raw) == 32
    except (ValueError, TypeError):
        return False


def read_trusted_keys(path: Path) -> tuple[bytes, ...]:
    """The keys in an existing licence_pubkey.py, read without running it. Refuses anything it can't read
    rather than dropping keys (old cafes' codes must keep verifying)."""
    bad = KeysError(f"{path} couldn't be read, so it wasn't changed. Restore it from the repo and try again.")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError, RecursionError, MemoryError):
        raise bad from None
    found: list[bytes] | None = None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if getattr(node, "value", None) is None or not names & {"TRUSTED_KEYS", "TRUSTED_KEYS_HEX"}:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
            if "TRUSTED_KEYS" in names:                           # the generated form: built from the hex below
                continue
            raise bad from None
        if not isinstance(value, tuple):
            raise bad
        keys = []
        for item in value:
            if isinstance(item, str):
                try:
                    item = bytes.fromhex(item)
                except ValueError:
                    raise bad from None
            if not isinstance(item, bytes) or not _valid_public(item):
                raise bad
            keys.append(item)
        found = [*(found or []), *keys]                           # every assignment's keys: never drop one
    if found is None:
        raise bad
    return tuple(dict.fromkeys(found))


def public_key_py(public: bytes, existing: Iterable[bytes] = ()) -> str:
    """The full licence_pubkey.py: every key in `existing` (in order), then `public` if it isn't there yet."""
    keys = list(dict.fromkeys([*existing, public]))
    for k in keys:
        if not _valid_public(k):
            raise KeysError("A public key isn't valid, so the hub's key file wasn't changed.")
    lines = "".join(f'    "{k.hex()}",   # {fingerprint(k)}\n' for k in keys)
    return (
        '"""The public keys the hub trusts for licence codes (raw 32-byte Ed25519 public keys).\n'
        "\n"
        "Generated by the factory's \"Set up keys\" step (factory/keys.py); commit it and rebuild the program.\n"
        "Every key ever used stays here, so codes made with an earlier key still verify after a key change.\n"
        "A public key can only check codes, never make them; the private key never enters this repo.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "TRUSTED_KEYS_HEX: tuple[str, ...] = (\n"
        f"{lines}"
        ")\n"
        "\n"
        "TRUSTED_KEYS: tuple[bytes, ...] = tuple(bytes.fromhex(k) for k in TRUSTED_KEYS_HEX)\n"
    )


def write_public_key_py(repo_root: Path, keys: Keys) -> Path:
    """Add the key pair's public key to <repo>/hub/simtelemetry/licence_pubkey.py, keeping the keys there."""
    path = Path(repo_root) / PUBKEY_MODULE
    if not path.parent.is_dir():
        raise KeysError(f"{Path(repo_root)} isn't the program's source folder, so the hub's key file wasn't "
                        "written. Choose the source folder and try again.")
    existing = read_trusted_keys(path) if path.exists() else ()
    text = public_key_py(keys.public, existing)
    count = len(dict.fromkeys([*existing, keys.public]))
    try:
        write_atomic(path, text.encode("utf-8"))
    except OSError:
        raise KeysError(f"{path} couldn't be written. Check the repo folder and try again.") from None
    log.info("Hub key file updated with key %s (%d key(s) trusted)", keys.fingerprint, count)
    return path


def is_trusted(keys: Keys, trusted: Iterable[bytes] | None = None) -> bool:
    """True when this build of the hub (licence_pubkey.TRUSTED_KEYS) verifies codes signed with these keys."""
    return keys.public in tuple(licence_pubkey.TRUSTED_KEYS if trusted is None else trusted)


# --- backup --------------------------------------------------------------------------------------

def backup_state(folder: Path | None = None) -> BackupState | None:
    """The last confirmed backup of the current key, or None (show the "Back up your signing key" banner).
    A record for another key (or a damaged record) counts as no backup."""
    folder = keys_dir(folder)
    try:
        data = json.loads((folder / STATE_FILE).read_text(encoding="utf-8"))
        state = BackupState(backed_up_to=str(data["backed_up_to"]), date=dt.date.fromisoformat(data["date"]),
                            fingerprint=str(data["fingerprint"]))
        current = load_private(folder)
    except (OSError, ValueError, KeyError, TypeError, KeysError):
        return None
    return state if state.fingerprint == current.fingerprint else None


def backed_up(folder: Path | None = None) -> bool:
    return backup_state(folder) is not None


def copy_backup(dest: Path, folder: Path | None = None, forbidden: Iterable[Path | None] = (),
                today: dt.date | None = None) -> BackupState:
    """Copy both key files into `dest` (for example a USB drive), check the copy byte for byte, then record it.

    Refuses a `dest` inside the repo, the key folder itself or a forbidden folder (pass the Shipments folder), and a
    `dest` that already holds a different signing key (it is never overwritten).
    """
    keys = load_private(folder)
    dest = Path(dest)
    if not dest.is_dir():
        raise KeysError(f"The folder {dest} isn't there. Plug in the drive or choose another folder.")
    assert_not_inside(dest, _forbidden(forbidden))
    if is_inside(dest, keys.folder):
        raise KeysError("Choose a folder outside the key folder, such as a USB drive, so the copy is kept apart.")
    files = {}
    try:
        for name in (PRIVATE_FILE, PUBLIC_FILE):
            src = keys.folder / name
            files[name] = src.read_bytes() if src.exists() else None
    except OSError:
        raise KeysError(DAMAGED.format(folder=keys.folder)) from None
    if files[PUBLIC_FILE] is None:
        files[PUBLIC_FILE] = keys.private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    target = dest / PRIVATE_FILE
    if target.exists():
        try:
            same = target.read_bytes() == files[PRIVATE_FILE]
        except OSError:
            same = False
        if not same:
            raise KeysError(f"There's a different signing key in {dest} already, and it was kept. "
                            "Choose another folder for this copy.")
    failed = KeysError(f"The key couldn't be copied to {dest} correctly. Check the drive and try again.")
    try:
        for name, data in files.items():
            if name == PRIVATE_FILE:
                _write_private_copy(dest / name, data)
            else:
                write_atomic(dest / name, data)
        copied = all((dest / name).read_bytes() == data for name, data in files.items())
    except OSError:
        raise failed from None
    if not copied:
        raise failed
    state = BackupState(backed_up_to=str(dest), date=today or dt.date.today(), fingerprint=keys.fingerprint)
    try:
        write_atomic(keys.folder / STATE_FILE, json.dumps(
            {"backed_up_to": state.backed_up_to, "date": state.date.isoformat(), "fingerprint": state.fingerprint},
            ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError:
        raise KeysError("The key was copied, but the factory couldn't note it down. Try again.") from None
    log.info("Signing key %s copied to %s", keys.fingerprint, dest)
    return state
