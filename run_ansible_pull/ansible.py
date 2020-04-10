import itertools
import json
import re


def get_ansible_cmd(
    work_dir,
    repo_url,
    vault_pass_file,
    extra_vars,
    tags,
    only_if_changed,
    playbook_path,
    branch,
    inventory,
    connection,
):
    ansible_command_filtered = filter(
        None,
        [
            ["ansible-pull"],
            ["--inventory", inventory] if inventory else [],
            ["--directory", work_dir],
            ["--url", repo_url],
            ["--vault-password-file", vault_pass_file] if vault_pass_file else [],
            ["--extra-vars", extra_vars] if extra_vars else [],
            ["--checkout", branch],
            ["--inventory", inventory] if inventory else [],
            ["--connection", connection] if connection else [],
            ["--accept-host-key"],
            ["--tags", tags] if tags else [],
            ["--only-if-changed"] if only_if_changed else [],
            [playbook_path],
        ],
    )

    # Flatten
    return list(itertools.chain(*ansible_command_filtered))


def get_ansible_result(ansible_log):
    """Creates a play recap message from the one matched in the Ansible log"""
    m_git_result = re.search(pattern_git_result, ansible_log)
    m_play_recap = re.search(pattern_play_recap, ansible_log)
    m_play_failure = re.search(pattern_play_failure, ansible_log)

    result = dict()

    if m_git_result:
        grp = m_git_result.group
        success = True if str(grp("result")).lower().startswith("success") else False
        result["success"] = success

        parse_error = None
        json_dict = dict()
        try:
            json_dict = json.loads(str(grp("json")))
        except ValueError as e:
            parse_error = "(Failed to parse Ansible Git result JSON: %s)" % e

        success = True if json_dict.get("failed") == "true" else False
        changed = True if json_dict.get("changed") == "true" else False
        before = json_dict.get("before")
        after = json_dict.get("after")
        msg = json_dict.get("msg")

        result["git_result"] = {
            "host": grp("host"),
            "success": success,
            "changed": changed,
            "before": before,
            "after": after,
            "msg": clean_json_msg(msg),
        }

        if parse_error:
            result["git_result"]["parse_error"] = parse_error

    if m_play_failure:
        grp = m_play_failure.group
        try:
            task_dict = json.loads(grp("task_result_json"))
        except json.JSONDecodeError as e:
            task_dict = {
                "failure": "(Failed to parse Ansible task result JSON: %s)" % e
            }
        else:
            if task_dict.get("msg"):
                task_dict["msg"] = clean_json_msg(task_dict["msg"])

        result["play_failure"] = {
            "role_and_task_names": grp("role_and_task_names"),
            "task_dict": task_dict,
            "exception": grp("task_exception"),
        }

    if m_play_recap:
        grp = m_play_recap.group

        result["play_recap"] = {
            "host": grp("host"),
            "ok_count": int(grp("ok_count")),
            "changed_count": int(grp("changed_count")),
            "unreachable_count": int(grp("unreachable_count")),
            "failed_count": int(grp("failed_count")),
        }

    return result


def clean_json_msg(msg):
    return msg.replace("\n", "\\n") if msg else msg


pattern_play_recap = re.compile(
    r"^PLAY RECAP \*+\n(?P<host>\w+)\s+:\s+" + r"ok=(?P<ok_count>[0-9]+)\s+"
    r"changed=(?P<changed_count>[0-9]+)\s+"
    + r"unreachable=(?P<unreachable_count>[0-9]+)\s+"
    + r"failed=(?P<failed_count>[0-9]+)\s*$",
    flags=re.MULTILINE,
)

pattern_play_failure = re.compile(
    r"^TASK\s+\[(?P<role_and_task_names>[^\]]+)\]"
    + r"\s+\*+\s*\n\s*"
    + r"(:?An exception occurred.* The error was: (?P<task_exception>.+?)\n\s*)?"
    + r"(:?fatal|failed):\s+.*?"
    + r"\s+=>\s+(?P<task_result_json>{.*})\s*"
    + r"\n\s*(?!\.\.\.ignoring)",
    flags=re.MULTILINE,
)

pattern_git_result = re.compile(
    r"^(?P<host>\w+) \| (?P<result>\w+!?)"
    + r"\s+=>\s+(?P<json>{\s*\n(:?.*\n)*\s*}\s*$)",
    flags=re.MULTILINE,
)
