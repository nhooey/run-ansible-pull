import inspect
import os
import unittest
import yaml

from datetime import timedelta

from run_ansible_pull.ansible import get_ansible_result
from run_ansible_pull.sensu import format_sensu_summary


class RunAnsiblePullTestCase(unittest.TestCase):
    """Test run_ansible_pull"""

    def setUp(self):
        test_data_path = os.path.join(
            os.path.dirname(inspect.getfile(inspect.currentframe())), "test_data.yaml"
        )

        with open(test_data_path) as f:
            self.test_data = yaml.safe_load(f)

    def test_sensu_summaries(self):
        """Ensure generated Sensu Ansible summaries are correct"""

        for item in self.test_data["ansible_pull_logs"]:
            ansible_summary = get_ansible_result(item["log"])
            sensu_summary = format_sensu_summary(
                ansible_summary, timedelta(seconds=item["runtime"]),
            )

            self.assertEqual(sensu_summary, item["summary"].rstrip())


if __name__ == "__main__":
    unittest.main()
