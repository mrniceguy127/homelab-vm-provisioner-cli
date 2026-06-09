import runpy
import sys
import unittest
from importlib import import_module
from unittest.mock import patch


class MainEntrypointTests(unittest.TestCase):
    def test_module_entrypoint_exits_with_cli_status(self):
        sys.modules.pop("homelab_vm_provisioner.__main__", None)

        with patch("homelab_vm_provisioner.cli.main", return_value=7) as main_mock:
            with self.assertRaises(SystemExit) as exc:
                runpy.run_module("homelab_vm_provisioner", run_name="__main__")

        self.assertEqual(exc.exception.code, 7)
        main_mock.assert_called_once_with()

    def test_importing___main___module_does_not_run_entrypoint(self):
        sys.modules.pop("homelab_vm_provisioner.__main__", None)

        with patch("homelab_vm_provisioner.cli.main") as main_mock:
            import_module("homelab_vm_provisioner.__main__")

        main_mock.assert_not_called()
