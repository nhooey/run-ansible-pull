import logging
import sys

from cloghandler import ConcurrentRotatingFileHandler

logging.raiseExceptions = True
logger_label = "run-ansible-pull"
logger_labels = [logger_label, "tendo.singleton"]


def set_logging_config(debug, log_file):
    loggers = [logging.getLogger(label) for label in logger_labels]

    for logger in loggers:
        logger.setLevel(logging.DEBUG if debug else logging.INFO)

        log_handlers = [logging.StreamHandler(sys.stdout)]

        if type(log_file) is str:
            log_handlers.append(
                ConcurrentRotatingFileHandler(
                    log_file, maxBytes=10000000, backupCount=5
                )
            )

        log_format = "%(asctime)s %(name)-10s %(process)6d %(levelname)-8s %(message)s"

        for log_handler in log_handlers:
            log_handler.setFormatter(logging.Formatter(log_format))
            logger.addHandler(log_handler)
