#!/usr/bin/env python3
import logging
import os
import re
import subprocess
import time
import shutil
import sys

from datetime import timedelta
from tendo.singleton import SingleInstance, SingleInstanceException
from threading import Thread
from queue import Queue, Empty

from run_ansible_pull.ansible import get_ansible_cmd, get_ansible_result
from run_ansible_pull.args import get_args
from run_ansible_pull.config import get_git_branch
from run_ansible_pull.logger import set_logging_config, logger_label
from run_ansible_pull.sensu import (
    SENSU_OK,
    SENSU_WARNING,
    SENSU_CRITICAL,
    format_sensu_summary,
    send_sensu_event,
)
from run_ansible_pull.system import (
    kill_softly,
    clean_tmp_dir,
    register_signal_handlers,
    ShutdownException,
)

logger = logging.getLogger(logger_label)


def run():
    args = get_args()
    set_logging_config(args.debug, args.log_file)
    git_branch = get_git_branch()

    try:
        SingleInstance()
    except SingleInstanceException:
        logger.error("Instance already running, quitting.")
        send_sensu_event(
            status=SENSU_WARNING,
            summary="Instance already running.",
            enabled=args.notify_sensu,
        )
        sys.exit(-1)

    register_signal_handlers(logger)

    clean_tmp_dir()

    return_code = -42

    first_run = True
    try_again = False

    while first_run or try_again:
        try_again = False
        process = None
        start_time = time.time()

        try:
            ansible_cmd = get_ansible_cmd(
                args.work_dir,
                args.git_repo_url,
                args.vault_pass_file,
                args.tags,
                args.playbook_path,
                git_branch,
            )
            logger.info("Running Ansible command: %s", " ".join(ansible_cmd))
            process = subprocess.Popen(
                ansible_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            logger.info("Started Ansible process with PID: %s", process.pid)

            def ansible_running():
                return process.poll() is None

            def timeout_reached():
                return time.time() - start_time > args.timeout

            queue = Queue()
            logger_thread = Thread(target=enqueue_output, args=(process.stdout, queue))
            logger_thread.daemon = True
            logger_thread.start()

            one_more_time = iter([True] * 20 + [False])

            ansible_output = ""

            while (ansible_running() and not timeout_reached()) or next(one_more_time):
                line = None
                try:
                    line = queue.get(block=False)
                except Empty:
                    pass
                else:
                    queue.task_done()

                if line is not None:
                    line = line.decode("utf-8")
                    logger.info(line.rstrip())
                    ansible_output += line
                else:
                    time.sleep(0.1)

            try:
                return_code = process.wait(0)
            except subprocess.TimeoutExpired:
                return_code = None

        except ShutdownException as e:
            logger.error("Ansible Pull result: Interrupted. PID[%s]", process.pid)
            kill_softly(process)
            sys.exit(e.signal)
        else:
            if return_code is None:
                logger.error(
                    "Ansible Pull result: Timeout (%s seconds). PID[%s]",
                    args.timeout,
                    process.pid,
                )
                kill_softly(process)
            else:
                logger.info(
                    "Ansible Pull result: %s. PID[%s]. Return code: %s",
                    "Success" if return_code == 0 else "Failed",
                    process.pid,
                    process.returncode,
                )
        finally:
            end = time.time()
            runtime = timedelta(seconds=int(end - start_time))

        ansible_result = get_ansible_result(ansible_output)

        def get_git_failure_type(_ansible_result):

            git_failed_with_msg = (
                _ansible_result.get("git_result")
                and not _ansible_result["git_result"]["success"]
                and _ansible_result["git_result"].get("msg")
            )

            git_failure = None

            if git_failed_with_msg:
                regex_git_failure = re.compile(
                    r"^Failed to (?P<failure>checkout|download)\\b"
                )
                match = re.search(
                    regex_git_failure, _ansible_result["git_result"]["msg"]
                )
                git_failure = match.groups("failure")

            return git_failure

        git_failure_type = get_git_failure_type(ansible_result)

        sensu_status = SENSU_OK if process.returncode == 0 else SENSU_CRITICAL

        # Delete and try again if Git failed on the first run
        if git_failure_type and first_run:
            if git_failure_type == "checkout":
                git_branch = "master"

            if os.path.exists(args.work_dir):
                logger.warning(
                    'Deleting Git directory: "%s" because Git failed to checkout branch',
                    args.work_dir,
                )
                shutil.rmtree(args.work_dir)
            sensu_status = SENSU_WARNING
            try_again = True

        summary = format_sensu_summary(ansible_result, runtime)
        send_sensu_event(
            status=sensu_status, summary=summary, enabled=args.notify_sensu
        )

        return_code = process.returncode

        first_run = False

    sys.exit(return_code)


def enqueue_output(out, queue):
    try:
        first_time = True

        for line in iter(out.readline, b""):
            if first_time:
                logger.debug("Logging Thread[%s] queueing output...", os.getpid())
                first_time = False

            queue.put(line)

    except ShutdownException:
        logger.info("Shutting down enqueue_output() loop")
    finally:
        logger.debug("Logging Thread[%s] hit Empty, quitting...", os.getpid())
        out.close()
