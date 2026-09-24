from __future__ import annotations

import logging
import re

_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _KEY_PATTERN.search(message) or "OPENAI_API_KEY" in message:
            record.msg = "[redacted sensitive log message]"
            record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(RedactSecretsFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
