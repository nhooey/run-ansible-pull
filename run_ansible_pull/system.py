import atexit
import fcntl
import logging
import os
import shutil
import signal
import subprocess
import sys
import time

import psutil
from psutil import NoSuchProcess, ZombieProcess

from run_ansible_pull.logger import logger_label

logger = logging.getLogger(logger_label)


def instance_already_running():
    lockfile = os.open("/tmp/run-ansible-pull.lock", os.O_CREAT | os.O_WRONLY)

    try:
        fcntl.lockf(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        already_running = False
    except IOError:
        already_running = True

    return already_running


def subprocess_popen_pipe_output(cmd):
    kwargs_line_buffered = dict(bufsize=1)
    if sys.hexversion >= 0x3070000:
        # "text" was added as a keyword argument alias for "universal_newlines"
        # in Python 3.7, and "universal_newlines" is provided still only for
        # backwards compatibility. Let's do this right if we're going to do it.
        kwargs_line_buffered = {**dict(text=True), **kwargs_line_buffered}
    else:
        # For systems with python before 3.7, use "universal_newlines"
        kwargs_line_buffered = {**dict(universal_newlines=True), **kwargs_line_buffered}

    return subprocess.Popen(
        cmd, **kwargs_line_buffered, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def kill_softly(parent_popen):
    logger.info(
        "Terminating parent PID[%s] and all of its children...", parent_popen.pid
    )

    try:
        parent_process = psutil.Process(parent_popen.pid)
    except (NoSuchProcess, ZombieProcess):
        logger.warning(
            "Process PID[%s] does not exist or is a zombie.", parent_popen.pid
        )
    else:
        terminate_processes = [parent_process] + parent_process.children(recursive=True)
        logger.info(
            "Terminating all processes PID%s", [p.pid for p in terminate_processes]
        )

        for process in terminate_processes:
            logger.info("Terminating process PID[%s]", process.pid)
            try:
                process.terminate()
            except NoSuchProcess:
                logger.debug("Process already stopped PID[%s]", process.pid)

            attempts = 0
            for attempt in range(1, 10 + 1):
                attempts += 1
                if process.is_running():
                    logger.debug(
                        "Waited %s seconds for PID: %s to terminate...",
                        attempts,
                        process.pid,
                    )
                    time.sleep(1)

            if process.is_running():
                logger.info(
                    "Sending SIGKILL to process PID[%s] after %s seconds...",
                    process.pid,
                    attempts,
                )
                try:
                    process.kill()
                except NoSuchProcess:
                    logger.debug("Process already stopped PID[%s]", process.pid)

            # Give child processes time to be terminated by their parent
            time.sleep(5)


def clean_tmp_dir():
    ansible_tmp_dir = os.path.join(os.path.expanduser("~"), ".ansible", "tmp")
    if os.path.exists(ansible_tmp_dir):
        shutil.rmtree(ansible_tmp_dir)


def register_signal_handlers(_logger):
    def exit_handler():
        _logger.info("%s Exiting normally... %s", "=" * 20, "=" * 20)
        _logger.info("")

    atexit.register(exit_handler)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


def handle_signal(sig, frame=None):
    logger.debug("--- Received signal: %s, frame: %s", sig, frame)
    if sig in (signal.SIGINT, signal.SIGTERM):
        raise ShutdownException(sig)


class ShutdownException(BaseException):
    def __init__(self, sig):
        self.signal = sig

    def __str__(self):
        return "ShutdownException(%s)" % self.signal
