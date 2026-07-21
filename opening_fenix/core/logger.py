import logging
import os
from opening_fenix.core.utils import get_user_dir

def setup_logger(name="OpeningFenix"):
    """Configures and returns a logger for the application."""
    user_dir = get_user_dir()
    log_file = os.path.join(user_dir, "app.log")
    
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File handler
        try:
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            print(f"Warning: Could not create log file '{log_file}': {e}")
        
    return logger

# Create a default instance for easy access
logger = setup_logger()
