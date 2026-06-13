"""``python -m monday`` — run the engine with uvicorn (host/port from config)."""

from __future__ import annotations

import logging

import uvicorn

from .config import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    uvicorn.run("monday.app:app", host=settings.monday_host, port=settings.monday_port,
                log_level="info")


if __name__ == "__main__":
    main()
