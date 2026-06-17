"""Integration tests for CLI command functions."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from homelab_vm_provisioner import cli

from .helpers import completed_process

# Module-level patchers to prevent actual system calls
_require_tools_patcher = None
_run_patcher = None


def setUpModule():
    """Patch system calls at module level to prevent actual execution."""
    global _require_tools_patcher, _run_patcher
    # Mock require_tools on cli module where it's imported
    _require_tools_patcher = patch.object(cli, 'require_tools', return_value=None)
    _require_tools_patcher.start()
    # Mock run on cli module where it's imported
    _run_patcher = patch.object(cli, 'run', return_value=completed_process(0, ""))
    _run_patcher.start()


def tearDownModule():
    """Stop module-level patches."""
    global _require_tools_patcher, _run_patcher
    if _require_tools_patcher:
        _require_tools_patcher.stop()
    if _run_patcher:
        _run_patcher.stop()


class StartCommandTests(unittest.TestCase):
    """Tests for the start command."""

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "reconcile_networking")
    @patch.object(cli, "is_libvirt_nat_network")
    @patch.object(cli, "start_vm_domain")
    @patch("builtins.print")
    def test_starts_stopped_vm(self, mock_print, mock_start, mock_is_nat, mock_reconcile, mock_load, mock_lock):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm"}
        mock_is_nat.return_value = False
        mock_start.return_value = True
        
        cli.start("test-vm")
        
        mock_start.assert_called_once_with("test-vm")
        self.assertTrue(any("Started VM" in str(call) for call in mock_print.call_args_list))

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "reconcile_networking")
    @patch.object(cli, "is_libvirt_nat_network")
    @patch.object(cli, "current_domain_state")
    @patch.object(cli, "start_vm_domain")
    @patch("builtins.print")
    def test_reports_already_running_vm(self, mock_print, mock_start, mock_state, mock_is_nat, mock_reconcile, mock_load, mock_lock):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm"}
        mock_is_nat.return_value = False
        mock_state.return_value = "running"
        mock_start.return_value = False
        
        cli.start("test-vm")
        
        # When already running, start_vm_domain returns False so no "Started VM" message
        self.assertFalse(any("Started VM" in str(call) for call in mock_print.call_args_list))


class StopCommandTests(unittest.TestCase):
    """Tests for the stop command."""

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "reconcile_networking")
    @patch.object(cli, "is_libvirt_nat_network")
    @patch.object(cli, "stop_vm_domain")
    @patch("builtins.print")
    def test_stops_running_vm(self, mock_print, mock_stop, mock_is_nat, mock_reconcile, mock_load, mock_lock):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm"}
        mock_is_nat.return_value = False
        mock_stop.return_value = True
        
        cli.stop("test-vm")
        
        mock_stop.assert_called_once_with("test-vm")
        self.assertTrue(any("Stopped VM" in str(call) for call in mock_print.call_args_list))

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "reconcile_networking")
    @patch.object(cli, "is_libvirt_nat_network")
    @patch.object(cli, "stop_vm_domain")
    @patch("builtins.print")
    def test_reports_already_stopped_vm(self, mock_print, mock_stop, mock_is_nat, mock_reconcile, mock_load, mock_lock):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm"}
        mock_is_nat.return_value = False
        mock_stop.return_value = False
        
        cli.stop("test-vm")
        
        # When already stopped, stop_vm_domain returns False so no "Stopped VM" message
        self.assertFalse(any("Stopped VM" in str(call) for call in mock_print.call_args_list))


class DestroyCommandTests(unittest.TestCase):
    """Tests for the destroy command."""

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "merged_vm_network")
    @patch.object(cli, "cleanup_vm_runtime_definition")
    @patch.object(cli, "cleanup_local_vm_artifacts")
    @patch.object(cli, "is_libvirt_nat_network", return_value=True)
    @patch.object(cli, "reconcile_networking")
    def test_destroys_vm(
        self, mock_reconcile, mock_is_nat, mock_cleanup_local, mock_cleanup_runtime, 
        mock_network, mock_load, mock_lock
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {
            "vm_name": "test-vm",
            "admin_private_key": "/keys/test.key",
            "vm_data_dir": "/vm/test-vm",
            "ports": []
        }
        mock_network.return_value = {"name": "test-net", "mode": "nat"}
        
        cli.destroy("test-vm")
        
        mock_cleanup_runtime.assert_called_once()
        mock_cleanup_local.assert_called_once()
        mock_reconcile.assert_called_once_with(policy_only=True)

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "merged_vm_network")
    @patch.object(cli, "cleanup_vm_runtime_definition")
    @patch.object(cli, "cleanup_local_vm_artifacts")
    @patch.object(cli, "is_libvirt_nat_network", return_value=False)
    def test_destroys_vm_without_nat_network(
        self, mock_is_nat, mock_cleanup_local, mock_cleanup_runtime, 
        mock_network, mock_load, mock_lock
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {
            "vm_name": "test-vm",
            "admin_private_key": "/keys/test.key",
            "vm_data_dir": "/vm/test-vm",
            "ports": []
        }
        mock_network.return_value = {"name": "test-net", "mode": "bridge"}
        
        cli.destroy("test-vm")
        
        mock_cleanup_runtime.assert_called_once()
        mock_cleanup_local.assert_called_once()


class SnapshotCreateTests(unittest.TestCase):
    """Tests for snapshot_create command."""

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "vm_exists", return_value=True)
    @patch.object(cli, "stop_vm_domain", return_value=True)
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_image_artifact")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "vm_data_dir_for_config")
    @patch.object(cli, "copy_local_tree")
    @patch.object(cli, "resolved_config_assets", return_value={})
    @patch.object(cli, "snapshot_metadata_path")
    @patch.object(cli, "chown_path_to_current_user")
    @patch.object(cli, "start_vm_domain")
    @patch("builtins.print")
    def test_creates_snapshot_of_running_vm(
        self, mock_print, mock_start, mock_chown, mock_meta_path, mock_assets,
        mock_copy_tree, mock_vm_data_dir, mock_state_file, mock_copy_file,
        mock_copy_artifact, mock_copy_qcow2, mock_stop, mock_exists,
        mock_seed_path, mock_disk_path, mock_snapshot_path, mock_snapshot_id,
        mock_global_config, mock_load_config, mock_resolve_config, mock_load, mock_lock
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm", "config_path": "/configs/test.yaml"}
        mock_resolve_config.return_value = Path("/configs/test.yaml")
        mock_load_config.return_value = {}
        mock_global_config.return_value = {}
        mock_snapshot_id.return_value = "20260616T120000Z"
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = False
        snapshot_path_mock.__truediv__ = lambda self, other: Mock(spec=Path)
        mock_snapshot_path.return_value = snapshot_path_mock
        mock_disk_path.return_value = Mock(exists=Mock(return_value=True))
        mock_seed_path.return_value = Mock(exists=Mock(return_value=False))
        mock_state_file.return_value = Mock(exists=Mock(return_value=False))
        mock_vm_data_dir.return_value = Mock(exists=Mock(return_value=False))
        mock_meta_path.return_value = Mock(write_text=Mock())
        
        cli.snapshot_create("test-vm")
        
        mock_stop.assert_called_once_with("test-vm")
        mock_start.assert_called_once_with("test-vm")
        mock_print.assert_called_with("Created restore point 20260616T120000Z for test-vm")

    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "vm_exists", return_value=True)
    @patch.object(cli, "stop_vm_domain", return_value=False)
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "vm_data_dir_for_config")
    @patch.object(cli, "resolved_config_assets", return_value={})
    @patch.object(cli, "snapshot_metadata_path")
    @patch.object(cli, "chown_path_to_current_user")
    @patch("builtins.print")
    def test_creates_snapshot_without_restarting_stopped_vm(
        self, mock_print, mock_chown, mock_meta_path, mock_assets,
        mock_vm_data_dir, mock_state_file, mock_copy_file,
        mock_copy_qcow2, mock_stop, mock_exists,
        mock_seed_path, mock_disk_path, mock_snapshot_path, mock_snapshot_id,
        mock_global_config, mock_load_config, mock_resolve_config, mock_load, mock_lock
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load.return_value = {"vm_name": "test-vm", "config_path": "/configs/test.yaml"}
        mock_resolve_config.return_value = Path("/configs/test.yaml")
        mock_load_config.return_value = {}
        mock_global_config.return_value = {}
        mock_snapshot_id.return_value = "20260616T120000Z"
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = False
        snapshot_path_mock.__truediv__ = lambda self, other: Mock(spec=Path)
        mock_snapshot_path.return_value = snapshot_path_mock
        mock_disk_path.return_value = Mock(exists=Mock(return_value=True))
        mock_seed_path.return_value = Mock(exists=Mock(return_value=False))
        mock_state_file.return_value = Mock(exists=Mock(return_value=False))
        mock_vm_data_dir.return_value = Mock(exists=Mock(return_value=False))
        mock_meta_path.return_value = Mock(write_text=Mock())
        
        cli.snapshot_create("test-vm")
        
        mock_stop.assert_called_once_with("test-vm")
        mock_print.assert_called_with("Created restore point 20260616T120000Z for test-vm")


class SnapshotRestoreTests(unittest.TestCase):
    """Tests for snapshot_restore command."""

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_snapshot_metadata")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "merged_vm_network")
    @patch.object(cli, "cleanup_vm_runtime_definition")
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_image_artifact")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "load_config")
    @patch.object(cli, "restored_network_config")
    @patch.object(cli, "save_vm_state")
    @patch.object(cli, "ensure_host_services")
    @patch.object(cli, "create_nat_network")
    @patch.object(cli, "virt_install")
    @patch.object(cli, "stop_vm_domain")
    @patch.object(cli, "apply_runtime_networking")
    @patch.object(cli, "load_global_config", return_value={})
    @patch.object(cli, "image_settings_for_config", return_value={"os_variant": "debian11"})
    @patch("builtins.print")
    def test_restores_snapshot(
        self, mock_print, mock_image_settings, mock_global, mock_apply, mock_stop, 
        mock_virt, mock_create_nat, mock_ensure, mock_save, mock_restored_net, 
        mock_load_config, mock_state_file, mock_copy_file, mock_seed_path, 
        mock_disk_path, mock_copy_artifact, mock_copy_qcow2, mock_cleanup, 
        mock_merged_net, mock_load_state, mock_lock, mock_snapshot_path, 
        mock_load_metadata, mock_require
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        
        mock_load_metadata.return_value = {
            "snapshot_id": "20260616T120000Z",
            "vm_name": "test-vm",
            "original_paths": {
                "config_path": "/configs/test.yaml",
                "state_path": "/states/test.yaml"
            },
            "assets": {}
        }
        
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.__truediv__ = lambda self, other: Mock(spec=Path, exists=Mock(return_value=True))
        mock_snapshot_path.return_value = snapshot_path_mock
        
        mock_load_state.return_value = {"vm_name": "test-vm", "ports": []}
        mock_merged_net.return_value = {"mode": "nat", "name": "test-net"}
        mock_disk_path.return_value = Path("/vm/test-vm/disk.qcow2")
        mock_seed_path.return_value = Path("/vm/test-vm/seed.iso")
        mock_state_file.return_value = Path("/states/test.yaml")
        mock_load_config.return_value = {"vm": {}}
        mock_restored_net.return_value = {"mode": "nat", "name": "test-net"}
        
        cli.snapshot_restore("test-vm", "20260616T120000Z")
        
        mock_copy_qcow2.assert_called_once()
        mock_virt.assert_called_once()
        mock_print.assert_called_with("Restored test-vm from restore point 20260616T120000Z")

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_snapshot_metadata")
    @patch.object(cli, "snapshot_path_for_vm")
    def test_raises_error_when_snapshot_disk_not_found(
        self, mock_snapshot_path, mock_load_metadata, mock_require
    ):
        mock_load_metadata.return_value = {"snapshot_id": "20260616T120000Z"}
        
        snapshot_path_mock = Mock(spec=Path)
        
        def truediv_side_effect(other):
            result = Mock(spec=Path)
            if "qcow2" in other:
                result.exists.return_value = False
            else:
                result.exists.return_value = True
            return result
        
        snapshot_path_mock.__truediv__ = truediv_side_effect
        mock_snapshot_path.return_value = snapshot_path_mock
        
        with self.assertRaisesRegex(FileNotFoundError, "Snapshot disk was not found"):
            cli.snapshot_restore("test-vm", "20260616T120000Z")


class SnapshotDeleteTests(unittest.TestCase):
    """Tests for snapshot_delete command."""

    @patch.object(cli, "snapshot_path_for_vm")
    @patch("shutil.rmtree")
    @patch("builtins.print")
    def test_deletes_snapshot(self, mock_print, mock_rmtree, mock_snapshot_path):
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = True
        mock_snapshot_path.return_value = snapshot_path_mock
        
        cli.snapshot_delete("test-vm", "20260616T120000Z")
        
        mock_rmtree.assert_called_once_with(snapshot_path_mock)
        mock_print.assert_called_with("Deleted restore point 20260616T120000Z for test-vm")

    @patch.object(cli, "snapshot_path_for_vm")
    def test_raises_error_when_snapshot_not_found(self, mock_snapshot_path):
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = False
        mock_snapshot_path.return_value = snapshot_path_mock
        
        with self.assertRaisesRegex(FileNotFoundError, "Snapshot not found"):
            cli.snapshot_delete("test-vm", "20260616T120000Z")


class CurrentDomainStateTests(unittest.TestCase):
    """Tests for current_domain_state helper."""

    @patch.object(cli, "capture_or_none")
    def test_returns_running_state(self, mock_capture):
        mock_capture.return_value = "running"
        self.assertEqual(cli.current_domain_state("test-vm"), "running")

    @patch.object(cli, "capture_or_none")
    def test_returns_shut_off_state(self, mock_capture):
        mock_capture.return_value = "shut off"
        self.assertEqual(cli.current_domain_state("test-vm"), "shut off")

    @patch.object(cli, "capture_or_none")
    def test_returns_none_for_nonexistent_vm(self, mock_capture):
        mock_capture.return_value = None
        self.assertIsNone(cli.current_domain_state("nonexistent"))


class SnapshotPathHelpersTests(unittest.TestCase):
    """Tests for snapshot path helper functions."""

    def test_snapshot_root_for_vm_uses_global_config(self):
        global_config = {"paths": {"snapshot_dir": "/custom/snapshots"}}
        result = cli.snapshot_root_for_vm("test-vm", global_config=global_config)
        self.assertEqual(result, Path("/custom/snapshots/test-vm"))

    @patch.object(cli, "default_snapshot_root")
    @patch.object(cli, "load_global_config")
    def test_snapshot_root_for_vm_uses_default_when_not_configured(
        self, mock_load_global, mock_default
    ):
        mock_load_global.return_value = {}
        mock_default.return_value = Path("/default/snapshots")
        result = cli.snapshot_root_for_vm("test-vm")
        self.assertEqual(result, Path("/default/snapshots/test-vm"))

    @patch.object(cli, "snapshot_root_for_vm")
    def test_snapshot_path_for_vm(self, mock_snapshot_root):
        mock_snapshot_root.return_value = Path("/snapshots/test-vm")
        result = cli.snapshot_path_for_vm("test-vm", "20260616_120000")
        self.assertEqual(result, Path("/snapshots/test-vm/20260616_120000"))

    def test_snapshot_metadata_path(self):
        result = cli.snapshot_metadata_path(Path("/snapshots/test-vm/20260616_120000"))
        self.assertEqual(result, Path("/snapshots/test-vm/20260616_120000/metadata.yaml"))


class ListSnapshotsTests(unittest.TestCase):
    """Tests for list_snapshots function."""

    @patch.object(cli, "snapshot_root_for_vm")
    @patch("pathlib.Path.exists")
    def test_returns_empty_list_when_no_snapshot_dir(self, mock_exists, mock_snapshot_root):
        mock_snapshot_root.return_value = Path("/snapshots/test-vm")
        mock_exists.return_value = False
        result = cli.list_snapshots("test-vm")
        self.assertEqual(result, [])

    @patch.object(cli, "snapshot_root_for_vm")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.read_text")
    @patch("yaml.safe_load")
    def test_returns_sorted_snapshot_dirs(self, mock_yaml, mock_read, mock_glob, mock_exists, mock_snapshot_root):
        mock_snapshot_root.return_value = Path("/snapshots/test-vm")
        
        # Create mock Path objects for metadata files
        mock_meta1 = Mock(spec=Path)
        mock_meta1.parent = Mock()
        mock_meta1.parent.name = "20260615T100000Z"
        mock_meta1.__lt__ = lambda self, other: True  # Make sortable
        
        mock_meta2 = Mock(spec=Path)
        mock_meta2.parent = Mock()
        mock_meta2.parent.name = "20260616T120000Z"
        mock_meta2.__lt__ = lambda self, other: False  # Make sortable
        
        mock_glob.return_value = [mock_meta1, mock_meta2]  # Already sorted
        mock_yaml.side_effect = [
            {"snapshot_id": "20260615T100000Z", "created_at": "2026-06-15T10:00:00Z"},
            {"snapshot_id": "20260616T120000Z", "created_at": "2026-06-16T12:00:00Z"}
        ]
        
        result = cli.list_snapshots("test-vm")
        
        # Should return sorted list of snapshot dicts (reverse chronological order)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["snapshot_id"], "20260616T120000Z")  # Newer first
        self.assertEqual(result[1]["snapshot_id"], "20260615T100000Z")


class LoadSetupScriptContentTests(unittest.TestCase):
    """Tests for load_setup_script_content helper."""

    @patch.object(cli, "resolve_setup_script_path")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.read_text", return_value="#!/bin/bash\necho test")
    def test_loads_setup_script_content(self, mock_read, mock_exists, mock_resolve):
        mock_resolve.return_value = Path("/scripts/setup.sh")
        config_data = {"scripts": {"setup_script_file": "setup.sh"}}
        global_config = {}
        
        result = cli.load_setup_script_content(config_data, global_config)
        
        self.assertEqual(result, "#!/bin/bash\necho test\n")
        mock_resolve.assert_called_once_with("setup.sh", global_config=global_config)

    @patch.object(cli, "resolve_setup_script_path")
    def test_returns_none_when_no_setup_script_path(self, mock_resolve):
        mock_resolve.return_value = None
        result = cli.load_setup_script_content({}, {})
        self.assertIsNone(result)


class CopyLocalFileAndTreeTests(unittest.TestCase):
    """Tests for copy_local_file and copy_local_tree helpers."""

    @patch("pathlib.Path.mkdir")
    @patch("shutil.copy2")
    def test_copy_local_file(self, mock_copy, mock_mkdir):
        cli.copy_local_file(Path("/source/file.txt"), Path("/target/file.txt"))
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_copy.assert_called_once_with(Path("/source/file.txt"), Path("/target/file.txt"))

    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("shutil.copytree")
    def test_copy_local_tree(self, mock_copytree, mock_mkdir, mock_exists):
        cli.copy_local_tree(Path("/source/dir"), Path("/target/dir"))
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_copytree.assert_called_once_with(
            Path("/source/dir"), Path("/target/dir")
        )


class ChownPathToCurrentUserTests(unittest.TestCase):
    """Tests for chown_path_to_current_user helper."""

    @patch("os.getuid", return_value=1000)
    @patch("os.getgid", return_value=1000)
    @patch.object(cli, "run")
    def test_chowns_path_to_current_user(self, mock_run, mock_getgid, mock_getuid):
        cli.chown_path_to_current_user(Path("/some/path"))
        mock_run.assert_called_once_with(
            ["chown", "-R", "1000:1000", "/some/path"], sudo=True
        )


class CurrentSnapshotIdTests(unittest.TestCase):
    """Tests for current_snapshot_id helper."""

    @patch.object(cli, "datetime")
    def test_returns_timestamp_id(self, mock_datetime):
        from datetime import datetime, timezone
        mock_datetime.now.return_value = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = cli.current_snapshot_id()
        self.assertEqual(result, "20260616T120000Z")


class MergedVmNetworkTests(unittest.TestCase):
    """Tests for merged_vm_network helper."""

    @patch.object(cli, "is_libvirt_nat_network", return_value=False)
    @patch.object(cli, "discover_vm_network")
    def test_merges_discovered_network_with_state(self, mock_discover, mock_is_nat):
        mock_discover.return_value = {"discovered_ip": "192.168.1.10"}
        state = {
            "network": {"name": "test-net", "mac": "52:54:00:11:22:33"}
        }
        result = cli.merged_vm_network("test-vm", state)
        expected = {
            "name": "test-net",
            "mac": "52:54:00:11:22:33",
            "discovered_ip": "192.168.1.10"
        }
        self.assertEqual(result, expected)


class PrintCreateSummaryTests(unittest.TestCase):
    """Tests for print_create_summary helper."""

    @patch("builtins.print")
    def test_prints_vm_summary_with_ports(self, mock_print):
        network = {"mode": "nat", "vm_ip": "192.168.1.10", "cidr": "192.168.1.0/24"}
        ports = [{"host": 8080, "guest": 80}, {"host": 2222, "guest": 22}]
        
        cli.print_create_summary(
            "test-vm",
            "testuser",
            "untrusted",
            network,
            "/keys/test_vm_ed25519",
            ports
        )
        
        printed = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("test-vm", printed)
        self.assertIn("testuser", printed)
        self.assertIn("192.168.1.10", printed)
        self.assertIn("2222", printed)  # SSH port, not the HTTP port

    @patch("builtins.print")
    def test_prints_vm_summary_without_ports(self, mock_print):
        network = {"mode": "bridge", "vm_ip": "192.168.1.10"}
        
        cli.print_create_summary(
            "test-vm",
            "testuser",
            "trusted",
            network,
            "/keys/test_vm_ed25519",
            []
        )
        
        printed = "\n".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("test-vm", printed)
        self.assertIn("trusted", printed)


class EnsureHostServicesTests(unittest.TestCase):
    """Tests for ensure_host_services helper."""

    @patch.object(cli, "run")
    def test_ensures_libvirtd_is_running(self, mock_run):
        cli.ensure_host_services()
        mock_run.assert_called_once_with(
            ["systemctl", "enable", "--now", "libvirtd"], sudo=True
        )


class SnapshotCreateDetailedTests(unittest.TestCase):
    """Detailed tests for snapshot_create covering complex paths."""

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "stop_vm_domain")
    @patch.object(cli, "vm_exists")
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_image_artifact")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "vm_data_dir_for_config")
    @patch.object(cli, "copy_local_tree")
    @patch.object(cli, "resolved_config_assets")
    @patch.object(cli, "chown_path_to_current_user")
    @patch.object(cli, "start_vm_domain")
    @patch("builtins.print")
    def test_creates_snapshot_with_all_assets(
        self,
        mock_print,
        mock_start,
        mock_chown,
        mock_assets,
        mock_copy_tree,
        mock_vm_data_dir,
        mock_state_file,
        mock_copy_file,
        mock_copy_artifact,
        mock_copy_qcow2,
        mock_vm_exists,
        mock_stop,
        mock_lock,
        mock_seed_path,
        mock_disk_path,
        mock_snapshot_path,
        mock_snapshot_id,
        mock_global,
        mock_load_config,
        mock_resolve,
        mock_load_state,
        mock_require,
    ):
        # Setup mocks
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        
        mock_state = {
            "config_path": "/configs/test-vm.yaml",
            "vm_data_dir": "/vm-data/test-vm",
            "admin_private_key": "/keys/test-vm_admin_ed25519",
        }
        mock_load_state.return_value = mock_state
        
        mock_resolve.return_value = Path("/configs/test-vm.yaml")
        mock_load_config.return_value = {"vm": {"name": "test-vm"}, "scripts": {"setup_script_file": "/scripts/setup.sh"}}
        mock_global.return_value = {}
        mock_snapshot_id.return_value = "20260616_120000"
        
        snapshot_path = Path("/snapshots/test-vm/20260616_120000")
        mock_snapshot_path.return_value = snapshot_path
        
        disk_path = Path("/vm-data/test-vm/disk.qcow2")
        mock_disk_path.return_value = disk_path
        
        seed_path = Path("/vm-data/test-vm/seed.iso")
        mock_seed_path.return_value = seed_path
        
        mock_vm_exists.return_value = True
        mock_stop.return_value = True  # VM was running
        
        mock_state_file.return_value = Path("/states/test-vm.yaml")
        mock_vm_data_dir.return_value = Path("/vm-data/test-vm")
        
        mock_assets.return_value = {
            "setup_script": Path("/scripts/setup.sh")
        }
        
        # Mock Path.exists and Path.mkdir
        with patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.mkdir"), \
             patch("pathlib.Path.write_text"):
            
            mock_exists.return_value = True
            
            cli.snapshot_create("test-vm")
        
        # Verify VM was stopped and restarted
        mock_stop.assert_called_once_with("test-vm")
        mock_start.assert_called_once_with("test-vm")
        
        # Verify disk snapshot
        mock_copy_qcow2.assert_called_once()
        
        # Verify seed ISO snapshot
        mock_copy_artifact.assert_called_once()
        
        # Verify config and state copied
        self.assertGreaterEqual(mock_copy_file.call_count, 2)
        
        # Verify vm-data directory copied
        mock_copy_tree.assert_called_once()
        
        # Verify ownership fixed
        mock_chown.assert_called_once()
        
        # Verify success message
        self.assertTrue(any("Created restore point" in str(call) for call in mock_print.call_args_list))

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_vm_state")
    def test_raises_error_when_no_config_path_in_state(self, mock_load_state, mock_require):
        mock_load_state.return_value = {"vm_name": "test-vm"}
        
        with self.assertRaisesRegex(FileNotFoundError, "No saved config path"):
            cli.snapshot_create("test-vm")

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    def test_raises_error_when_disk_not_found(
        self,
        mock_disk_path,
        mock_snapshot_path,
        mock_snapshot_id,
        mock_global,
        mock_load_config,
        mock_resolve,
        mock_load_state,
        mock_require,
    ):
        mock_load_state.return_value = {"config_path": "/configs/test-vm.yaml"}
        mock_resolve.return_value = Path("/configs/test-vm.yaml")
        mock_load_config.return_value = {"vm": {"name": "test-vm"}}
        mock_global.return_value = {}
        mock_snapshot_id.return_value = "20260616_120000"
        mock_snapshot_path.return_value = Path("/snapshots/test-vm/20260616_120000")
        
        # Return a mock Path with exists() returning False
        disk_path_mock = Mock(spec=Path)
        disk_path_mock.exists.return_value = False
        mock_disk_path.return_value = disk_path_mock
        
        with self.assertRaisesRegex(FileNotFoundError, "VM disk was not found"):
            cli.snapshot_create("test-vm")

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "vm_exists", return_value=False)
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "vm_data_dir_for_config")
    @patch.object(cli, "resolved_config_assets", return_value={})
    @patch.object(cli, "snapshot_metadata_path")
    @patch("shutil.rmtree")
    def test_cleans_up_snapshot_on_error(
        self,
        mock_rmtree,
        mock_meta_path,
        mock_assets,
        mock_vm_data_dir,
        mock_state_file,
        mock_copy_file,
        mock_copy_qcow2,
        mock_vm_exists,
        mock_lock,
        mock_seed_path,
        mock_disk_path,
        mock_snapshot_path,
        mock_snapshot_id,
        mock_global,
        mock_load_config,
        mock_resolve,
        mock_load_state,
        mock_require,
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        
        mock_load_state.return_value = {"config_path": "/configs/test-vm.yaml"}
        mock_resolve.return_value = Path("/configs/test-vm.yaml")
        mock_load_config.return_value = {}
        mock_global.return_value = {}
        mock_snapshot_id.return_value = "20260616T120000Z"
        
        # Create mock snapshot path
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = True
        snapshot_path_mock.mkdir = Mock()
        snapshot_path_mock.__truediv__ = lambda self, other: Mock(spec=Path)
        mock_snapshot_path.return_value = snapshot_path_mock
        
        # Create mock disk path with exists=True
        disk_path_mock = Mock(spec=Path)
        disk_path_mock.exists.return_value = True
        mock_disk_path.return_value = disk_path_mock
        
        # Create mock seed path with exists=False
        seed_path_mock = Mock(spec=Path)
        seed_path_mock.exists.return_value = False
        mock_seed_path.return_value = seed_path_mock
        
        # Mock state_file and vm_data_dir to not exist
        mock_state_file.return_value = Mock(exists=Mock(return_value=False))
        mock_vm_data_dir.return_value = Mock(exists=Mock(return_value=False))
        
        # Mock snapshot_metadata_path
        mock_meta_path.return_value = Mock(write_text=Mock())
        
        # Make copy_qcow2_image raise an error
        mock_copy_qcow2.side_effect = RuntimeError("Copy failed")
        
        with self.assertRaisesRegex(RuntimeError, "Copy failed"):
            cli.snapshot_create("test-vm")
        
        # Verify cleanup was called
        mock_rmtree.assert_called_once_with(snapshot_path_mock, ignore_errors=True)

    @patch.object(cli, "require_tools")
    @patch.object(cli, "load_vm_state")
    @patch.object(cli, "resolve_config_path")
    @patch.object(cli, "load_config")
    @patch.object(cli, "load_global_config")
    @patch.object(cli, "current_snapshot_id")
    @patch.object(cli, "snapshot_path_for_vm")
    @patch.object(cli, "vm_disk_path")
    @patch.object(cli, "seed_iso_path")
    @patch.object(cli, "host_lifecycle_lock")
    @patch.object(cli, "vm_exists", return_value=False)
    @patch.object(cli, "copy_qcow2_image")
    @patch.object(cli, "copy_local_file")
    @patch.object(cli, "state_file_for_vm")
    @patch.object(cli, "vm_data_dir_for_config")
    @patch.object(cli, "resolved_config_assets", return_value={})
    @patch.object(cli, "snapshot_metadata_path")
    @patch.object(cli, "chown_path_to_current_user")
    @patch("builtins.print")
    def test_handles_missing_seed_iso(
        self,
        mock_print,
        mock_chown,
        mock_meta_path,
        mock_assets,
        mock_vm_data_dir,
        mock_state_file,
        mock_copy_file,
        mock_copy_qcow2,
        mock_vm_exists,
        mock_lock,
        mock_seed_path,
        mock_disk_path,
        mock_snapshot_path,
        mock_snapshot_id,
        mock_global,
        mock_load_config,
        mock_resolve,
        mock_load_state,
        mock_require,
    ):
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        
        mock_load_state.return_value = {"config_path": "/configs/test-vm.yaml"}
        mock_resolve.return_value = Path("/configs/test-vm.yaml")
        mock_load_config.return_value = {}
        mock_global.return_value = {}
        mock_snapshot_id.return_value = "20260616T120000Z"
        
        # Create mock snapshot path
        snapshot_path_mock = Mock(spec=Path)
        snapshot_path_mock.exists.return_value = False
        snapshot_path_mock.mkdir = Mock()
        snapshot_path_mock.__truediv__ = lambda self, other: Mock(spec=Path)
        mock_snapshot_path.return_value = snapshot_path_mock
        
        # Disk exists
        disk_path_mock = Mock(spec=Path)
        disk_path_mock.exists.return_value = True
        mock_disk_path.return_value = disk_path_mock
        
        # Seed does NOT exist
        seed_path_mock = Mock(spec=Path)
        seed_path_mock.exists.return_value = False
        mock_seed_path.return_value = seed_path_mock
        
        # State file and vm data dir don't exist
        mock_state_file.return_value = Mock(exists=Mock(return_value=False))
        mock_vm_data_dir.return_value = Mock(exists=Mock(return_value=False))
        
        # Metadata path
        mock_meta_path.return_value = Mock(write_text=Mock())
        
        cli.snapshot_create("test-vm")
        
        # Verify snapshot was created successfully
        mock_print.assert_called_with("Created restore point 20260616T120000Z for test-vm")
        self.assertTrue(any("Created restore point" in str(call) for call in mock_print.call_args_list))


class ResolvedConfigAssetsTests(unittest.TestCase):
    """Tests for resolved_config_assets helper."""

    @patch.object(cli, "resolve_setup_script_path")
    def test_returns_empty_dict_when_no_assets(self, mock_resolve_script):
        mock_resolve_script.return_value = None
        
        result = cli.resolved_config_assets({}, {})
        
        self.assertEqual(result, {})

    @patch.object(cli, "resolve_setup_script_path")
    def test_includes_setup_script_when_present(self, mock_resolve_script):
        mock_resolve_script.return_value = Path("/scripts/setup.sh")
        
        result = cli.resolved_config_assets(
            {"scripts": {"setup_script_file": "/scripts/setup.sh"}},
            {}
        )
        
        self.assertEqual(result["setup_script_file"], Path("/scripts/setup.sh"))

    @patch.object(cli, "resolve_setup_script_path")
    @patch.object(cli, "resolve_user_key_path")
    def test_includes_user_key_when_present(self, mock_resolve_key, mock_resolve_script):
        mock_resolve_script.return_value = None
        mock_resolve_key.return_value = Path("/keys/user.pub")
        
        result = cli.resolved_config_assets(
            {"vm": {"ssh_key_file": "/keys/user.pub"}},
            {}
        )
        
        self.assertEqual(result["ssh_key_file"], Path("/keys/user.pub"))
