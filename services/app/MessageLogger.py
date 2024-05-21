import logging
import sys
from utilities import log_level

def setup_logger(name, filename="app", log_dir="/var/log"):
    """
    Set up a logger with the name and log it to a file
    """
    # Create a logger
    logger = logging.getLogger(name)

    # Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    logger.setLevel(log_level)

    if not logger.handlers:

        # Create handlers (console handler and file handler)
        # console_handler = logging.StreamHandler(sys.stdout)
        file_handler = logging.FileHandler(f"{log_dir}/{filename}.log")

        # Set the logging level for handlers
        # console_handler.setLevel(log_level)
        file_handler.setLevel(log_level)

        # Create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Add handlers to the logger
        # logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        logger.propagate = False

    return logger
