from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MARK = "_simtelemetry_handler"
LAP_DEBUG_LOGGER = "simtelemetry.lapdebug"


def teardown_logging() -> None:
    """Remove and close the handlers added by setup_logging (closes hub.log)."""
    root = logging.getLogger()
    for logger in (root, logging.getLogger(LAP_DEBUG_LOGGER)):
        for handler in [h for h in logger.handlers if getattr(h, _MARK, False)]:
            logger.removeHandler(handler)
            handler.close()


def setup_logging(log_dir: Path | None, verbose: bool = False, lap_debug: bool = False) -> Path | None:
    """Console + rotating file log. Safe to call more than once.

    With lap_debug, every lap event is logged (console + hub.log) and also written to its own
    file, lap-debug-<date>-<time>.log, whose path is returned.
    """
    teardown_logging()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    lap_logger = logging.getLogger(LAP_DEBUG_LOGGER)
    lap_logger.setLevel(logging.INFO if lap_debug else logging.WARNING)

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

    if lap_debug and log_dir is not None:
        path = log_dir / f"lap-debug-{time.strftime('%Y%m%d-%H%M%S')}.log"
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%Y-%m-%d %H:%M:%S"))
        setattr(handler, _MARK, True)
        lap_logger.addHandler(handler)
        lap_logger.info("lap debug log started")
        return path
    return None
