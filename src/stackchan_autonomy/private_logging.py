"""Scoped library log isolation for the standalone, single-session PC bridge."""

import logging
from contextlib import contextmanager


@contextmanager
def private_library_logs():
    roots = ("mcp", "websockets", "openai", "httpx", "httpx2", "httpcore", "httpcore2")
    for name in roots:
        logging.getLogger(name)
    loggers = [
        logger
        for name, logger in list(logging.Logger.manager.loggerDict.items())
        if isinstance(logger, logging.Logger)
        and any(name == root or name.startswith(root + ".") for root in roots)
    ]
    # MCP typed-validation errors also use root logging. This process is dedicated.
    loggers.append(logging.getLogger())
    previous = [(logger, logger.handlers[:], logger.propagate) for logger in loggers]
    try:
        for logger in loggers:
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
        yield
    finally:
        for logger, handlers, propagate in previous:
            logger.handlers = handlers
            logger.propagate = propagate
