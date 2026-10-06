from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MARK = "_simtelemetry_handler"


def setup_logging(log_dir: Path | None, verbose: bool = False) -> None:
    """Console + rotating file log. Safe to call more than once."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
    setattr(console, _MARK, True)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "hub.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(file_handler, _MARK, True)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
