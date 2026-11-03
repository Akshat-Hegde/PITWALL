import base64
import datetime as dt
import importlib.util
import logging
import os
import subprocess

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from factory import keys as K
from factory.keys import KeysError
from simtelemetry import brand, licence, licence_pubkey

DAY = dt.date(2026, 11, 3)


@pytest.fixture
def kdir(tmp_path):
    return tmp_path / "home" / "keys"


@pytest.fixture
def made(kdir):
    return K.create_keys(kdir)


def secret_texts(keys: K.Keys) -> list[str]:
    """Every way the private key's bytes could show up in text."""
    raw = keys.private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pem = (keys.folder / K.PRIVATE_FILE).read_text()
    body = "".join(pem.splitlines()[1:-1])
    return [raw.hex(), base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode().rstrip("="), body]


def load_module(path):
    spec = importlib.util.spec_from_file_location("pubkey_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- folder --------------------------------------------------------------------------------------

def test_default_folder():
    name = f"{brand.EXE_NAME}Factory"
    assert K.FACTORY_DIR_NAME == name
    # The profile folder, never %APPDATA%: Microsoft Store Python redirects AppData writes, so icacls would miss it.
    win = K.default_dir({"USERPROFILE": r"C:\Users\ravi", "APPDATA": r"C:\Users\ravi\AppData\Roaming"}, windows=True)
    assert win.parts[-2:] == (name, "keys") and str(win).startswith(r"C:\Users\ravi")
    assert "AppData" not in str(win)
    assert K.default_dir({"XDG_CONFIG_HOME": "/x/cfg"}, windows=False).as_posix() == f"/x/cfg/{name}/keys"
    assert K.default_dir({}, windows=False) == K.Path.home() / ".config" / name / "keys"
    assert K.default_dir({K.KEYS_ENV: "/tmp/k", "APPDATA": "/a"}, windows=True) == K.Path("/tmp/k")


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(K.KEYS_ENV, str(tmp_path / "k"))
    assert not K.has_keys()
    keys = K.create_keys()
    assert keys.folder == tmp_path / "k" and K.has_keys() and K.load_private().public == keys.public


# --- create and load -----------------------------------------------------------------------------

def test_create_and_load(kdir, made):
    assert len(made.public) == 32 and K.has_keys(kdir)
    again = K.load_private(kdir)
    assert again.public == made.public and again.fingerprint == made.fingerprint
    assert (kdir / K.PRIVATE_FILE).read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    assert not list(kdir.glob("*.tmp"))
    assert "Ed25519PrivateKey" not in repr(made)


def test_create_refuses_to_overwrite(kdir, made):
    before = (kdir / K.PRIVATE_FILE).read_bytes()
    with pytest.raises(KeysError, match="already. They were not replaced"):
        K.create_keys(kdir)
    assert (kdir / K.PRIVATE_FILE).read_bytes() == before
    (kdir / K.PRIVATE_FILE).unlink()                     # a public key alone is still refused
    with pytest.raises(KeysError, match="no signing.key"):
        K.create_keys(kdir)


def test_write_new_never_replaces_a_file_that_appears(tmp_path):
    target = tmp_path / "signing.key"
    target.write_bytes(b"old")
    with pytest.raises(KeysError):
        K._write_new(target, b"new", private=False)
    assert target.read_bytes() == b"old" and not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_posix_permissions(kdir, made):
    assert (kdir / K.PRIVATE_FILE).stat().st_mode & 0o777 == 0o600
    assert kdir.stat().st_mode & 0o777 == 0o700


def test_load_plain_errors(kdir):
    with pytest.raises(KeysError, match="Set up keys first"):
        K.load_private(kdir)
    kdir.mkdir(parents=True)
    (kdir / K.PRIVATE_FILE).write_text("not a key")
    with pytest.raises(KeysError, match="damaged"):
        K.load_private(kdir)
    (kdir / K.PRIVATE_FILE).write_bytes(b"x" * 10_000)
    with pytest.raises(KeysError, match="damaged"):
        K.load_private(kdir)


def test_load_refuses_mixed_up_key_files(tmp_path):
    a, b = K.create_keys(tmp_path / "a"), K.create_keys(tmp_path / "b")
    (a.folder / K.PUBLIC_FILE).write_bytes((b.folder / K.PUBLIC_FILE).read_bytes())
    with pytest.raises(KeysError, match="don't belong together"):
        K.load_private(a.folder)
    (a.folder / K.PUBLIC_FILE).unlink()                  # the public file is optional: derived from the private one
    assert K.load_private(a.folder).public == a.public


def test_keys_never_made_inside_the_repo_or_shipments(tmp_path):
    with pytest.raises(KeysError, match="can't be kept in"):
        K.create_keys(K.REPO_ROOT / "factory" / "keys-test-should-not-exist")
    assert not (K.REPO_ROOT / "factory" / "keys-test-should-not-exist").exists()
    ship = tmp_path / "Shipments"
    with pytest.raises(KeysError, match="can't be kept in"):
        K.create_keys(ship / "keys", forbidden=[ship])
    assert not (ship / "keys").exists()


def test_assert_not_inside(tmp_path):
    root = tmp_path / "Shipments"
    for bad in (root, root / "a" / "b", tmp_path / "x" / ".." / "Shipments" / "c"):
        with pytest.raises(KeysError):
            K.assert_not_inside(bad, [root])
    K.assert_not_inside(tmp_path / "Shipments2", [root])          # a sibling with a longer name is fine
    K.assert_not_inside(tmp_path / "usb", [None, root])
    link = tmp_path / "usb-link"
    root.mkdir()
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(root), str(link))              # symlinks need a privilege on Windows
    else:
        link.symlink_to(root, target_is_directory=True)
    with pytest.raises(KeysError):                                  # a link into Shipments is still Shipments
        K.assert_not_inside(link / "k", [root])


# --- Windows ACL (never run here) ------------------------------------------------------------------

def test_icacls_command(monkeypatch):
    for name in ("SystemRoot", "SYSTEMROOT"):
        monkeypatch.delenv(name, raising=False)           # plain "icacls" (Windows sets SystemRoot)
    p = K.Path(r"C:\Users\ravi\AppData\Roaming\F\keys\signing.key")
    assert K.icacls_command(p, r"CAFE-PC\ravi") == ["icacls", str(p), "/inheritance:r", "/grant:r", r"CAFE-PC\ravi:F"]
    assert K.icacls_command(p.parent, "ravi", folder=True)[-1] == "ravi:(OI)(CI)F"
    assert K.windows_user({"USERNAME": "ravi", "USERDOMAIN": "CAFE-PC"}) == r"CAFE-PC\ravi"
    assert K.windows_user({"USERNAME": "ravi"}) == "ravi"
    with pytest.raises(KeysError):
        K.windows_user({})


def windows_mocked(monkeypatch, returncode=0):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, "", "")

    monkeypatch.setattr(K, "_is_windows", lambda: True)
    monkeypatch.setattr(K, "_run", run)
    monkeypatch.setenv("USERNAME", "ravi")
    monkeypatch.setenv("USERDOMAIN", "CAFE-PC")
    for name in ("SystemRoot", "SYSTEMROOT"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_windows_path_runs_icacls_on_the_folder_and_the_key_before_the_key_is_written(kdir, monkeypatch):
    seen = []
    calls = windows_mocked(monkeypatch)
    real = K._run

    def run(cmd, **kw):
        target = K.Path(cmd[1])
        seen.append(target.read_bytes() if target.is_file() else None)
        return real(cmd, **kw)

    monkeypatch.setattr(K, "_run", run)
    K.create_keys(kdir)
    assert calls == [["icacls", str(kdir), "/inheritance:r", "/grant:r", r"CAFE-PC\ravi:(OI)(CI)F"],
                     ["icacls", str(kdir / (K.PRIVATE_FILE + ".tmp")), "/inheritance:r", "/grant:r", r"CAFE-PC\ravi:F"]]
    assert seen == [None, b""]                       # the file was still empty when it was made private


def test_windows_icacls_failure_makes_no_key(kdir, monkeypatch):
    windows_mocked(monkeypatch, returncode=5)
    with pytest.raises(KeysError, match="couldn't be made private"):
        K.create_keys(kdir)
    assert not (kdir / K.PRIVATE_FILE).exists() and not list(kdir.glob("*.tmp"))


def test_icacls_never_runs_off_windows(kdir, monkeypatch):
    monkeypatch.setattr(K, "_run", lambda *a, **k: pytest.fail("icacls ran"))
    if os.name != "nt":
        K.create_keys(kdir)


# --- the hub's public key module -----------------------------------------------------------------

def test_current_pubkey_file_is_readable():
    assert K.read_trusted_keys(K.REPO_ROOT / K.PUBKEY_MODULE) == tuple(licence_pubkey.TRUSTED_KEYS)


def test_public_key_py_imports_and_keeps_old_keys(tmp_path, made):
    old = K.create_keys(tmp_path / "old")
    text = K.public_key_py(made.public, existing=[old.public])
    (tmp_path / "m.py").write_text(text, encoding="utf-8")
    mod = load_module(tmp_path / "m.py")
    assert mod.TRUSTED_KEYS == (old.public, made.public)
    assert K.read_trusted_keys(tmp_path / "m.py") == (old.public, made.public)
    assert K.public_key_py(made.public, existing=[made.public]).count(made.public.hex()) == 1


def test_write_public_key_py(tmp_path, made):
    repo = tmp_path / "repo"
    target = repo / K.PUBKEY_MODULE
    target.parent.mkdir(parents=True)
    target.write_text((K.REPO_ROOT / K.PUBKEY_MODULE).read_text(encoding="utf-8"), encoding="utf-8")
    assert K.write_public_key_py(repo, made) == target
    first = load_module(target).TRUSTED_KEYS
    assert first == (*licence_pubkey.TRUSTED_KEYS, made.public)
    new = K.create_keys(tmp_path / "new")                # a key change keeps the old key trusted
    K.write_public_key_py(repo, new)
    keys = load_module(target).TRUSTED_KEYS
    assert keys == (*first, new.public)
    for raw in keys:
        K.Ed25519PublicKey.from_public_bytes(raw)
    for k in (made, new):                                # both keys' codes verify with the generated module
        data = licence.encode_payload({"v": 1, "licence_id": "l-1", "cafe_id": "c-1", "cafe_name": "A", "rigs": 4,
                                       "games": ["f1_25"], "features": [], "variant": "9t7",
                                       "issued": "2026-11-03", "seq": 1})
        licence.verify(licence.make_code(data, k.private.sign(data)), keys=keys)
    assert all(s not in target.read_text() for k in (made, new) for s in secret_texts(k))


def test_unreadable_pubkey_file_is_never_replaced(tmp_path, made):
    repo = tmp_path / "repo"
    target = repo / K.PUBKEY_MODULE
    target.parent.mkdir(parents=True)
    for text in ("TRUSTED_KEYS = (SOME_KEY,)\n", "def (\n", "TRUSTED_KEYS = ('zz',)\n", "X = 1\n",
                 "TRUSTED_KEYS_HEX = ('" + "00" * 31 + "',)\n"):
        target.write_text(text)
        with pytest.raises(KeysError, match="wasn't changed"):
            K.write_public_key_py(repo, made)
        assert target.read_text() == text


def test_is_trusted(made, monkeypatch):
    assert not K.is_trusted(made, trusted=())
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (made.public,))
    assert K.is_trusted(made)


# --- backup --------------------------------------------------------------------------------------

def test_backup_copies_checks_and_records(tmp_path, kdir, made):
    usb = tmp_path / "usb"
    usb.mkdir()
    assert K.backup_state(kdir) is None and not K.backed_up(kdir)
    state = K.copy_backup(usb, kdir, today=DAY)
    assert state == K.BackupState(backed_up_to=str(usb), date=DAY, fingerprint=made.fingerprint)
    assert K.backup_state(kdir) == state and K.backed_up(kdir)
    for name in (K.PRIVATE_FILE, K.PUBLIC_FILE):
        assert (usb / name).read_bytes() == (kdir / name).read_bytes()
    assert K.load_private(usb).public == made.public
    if os.name != "nt":
        assert (usb / K.PRIVATE_FILE).stat().st_mode & 0o777 == 0o600
    K.copy_backup(usb, kdir, today=DAY)                  # the same key again is fine


def test_backup_refuses_repo_shipments_and_key_folder(tmp_path, kdir, made):
    ship = tmp_path / "Shipments"
    (ship / "Apex").mkdir(parents=True)
    for dest, forbidden in ((K.REPO_ROOT, ()), (K.REPO_ROOT / "factory", ()), (ship, [ship]),
                            (ship / "Apex", [ship]), (kdir / "sub", ())):
        dest.mkdir(exist_ok=True)
        with pytest.raises(KeysError):
            K.copy_backup(dest, kdir, forbidden=forbidden)
        assert not (dest / K.PRIVATE_FILE).exists()
    with pytest.raises(KeysError, match="outside the key folder"):
        K.copy_backup(kdir, kdir)
    assert not K.backed_up(kdir)
    with pytest.raises(KeysError, match="isn't there"):
        K.copy_backup(tmp_path / "unplugged", kdir)


def test_backup_never_overwrites_another_key(tmp_path, kdir, made):
    usb = tmp_path / "usb"
    other = K.create_keys(usb)
    with pytest.raises(KeysError, match="different signing key"):
        K.copy_backup(usb, kdir)
    assert K.load_private(usb).public == other.public and not K.backed_up(kdir)


def test_backup_bad_copy_is_not_recorded(tmp_path, kdir, made, monkeypatch):
    usb = tmp_path / "usb"
    usb.mkdir()
    real = K.write_atomic
    monkeypatch.setattr(K, "write_atomic", lambda p, d: real(p, d[:-1] if p.parent == usb else d))
    with pytest.raises(KeysError, match="couldn't be copied"):
        K.copy_backup(usb, kdir)
    assert not K.backed_up(kdir)


def test_backup_record_for_another_key_counts_as_none(tmp_path, kdir, made):
    usb = tmp_path / "usb"
    usb.mkdir()
    K.copy_backup(usb, kdir)
    (kdir / K.PRIVATE_FILE).unlink()
    (kdir / K.PUBLIC_FILE).unlink()
    K.create_keys(kdir)                                  # lost key, new keys: the banner is back
    assert not K.backed_up(kdir) and not (kdir / K.STATE_FILE).exists()
    (kdir / K.STATE_FILE).write_text("{damaged")
    assert K.backup_state(kdir) is None


def test_key_bytes_never_logged(tmp_path, kdir, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    keys = K.create_keys(kdir)
    usb = tmp_path / "usb"
    usb.mkdir()
    K.copy_backup(usb, kdir)
    repo = tmp_path / "repo"
    (repo / K.PUBKEY_MODULE).parent.mkdir(parents=True)
    K.write_public_key_py(repo, keys)
    assert caplog.records
    for s in secret_texts(keys):
        assert s not in caplog.text
    assert keys.fingerprint in caplog.text
    assert "Ed25519PrivateKey" not in repr(keys)


# --- C8 review ------------------------------------------------------------------------------------

def test_icacls_is_the_system32_one_and_its_output_is_never_decoded(kdir, monkeypatch):
    kws = []
    windows_mocked(monkeypatch)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(K, "_run", lambda cmd, **kw: kws.append((cmd, kw)) or subprocess.CompletedProcess(cmd, 0))
    K.create_keys(kdir)
    assert all(cmd[0] == str(K.Path(r"C:\Windows") / "System32" / "icacls.exe") for cmd, _ in kws)
    for _, kw in kws:                                     # no text=True: a non-English path can't crash the decode
        assert not kw.get("text") and kw["stdout"] == subprocess.DEVNULL and kw["stderr"] == subprocess.DEVNULL
    assert K.icacls_exe({}) == "icacls"


@pytest.mark.parametrize("windows", [False, True])
def test_write_new_works_on_a_drive_without_hard_links(tmp_path, monkeypatch, windows):
    def no_links(*a, **k):
        raise OSError(1, "Operation not permitted")
    monkeypatch.setattr(K.os, "link", no_links)
    monkeypatch.setattr(K, "_is_windows", lambda: windows)
    monkeypatch.setattr(K, "_protect", lambda *a, **k: None)
    target = tmp_path / "signing.key"
    K._write_new(target, b"key", private=True)
    assert target.read_bytes() == b"key" and not list(tmp_path.glob("*.tmp"))
    with pytest.raises(KeysError, match="not replaced"):
        K._write_new(target, b"new", private=True)
    assert target.read_bytes() == b"key"


def test_write_public_key_py_refuses_a_folder_that_isnt_the_source(tmp_path, made):
    with pytest.raises(KeysError, match="isn't the program's source folder"):
        K.write_public_key_py(tmp_path / "somewhere", made)
    assert not (tmp_path / "somewhere").exists()


def test_read_trusted_keys_keeps_keys_from_every_assignment(tmp_path, made):
    old = K.create_keys(tmp_path / "old")
    path = tmp_path / "m.py"
    path.write_text(K.public_key_py(made.public) + f"TRUSTED_KEYS = (bytes.fromhex('{old.public.hex()}'),)\n"
                    + f"TRUSTED_KEYS = ({old.public!r},)\n")
    assert K.read_trusted_keys(path) == (made.public, old.public)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_backup_private_copy_is_never_readable_by_others(tmp_path, kdir, made):
    usb = tmp_path / "usb"
    usb.mkdir()
    old = os.umask(0)
    try:
        K.copy_backup(usb, kdir)
    finally:
        os.umask(old)
    assert (usb / K.PRIVATE_FILE).stat().st_mode & 0o777 == 0o600


def test_unreadable_key_says_which_account(kdir, made, monkeypatch):
    real = K.Path.read_bytes

    def denied(self):
        if self.name == K.PRIVATE_FILE:
            raise PermissionError(13, "denied")
        return real(self)
    monkeypatch.setattr(K.Path, "read_bytes", denied)
    with pytest.raises(KeysError, match="account can't open"):
        K.load_private(kdir)
