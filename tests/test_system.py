import subprocess
import tempfile
import unittest
from unittest.mock import patch

from homelab_vm_provisioner import system

from .helpers import completed_process


class ToolExistsTests(unittest.TestCase):
    def test_returns_true_when_command_exists(self):
        with patch.object(system.shutil, "which", return_value="/usr/bin/virsh"):
            self.assertTrue(system.tool_exists("virsh"))

    def test_returns_false_when_command_is_missing(self):
        with patch.object(system.shutil, "which", return_value=None):
            self.assertFalse(system.tool_exists("virsh"))


class NormalizedCommandPathTests(unittest.TestCase):
    def test_appends_standard_system_paths(self):
        path_value = system.normalized_command_path("/custom/bin:/usr/bin")

        self.assertIn("/custom/bin", path_value.split(":"))
        self.assertIn("/usr/sbin", path_value.split(":"))
        self.assertIn("/sbin", path_value.split(":"))


class RunTests(unittest.TestCase):
    def test_runs_plain_command(self):
        with patch.object(system.subprocess, "run", return_value=completed_process()) as run_mock:
            result = system.run(["virsh", "list"])

        self.assertEqual(result.returncode, 0)
        run_mock.assert_called_once_with(["virsh", "list"], check=True, text=True)

    def test_runs_sudo_command(self):
        with patch.object(system.subprocess, "run", return_value=completed_process()) as run_mock:
            system.run(["virsh", "list"], sudo=True, check=False)

        run_mock.assert_called_once_with(["sudo", "virsh", "list"], check=False, text=True)


class CaptureTests(unittest.TestCase):
    def test_returns_stripped_output(self):
        with patch.object(
            system.subprocess,
            "check_output",
            return_value=" value\n",
        ) as output_mock:
            self.assertEqual(system.capture(["virsh", "list"]), "value")

        output_mock.assert_called_once_with(["virsh", "list"], text=True)

    def test_prefixes_sudo_when_requested(self):
        with patch.object(system.subprocess, "check_output", return_value="value") as output_mock:
            system.capture(["virsh", "list"], sudo=True)

        output_mock.assert_called_once_with(["sudo", "virsh", "list"], text=True)


class CaptureOrNoneTests(unittest.TestCase):
    def test_returns_output_on_success(self):
        with patch.object(system, "capture", return_value="value"):
            self.assertEqual(system.capture_or_none(["virsh"]), "value")

    def test_returns_none_on_called_process_error(self):
        with patch.object(
            system,
            "capture",
            side_effect=subprocess.CalledProcessError(1, ["virsh"]),
        ):
            self.assertIsNone(system.capture_or_none(["virsh"]))

    def test_returns_none_on_missing_command(self):
        with patch.object(system, "capture", side_effect=FileNotFoundError):
            self.assertIsNone(system.capture_or_none(["virsh"]))


class RequireToolsTests(unittest.TestCase):
    def test_returns_when_all_tools_exist(self):
        with patch.object(system, "tool_exists", return_value=True):
            self.assertIsNone(system.require_tools(["virsh", "wget"]))

    def test_exits_when_any_tool_is_missing(self):
        with patch.object(system, "tool_exists", side_effect=[True, False]), patch(
            "builtins.print"
        ) as print_mock:
            with self.assertRaises(SystemExit) as exc:
                system.require_tools(["virsh", "wget"])

        self.assertEqual(exc.exception.code, 1)
        self.assertEqual(print_mock.call_count, 3)

    def test_uses_default_required_tools_when_none_are_passed(self):
        with patch.object(system, "DEFAULT_REQUIRED_TOOLS", ("virsh",)), patch.object(
            system, "tool_exists", return_value=True
        ) as tool_exists_mock:
            self.assertIsNone(system.require_tools())

        tool_exists_mock.assert_called_once_with("virsh")


class VmLifecycleLockErrorTests(unittest.TestCase):
    def test_constructs_message_with_vm_name(self):
        err = system.VmLifecycleLockError("create", vm_name="demo")
        
        self.assertIn("create for demo", str(err))
        self.assertEqual(err.details["operation"], "create")
        self.assertEqual(err.details["vm_name"], "demo")

    def test_constructs_message_with_holder_operation(self):
        holder = {"operation": "destroy", "vm_name": "alpha"}
        err = system.VmLifecycleLockError("create", vm_name="demo", holder=holder)
        
        self.assertIn("destroy for alpha", str(err))

    def test_constructs_message_with_holder_operation_only(self):
        holder = {"operation": "snapshot"}
        err = system.VmLifecycleLockError("create", vm_name="demo", holder=holder)
        
        self.assertIn("snapshot", str(err))

    def test_constructs_message_without_holder(self):
        err = system.VmLifecycleLockError("create", vm_name="demo")
        
        self.assertIn("another lifecycle operation", str(err))


class LockHolderDetailsTests(unittest.TestCase):
    def test_returns_json_from_lock_file(self):
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as f:
            f.write('{"operation": "create", "vm_name": "demo"}')
            f.flush()
            f.seek(0)
            
            details = system._lock_holder_details(f)
            
            self.assertEqual(details["operation"], "create")
            self.assertEqual(details["vm_name"], "demo")

    def test_returns_none_for_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as f:
            f.flush()
            f.seek(0)
            
            details = system._lock_holder_details(f)
            
            self.assertIsNone(details)

    def test_returns_raw_for_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as f:
            f.write("not-json")
            f.flush()
            f.seek(0)
            
            details = system._lock_holder_details(f)
            
            self.assertEqual(details, {"raw": "not-json"})
