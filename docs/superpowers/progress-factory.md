# Progress: Pitwall Factory

Plan: `docs/superpowers/plans/2026-11-03-factory.md`. Spec: `docs/superpowers/specs/2026-11-03-factory-design.md`. Branch: `factory`.

Each session starts by reading this log and continues from the first task not marked done. Every finished task gets a line here with its commits, test counts, any deviations, and anything left for LOCAL.

## Baseline
- 2026-11-03: the branch was created from `hardening` ab915ae (Pitwall 0.5.0). The hub has 884 passing tests and the dashboard has 120 (vitest).
- The spec was committed in c2c6927, and the plan in the commit that added this file.

- 2026-11-03 cloud session (Linux, Python 3.13, root): hub `869 passed, 10 skipped, 5 failed`. The 5 failures are pre-existing and environment-only: 4 in `test_backup_folder.py` (Windows drive letters / root ignores folder permissions) and `test_config.py::test_safe_bad_value_uses_that_default_and_keeps_the_rest`. They also fail on `ab915ae` before any factory work; LOCAL should confirm they pass on Windows. Dashboard: 120 vitest pass, `tsc -b` clean. tkinter is not available in the cloud Python, so the app smoke test skips here.

## Tasks
- [x] C1 Licence core
- [ ] C2 Licence storage, owner page, backups
- [ ] C3 Enforcement
- [ ] C4 Dashboard
- [ ] C5 Provisioning
- [ ] C6 Installer support (static)
- [ ] C7 Factory profile, pricing, presets
- [ ] C8 Keys and licence issue
- [ ] C9 Documents
- [ ] C10 Build pipeline
- [ ] C11 Preview
- [ ] C12 Form app
- [ ] C13 Whole-branch review and LOCAL hand-off list
- [ ] L1–L6 LOCAL (Windows PC)

## Log

- 2026-11-03 **C1 Licence core** (cloud). New `hub/simtelemetry/licence.py`, `hub/simtelemetry/licence_pubkey.py` (`TRUSTED_KEYS = ()` until L1), `hub/tests/test_licence.py` (60 tests); `cryptography>=42` added to `pyproject.toml`. Hub: `929 passed, 10 skipped, 5 failed` (the same 5 pre-existing environment failures as the baseline; no new ones).
  - API: `parse(code) -> Parsed`, `verify(code, keys=None) -> Licence`, `entitlements_from(licence) -> Entitlements`, `accept_new(current, new_licence) -> Entitlements`, `FALLBACK`, plus `encode_payload(dict) -> bytes` (canonical JSON: sorted keys, compact) and `make_code(payload, sig) -> str` so the factory (C8) signs exactly the bytes the hub verifies. Errors are **raised** as `LicenceError(ValueError)` with plain-English messages (the plan's `-> Licence | LicenceError` is read as "returns or raises").
  - `keys=None` reads `licence_pubkey.TRUSTED_KEYS` at call time, so tests monkeypatch the module attribute.
  - Whitespace and line breaks are removed anywhere in a pasted code (not only around it); `=` padding is tolerated. The stored code is the normalised one.
  - Payload model is strict (`rigs: true` or `"6"` is refused), ignores unknown keys (a newer v1 factory still verifies), `rigs` 1..999. Feature names unknown to this hub are dropped in `entitlements_from`.
  - `Entitlements.licensed(n)`: rig numbers are 1-based ("Rig N" in rigs.json), so rigs 1..N are licensed. `supplier` is `brand.COMPANY` for 9t7, "your supplier" for unbranded; `vendor_mark` is `variant == "9t7"`.
  - PyInstaller spec unchanged: pyinstaller-hooks-contrib bundles `cryptography` itself. **LOCAL** must confirm the built exe verifies a code (part of L1/L2).

## Decisions to confirm
- C1: the error messages end with a full stop ("This code isn't valid: check you copied all of it."), matching the hub's other owner messages.
- C1: re-entering the exact code that is installed says "This code is already installed." instead of "older than the one installed" (a fourth plain message, not in spec §2.3). A different code with the same or a lower seq says "This code is older than the one installed."
