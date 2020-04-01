import argparse
import os
import sys


def get_args():
    parser = argparse.ArgumentParser(description="Runs Ansible Pull.")

    class OSPathExpandUserAction(argparse.Action):
        def __call__(self, _parser, _args, values, option_string=None):
            setattr(_args, self.dest, os.path.expanduser(values))

    store_expanduser = OSPathExpandUserAction

    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="Set the log level to DEBUG instead of INFO. [False]",
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Do a dry-run without doing anything. " + "[False]",
    )

    parser.add_argument(
        "--timeout",
        dest="timeout",
        action="store",
        default=1200,
        type=int,
        help="Ansible Pull run timeout in seconds. " + "[1200]",
    )

    parser.add_argument(
        "--playbook-path",
        dest="playbook_path",
        action="store",
        type=str,
        required=True,
        help=(
            "The path to the Ansible playbook to run, relative to the root"
            + " of the Git repository."
        ),
    )

    parser.add_argument(
        "--git-repo-url",
        dest="git_repo_url",
        action="store",
        type=str,
        required=True,
        help="The Git repository URL to pull from.",
    )

    parser.add_argument(
        "--directory",
        dest="work_dir",
        action=store_expanduser,
        type=str,
        default="/var/lib/ansible/local",
        help="The working directory to store files. " + "[/var/lib/ansible/local]",
    )

    parser.add_argument(
        "--vault-password-file",
        dest="vault_pass_file",
        action=store_expanduser,
        type=str,
        default=None,
        help="The Ansible Vault password file. " + "[None]",
    )

    parser.add_argument(
        "--checkout",
        dest="branch",
        action=store_expanduser,
        type=str,
        default=None,
        help="The branch to check out." + "[None]",
    )

    parser.add_argument(
        "--log-file",
        dest="log_file",
        action=store_expanduser,
        type=str,
        default=sys.stdout,
        help="The file to log to. " + "[stdout]",
    )

    parser.add_argument(
        "--tags",
        dest="tags",
        action="store",
        type=str,
        default=None,
        help="The tags to send to Ansible. " + "[None]",
    )

    parser.add_argument(
        "--notify-sensu",
        dest="notify_sensu",
        action="store_true",
        default=False,
        help="Specify whether to notify Sensu or not. " + "[False]",
    )

    return parser.parse_args()
