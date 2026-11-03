"""The product name and every name derived from it. "Pitwall" is a placeholder: renaming is this one line.

Used by paths (ProgramData folder), the CLI --version, the PyInstaller spec (exe name), packaging/build.ps1 and
the installer (installer file, title, boot task, shortcuts, uninstall entry), and the mDNS host name when
that is built. The Python package stays `simtelemetry`.
"""

from __future__ import annotations

import re

PRODUCT_NAME = "Pitwall"
COMPANY = "9T7 Racing"                                           # the 9T7 installer's publisher, 9t7 supplier

SLUG = re.sub(r"[^a-z0-9]+", "-", PRODUCT_NAME.lower()).strip("-")
EXE_NAME = re.sub(r"[^A-Za-z0-9]+", "", PRODUCT_NAME)          # Pitwall.exe
TASK_NAME = f"{PRODUCT_NAME} Hub"                                # Windows boot task
MDNS_HOST = f"{SLUG}.local"                                      # reserved for the mDNS feature
HOME_ENV = f"{EXE_NAME.upper()}_HOME"                            # e.g. PITWALL_HOME


def as_dict() -> dict[str, str]:
    """For build scripts: `python -c "from simtelemetry import brand, json; print(json.dumps(brand.as_dict()))"`."""
    return {"PRODUCT_NAME": PRODUCT_NAME, "SLUG": SLUG, "EXE_NAME": EXE_NAME, "TASK_NAME": TASK_NAME,
            "MDNS_HOST": MDNS_HOST, "HOME_ENV": HOME_ENV, "COMPANY": COMPANY}
