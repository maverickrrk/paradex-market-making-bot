import logging
from logging.handlers import RotatingFileHandler
import os
import sys

# Define a custom formatter for adding colors to console logs
class ColorFormatter(logging.Formatter):
    """A custom log formatter that adds color to console output."""
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    # Define the format for different log levels
    log_format = "[%(asctime)s] [%(name)s] [%(levelname)-8s] - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    FORMATS = {
        logging.DEBUG: GREY + log_format + RESET,
        logging.INFO: GREY + log_format + RESET,
        logging.WARNING: YELLOW + log_format + RESET,
        logging.ERROR: RED + log_format + RESET,
        logging.CRITICAL: BOLD_RED + log_format + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt=self.date_format)
        return formatter.format(record)


def setup_logger(name: str, log_level: str, log_dir: str) -> logging.Logger:
    """
    Sets up a standardized logger for the application.

    This function configures a logger to output to both the console (with colors)
    and a rotating log file. This ensures logs are visible during runtime and
    are also saved for later analysis.

    Args:
        name: The name for the logger, typically the module or application name.
        log_level: The minimum logging level to capture (e.g., "INFO", "DEBUG").
        log_dir: The directory where log files should be stored.

    Returns:
        A fully configured logger instance.
    """
    # Create the directory for log files if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    
    # Prevent adding duplicate handlers if the function is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Set the logging level from the configuration
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    
    # Set root logger level to ensure all child loggers inherit it
    logging.getLogger().setLevel(level)

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)  # Set console handler to same level as logger
    console_handler.setFormatter(ColorFormatter())
    logger.addHandler(console_handler)

    # --- File Handler ---
    # Creates a new log file when the current one reaches 10MB, keeping 5 backups.
    log_file_path = os.path.join(log_dir, f"{name}.log")
    file_handler = RotatingFileHandler(
        log_file_path, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)-8s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Allow logs to propagate to the root logger so child loggers inherit the level
    logger.propagate = True

    return logger