import logging
import logging.handlers
import os

import yaml


def init_logger(conf_file: str | None = None):
    """
    Initialise the root logger for the CLI.

    When a config file is provided the logger uses a ``RotatingFileHandler``
    (rotating at ``log_max_bytes`` with ``log_backup_count`` backups) and a
    ``StreamHandler`` on stdout.  Without a config file a basic ``INFO``
    handler is configured instead.
    """
    # Suppress noisy output from evtx in all code paths
    logging.getLogger("evtx").setLevel(logging.ERROR)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Configure root logger
    root_logger = logging.getLogger()
    if not any(
        getattr(handler, "_ogre_console_handler", False) for handler in root_logger.handlers
    ):
        stdout_handler = logging.StreamHandler()
        stdout_handler.setFormatter(formatter)
        stdout_handler._ogre_console_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(stdout_handler)
    root_logger.setLevel(logging.INFO)
    if not conf_file:
        return

    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf) or {}
        log_filename = config_dict.get("log_file_name", None)
        if not log_filename:
            return

        log_level = getattr(logging, config_dict.get("log_level", "INFO").upper(), logging.INFO)
        log_dir = config_dict.get("log_file_path", "./")
        log_file = os.path.abspath(os.path.join(log_dir, log_filename))
        max_bytes = config_dict.get("log_max_bytes", 5242880)
        backup_count = config_dict.get("log_backup_count", 3)
        os.makedirs(log_dir, exist_ok=True)

        if not _has_file_handler(root_logger, log_file):
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
            )
            file_handler.setFormatter(formatter)
            file_handler._ogre_log_file = log_file  # type: ignore[attr-defined]
            root_logger.addHandler(file_handler)
        root_logger.setLevel(log_level)


def _has_file_handler(root_logger: logging.Logger, log_file: str) -> bool:
    for handler in root_logger.handlers:
        if getattr(handler, "_ogre_log_file", None) == log_file:
            return True
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file:
            return True
    return False
