import logging

from run_ansible_pull.logger import logger_label

path_config = "/etc/run-ansible-pull"
path_git_branch = f"{path_config}/git-branch.txt"
path_git_branch_override = f"{path_config}/git-branch_override.txt"

logger = logging.getLogger(logger_label)


def get_git_branch(branch=None):
    if branch is None:
        git_branch = None

        try:
            with open(path_git_branch_override, "r") as f:
                git_branch = f.read().replace("\n", "")
            logger.info(
                "Using git branch: '%s', specified from file: '%s'",
                git_branch,
                path_git_branch_override,
            )
        except OSError:
            pass

        if git_branch is None:
            try:
                with open(path_git_branch, "r") as f:
                    git_branch = f.read().replace("\n", "")
                logger.info(
                    "Using git branch: '%s', specified from file: '%s'",
                    git_branch,
                    path_git_branch,
                )
            except OSError:
                pass

        if git_branch is None:
            git_branch = "master"
            logger.info(
                "No git branch specifiers found in files: '%s' or '%s', using default: '%s'",
                path_git_branch_override,
                path_git_branch,
                git_branch,
            )
    else:
        git_branch = branch

    return git_branch
