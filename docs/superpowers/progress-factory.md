# Progress: Pitwall Factory

Plan: `docs/superpowers/plans/2026-11-03-factory.md`. Spec: `docs/superpowers/specs/2026-11-03-factory-design.md`. Branch: `factory`.

Each session starts by reading this log and continues from the first task not marked done. Every finished task gets a line here with its commits, test counts, any deviations, and anything left for LOCAL.

## Baseline
- 2026-11-03: the branch was created from `hardening` ab915ae (Pitwall 0.5.0). The hub has 884 passing tests and the dashboard has 120 (vitest).
- The spec was committed in c2c6927, and the plan in the commit that added this file.

- 2026-11-03 cloud session (Linux, Python 3.13, root): hub `869 passed, 10 skipped, 5 failed`. The 5 failures are pre-existing and environment-only: 4 in `test_backup_folder.py` (Windows drive letters / root ignores folder permissions) and `test_config.py::test_safe_bad_value_uses_that_default_and_keeps_the_rest`. They also fail on `ab915ae` before any factory work; LOCAL should confirm they pass on Windows. Dashboard: 120 vitest pass, `tsc -b` clean. tkinter is not available in the cloud Python, so the app smoke test skips here.

## Tasks
- [ ] C1 Licence core
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
