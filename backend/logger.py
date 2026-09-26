"""
Structured logging setup for NIKOLA backend using structlog.
All modules use: logger = get_logger(__name__)
"""

import logging
from pathlib import Path

import structlog


def configure_logging():
    """Configure structlog with timestamper, log level, and logger name."""

    # Ensure logs directory exists
    logs_dir = Path.cwd().parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Standard library logging config for third-party libs
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.FileHandler(logs_dir / "backend.log"),
            logging.StreamHandler(),
        ],
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structlog logger instance."""
    return structlog.get_logger(name)


# Configure on module import
configure_logging()
