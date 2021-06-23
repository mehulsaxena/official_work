import os
import re
import sys
from loguru import logger
import logginggit
import json


class LoggingFormatter:
    """The base logging formatter for DCS"""

    def __init__(self, fmt):
        super().__init__()
        # regex pattern scrubber. Could not turn message into JSON if it existed, went with regex - Josh
        self.scrub_patterns = {
            r":\/\/(.*?)\@": r"://[REDACTED]@",
            r".password.:\W+['|\"](.*?)['|\"]": r"'password': '[REDACTED]'",
            r".secret.:\W+['|\"](.*?)['|\"]": r"'secret': '[REDACTED]'",
            r".jwt.:\W+['|\"](.*?)['|\"]": r"'jwt': '[REDACTED]'",
            r".st2_api_key.:\W+['|\"](.*?)['|\"]": r"'st2_api_key': '[REDACTED]'",
            r".redis_password.:\W+['|\"](.*?)['|\"]": r"'redis_password': '[REDACTED]'",
        }
        self.fmt = fmt

    def format(self, record):
        """The loguru format method"""

        scrubbed = record["message"]
        # scrubs any messages that match the message pattern
        if isinstance(scrubbed, dict):
            scrubbed = json.dumps(scrubbed)
        for search, replace in self.scrub_patterns.items():
            scrubbed = re.sub(search, replace, scrubbed)
        record["extra"]["scrubbed"] = scrubbed

        if not record["extra"].get("device") or record["extra"].get("device") is None:
            record["extra"]["device"] = ""
        else:
            record["extra"]["device"] = f"{record['extra']['device']} - "
        return self.fmt


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging():
    logger.remove()
    log_level = os.getenv("LOGURU_LEVEL", "INFO")
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<red>{extra[device]}</red><level>{extra[scrubbed]}\n{exception}</level>"
    )
    std_formatter = LoggingFormatter(fmt)

    # add the loggers after hand
    if log_level == "DEBUG":
        logger.add(
            sink=sys.stderr,
            level="DEBUG",
            format=std_formatter.format,
            enqueue=True,
            backtrace=True,
            diagnose=True,
            colorize=True,
        )
    else:
        logger.add(
            sink=sys.stderr,
            level=log_level,
            format=std_formatter.format,
            enqueue=True,
            backtrace=False,
            diagnose=True,
            colorize=True,
        )

    # intercept root logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(log_level)
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    logger.configure(handlers=[{"sink": sys.stdout, "serialize": False}])



