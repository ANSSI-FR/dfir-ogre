
import logging
import logging.handlers
import os
import sys
import yaml

def init_logger(conf_file: str|None=None):
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

    # Stdout handler
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(stdout_handler)
    root_logger.setLevel(logging.INFO)
    if not conf_file:
      return

    with open(conf_file) as conf:
      config_dict = yaml.safe_load(conf)
      log_filename = config_dict.get("log_file_name", None)
      if not log_filename:
        return

      log_level = getattr(logging, config_dict.get("log_level", "INFO").upper(), logging.INFO)
      # Rotating file handler
      log_dir = config_dict.get("log_file_path", "./")
      log_file = os.path.join(log_dir, log_filename)
      max_bytes = config_dict.get("log_max_bytes", 5242880)
      backup_count = config_dict.get("log_backup_count", 3)
      os.makedirs(log_dir, exist_ok=True)
      file_handler = logging.handlers.RotatingFileHandler(
          log_file,
          maxBytes=max_bytes,
          backupCount=backup_count,
      )
      file_handler.setFormatter(formatter)
      root_logger.addHandler(file_handler)
      root_logger.setLevel(log_level)
