import json
import logging
from socket import socket

from run_ansible_pull.logger import logger_label

sensu_host = "localhost"
sensu_port = 3030

SENSU_OK = 0
SENSU_WARNING = 1
SENSU_CRITICAL = 2
SENSU_UNKNOWN = 3
SENSU_CUSTOM = 4

logger = logging.getLogger(logger_label)


def format_sensu_summary(ansible_result, runtime):
    git_failure = None
    if ansible_result.get("git_result"):
        x = ansible_result["git_result"]
        if not x["success"] and x.get("msg"):
            git_failure = 'Message: "%s"' % x["msg"]

    play_recap = None
    if ansible_result.get("play_recap"):
        x = ansible_result["play_recap"]
        play_recap = "[%s] ok: %s, changed: %s, unreachable: %s, failed: %s" % (
            x["host"],
            x["ok_count"],
            x["changed_count"],
            x["unreachable_count"],
            x["failed_count"],
        )

    # Don't register a Play failure if there is no failed count
    # This happens when fatal errors get ignored
    play_failure = None
    if (
        ansible_result.get("play_failure")
        and ansible_result["play_recap"]["failed_count"] > 0
    ):
        x = ansible_result["play_failure"]
        task_dict = x.get("task_dict")

        play_failure = (
            "[%s]" % x["role_and_task_names"]
            + (', Message: "%s"' % task_dict["msg"] if task_dict.get("msg") else "")
            + (', Exception: "%s"' % x["exception"] if x.get("exception") else "")
            + (
                ', Module STDERR: "%s"' % task_dict["module_stderr"]
                if task_dict.get("module_stderr")
                else ""
            )
        )

    summary_lines = [
        ("Git failed!: %s" % git_failure if git_failure else ""),
        ("Play failed!: %s" % play_failure if play_failure else ""),
        ("Play Recap: %s" % play_recap if play_recap else ""),
        ("Runtime: %s" % runtime if runtime is not None else ""),
    ]

    return "\n".join([line for line in summary_lines if line])


def send_sensu_event(status, summary, enabled=True):
    """Send the event to the Sensu server through a socket"""

    event = {
        "name": "ansible-pull",
        "status": status,
        "output": summary,
    }

    if enabled:
        logger.debug("Sending Sensu event: %s", event)
        success = False

        sock = socket()
        try:
            data = json.dumps(event) + "\n"
            sock.connect((sensu_host, sensu_port))
            sock.sendall(data.encode())
        except ConnectionRefusedError:
            logger.error(
                "Sending Sensu event failed: "
                + "Connection refused while connecting to socket %s:%s",
                sensu_host,
                sensu_port,
            )
            success = False
        except Exception as e:
            logger.error(
                "Sending Sensu event failed: " + "Exception: %s, Socket: %s:%s",
                e,
                sensu_host,
                sensu_port,
            )
        else:
            success = True
        finally:
            sock.close()
    else:
        logger.info("SKIPPING Sensu event: %s", event)
        success = True

    return success
