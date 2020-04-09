#!/usr/bin/env python3
import logging
import os
import re
import subprocess
import time
import shutil
import sys

from datetime import timedelta
from multiprocessing import JoinableQueue, Process
from queue import Empty

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
    subprocess_popen_pipe_output,
    instance_already_running,
)

logger = logging.getLogger(logger_label)


def run():
    args = get_args()
    set_logging_config(args.debug, args.log_file)
    git_branch = get_git_branch()

    if instance_already_running():
        send_sensu_event(
            status=SENSU_WARNING,
            summary="Instance already running.",
            enabled=args.notify_sensu,
        )
        logger.error("Instance already running, quitting.")
        sys.exit(-1)

    register_signal_handlers(logger)

    clean_tmp_dir()

    return_code = -42

    first_run = True
    try_again = False

    while first_run or try_again:
        try_again = False
        ansible_process = None
        start_time = time.time()

        try:
            ansible_cmd = get_ansible_cmd(
                args.work_dir,
                args.git_repo_url,
                args.vault_pass_file,
                args.extra_vars,
                args.tags,
                args.only_if_changed,
                args.playbook_path,
                git_branch,
            )
            logger.info("Running Ansible command: %s", " ".join(ansible_cmd))
            ansible_process = subprocess_popen_pipe_output(ansible_cmd)
            logger.info("Started Ansible process with PID: %s", ansible_process.pid)

            queue = JoinableQueue()
            logger_process = Process(
                target=enqueue_output, args=(ansible_process.stdout, queue)
            )
            logger_process.start()

            ansible_output = ""

            class LoopEnder:
                def __init__(self, _process, _start_time, _timeout):
                    self._state_ansible_running = None
                    self._state_time_elapsed = None
                    self._state_remainder = None
                    self._counter_remainder = list([True] * 20 + [False])
                    self._process = _process
                    self._start_time = _start_time
                    self._timeout = _timeout

                def keep_going(self):
                    keep_going = (
                        self._ansible_running() and not self._timeout_reached()
                    ) or self._remainder()
                    logger.debug("Keep going: %s", self)
                    return keep_going

                def __str__(self):
                    return ", ".join(
                        [
                            f"start time: {self._start_time}",
                            f"timeout: {self._timeout}",
                            f"ansible running: {self._state_ansible_running}",
                            f"time remaining: {self._timeout - self._state_time_elapsed}",
                            f"remainder count: {len(list(filter(None, self._counter_remainder)))}",
                        ]
                    )

                def _ansible_running(self):
                    self._state_ansible_running = self._process.poll() is None
                    return self._state_ansible_running

                def _timeout_reached(self):
                    self._state_time_elapsed = time.time() - self._start_time
                    return self._state_time_elapsed > self._timeout

                def _remainder(self):
                    self._state_remainder = self._counter_remainder.pop(0)
                    return self._state_remainder

            loop_ender = LoopEnder(ansible_process, start_time, args.timeout)

            while loop_ender.keep_going():
                line, lines = "", []
                try:
                    while line is not None:
                        logger.debug("queue size: %s", queue.qsize())
                        line = queue.get(block=False)
                        lines.append(line)
                        queue.task_done()
                        logger.debug(
                            "got_from_queue: [%s]: %s", type(line), bytes(line, "utf8")
                        )
                except Empty:
                    logger.debug("Queue: Empty exception caught.")
                else:
                    logger.debug("Queue: No exceptions caught.")

                for line in lines:
                    logger.info(line.rstrip())
                    ansible_output += line
                else:
                    time.sleep(0.1)

            try:
                stdout_output, error_data = ansible_process.communicate()
                ansible_output += stdout_output
                return_code = ansible_process.returncode
            except subprocess.TimeoutExpired:
                return_code = None

        except ShutdownException as e:
            logger.error(
                "Ansible Pull result: Interrupted. PID[%s]", ansible_process.pid
            )
            kill_softly(ansible_process)
            sys.exit(e.signal)
        else:
            if return_code is None:
                logger.error(
                    "Ansible Pull result: Timeout (%s seconds). PID[%s]",
                    args.timeout,
                    ansible_process.pid,
                )
                kill_softly(ansible_process)
            else:
                logger.info(
                    "Ansible Pull result: %s. PID[%s]. Return code: %s",
                    "Success" if return_code == 0 else "Failed",
                    ansible_process.pid,
                    ansible_process.returncode,
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

        sensu_status = SENSU_OK if ansible_process.returncode == 0 else SENSU_CRITICAL

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

        return_code = ansible_process.returncode

        first_run = False

    sys.exit(return_code)


def enqueue_output(out, queue):
    logger.debug("enqueue_output: type(out): %s", type(out))

    try:
        first_time = True

        for line in iter(out.readline, ""):
            clean_line = line.rstrip()
            if first_time:
                logger.debug(
                    "Logging Thread[%s] First time queueing output...", os.getpid()
                )
                first_time = False

            logger.debug(
                "Logging Thread[%s] queueing (size=%s) output: [%s] '%s'",
                os.getpid(),
                queue.qsize(),
                type(clean_line),
                bytes(clean_line, "utf8"),
            )
            queue.put(clean_line)

    except ShutdownException:
        logger.info("Received `ShutdownException`, ending enqueue_output() loop")
    finally:
        logger.debug("Logging Thread[%s] Ran out of output, quitting...", os.getpid())
