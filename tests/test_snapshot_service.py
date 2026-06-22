"""Tests for homelab_vm_provisioner.snapshot_service module."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from homelab_vm_provisioner.snapshot_service import (
    current_snapshot_id,
    snapshot_path_for_vm,
    snapshot_root_for_vm,
)


class CurrentSnapshotIdTest(unittest.TestCase):
    """Test current_snapshot_id generates unique IDs."""

    def test_generates_timestamp_id(self):
        """Should generate snapshot ID with timestamp format."""
        snapshot_id = current_snapshot_id()
        # Format: YYYYMMDD-HHMMSS
        self.assertRegex(snapshot_id, r"^\d{8}-\d{6}$")

    def test_generates_different_ids(self):
        """Should generate different IDs when called multiple times."""
        id1 = current_snapshot_id()
        id2 = current_snapshot_id()
        # IDs might be same if called in same second, but format should be valid
        self.assertRegex(id1, r"^\d{8}-\d{6}$")
        self.assertRegex(id2, r"^\d{8}-\d{6}$")


class SnapshotRootForVmTest(unittest.TestCase):
    """Test snapshot_root_for_vm returns correct path."""

    @patch("homelab_vm_provisioner.snapshot_service.default_snapshot_root")
    def test_returns_vm_snapshot_directory(self, mock_default_root):
        """Should return snapshot root for specific VM."""
        mock_default_root.return_value = Path("/var/lib/snapshots")

        result = snapshot_root_for_vm("test-vm")

        self.assertEqual(result, Path("/var/lib/snapshots/test-vm"))
        mock_default_root.assert_called_once_with(None)

    @patch("homelab_vm_provisioner.snapshot_service.default_snapshot_root")
    def test_uses_global_config(self, mock_default_root):
        """Should pass global config to default_snapshot_root."""
        mock_default_root.return_value = Path("/custom/snapshots")
        global_config = {"snapshots": {"root": "/custom/snapshots"}}

        result = snapshot_root_for_vm("demo", global_config=global_config)

        self.assertEqual(result, Path("/custom/snapshots/demo"))
        mock_default_root.assert_called_once_with(global_config)


class SnapshotPathForVmTest(unittest.TestCase):
    """Test snapshot_path_for_vm returns correct path."""

    @patch("homelab_vm_provisioner.snapshot_service.default_snapshot_root")
    def test_returns_full_snapshot_path(self, mock_default_root):
        """Should return full path to specific snapshot."""
        mock_default_root.return_value = Path("/var/lib/snapshots")

        result = snapshot_path_for_vm("test-vm", "20240101-120000")

        self.assertEqual(result, Path("/var/lib/snapshots/test-vm/20240101-120000"))

    @patch("homelab_vm_provisioner.snapshot_service.default_snapshot_root")
    def test_handles_nested_paths(self, mock_default_root):
        """Should handle nested snapshot paths correctly."""
        mock_default_root.return_value = Path("/root/vm/snapshots")

        result = snapshot_path_for_vm("my-vm", "snap-123")

        self.assertEqual(result, Path("/root/vm/snapshots/my-vm/snap-123"))




class SnapshotRestoreRecordDataTest(unittest.TestCase):
    """Test snapshot_restore_record_data restores snapshots."""

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_metadata_not_dict(self, mock_require):
        """Should raise ValueError when metadata is not a dict."""
        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        with self.assertRaises(ValueError) as ctx:
            snapshot_restore_record_data("test-vm", "snap-1", "invalid")
        self.assertIn("metadata mapping", str(ctx.exception))

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_config_snapshot_missing(self, mock_require):
        """Should raise ValueError when config_snapshot is missing."""
        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        metadata = {"artifact_manifest": {}}

        with self.assertRaises(ValueError) as ctx:
            snapshot_restore_record_data("test-vm", "snap-1", metadata)
        self.assertIn("config_snapshot", str(ctx.exception))

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_snapshot_disk_not_found(self, mock_require):
        """Should raise FileNotFoundError when snapshot disk doesn't exist."""
        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        metadata = {
            "config_snapshot": {"vm": {"name": "test"}},
            "artifact_manifest": {"disk": "/nonexistent/disk.qcow2"},
        }

        with self.assertRaises(FileNotFoundError) as ctx:
            snapshot_restore_record_data("test-vm", "snap-1", metadata)
        self.assertIn("Snapshot disk was not found", str(ctx.exception))

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_snapshot_seed_not_found(self, mock_require):
        """Should raise FileNotFoundError when snapshot seed doesn't exist."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        disk_path = Mock(spec=Path)
        disk_path.exists.return_value = True
        seed_path = Mock(spec=Path)
        seed_path.exists.return_value = False

        with patch("homelab_vm_provisioner.snapshot_service.Path") as mock_path:
            mock_path.side_effect = [disk_path, seed_path]

            metadata = {
                "config_snapshot": {"vm": {"name": "test"}},
                "artifact_manifest": {
                    "disk": "/snapshots/disk.qcow2",
                    "seed_iso": "/snapshots/seed.iso",
                },
            }

            with self.assertRaises(FileNotFoundError) as ctx:
                snapshot_restore_record_data("test-vm", "snap-1", metadata)
            self.assertIn("Snapshot seed ISO was not found", str(ctx.exception))


class SnapshotDeleteRecordDataTest(unittest.TestCase):
    """Test snapshot_delete_record_data deletes snapshot artifacts."""

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_metadata_not_dict(self, mock_require):
        """Should raise ValueError when metadata is not a dict."""
        from homelab_vm_provisioner.snapshot_service import (
            snapshot_delete_record_data,
        )

        with self.assertRaises(ValueError) as ctx:
            snapshot_delete_record_data("test-vm", "snap-1", "invalid")
        self.assertIn("metadata mapping", str(ctx.exception))

    @patch("homelab_vm_provisioner.system.require_tools")
    def test_raises_when_snapshot_path_missing(self, mock_require):
        """Should raise ValueError when snapshot_path is missing."""
        from homelab_vm_provisioner.snapshot_service import (
            snapshot_delete_record_data,
        )

        metadata = {"artifact_manifest": {}}

        with self.assertRaises(ValueError) as ctx:
            snapshot_delete_record_data("test-vm", "snap-1", metadata)
        self.assertIn("snapshot_path", str(ctx.exception))

    @patch("homelab_vm_provisioner.snapshot_service.shutil")
    @patch("homelab_vm_provisioner.system.require_tools")
    def test_deletes_snapshot_directory(self, mock_require, mock_shutil):
        """Should delete snapshot directory when it exists."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import (
            snapshot_delete_record_data,
        )

        snapshot_path = Mock(spec=Path)
        snapshot_path.exists.return_value = True

        metadata = {
            "artifact_manifest": {"snapshot_path": "/var/lib/snapshots/vm/snap-1"}
        }

        with patch("homelab_vm_provisioner.snapshot_service.Path", return_value=snapshot_path):
            result = snapshot_delete_record_data("test-vm", "snap-1", metadata)

        mock_shutil.rmtree.assert_called_once_with(snapshot_path)
        self.assertTrue(result["deleted"])
        self.assertEqual(result["snapshot_id"], "snap-1")
        self.assertEqual(result["vm_name"], "test-vm")

    @patch("homelab_vm_provisioner.snapshot_service.shutil")
    @patch("homelab_vm_provisioner.system.require_tools")
    def test_handles_nonexistent_snapshot_directory(self, mock_require, mock_shutil):
        """Should handle nonexistent snapshot directory gracefully."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import (
            snapshot_delete_record_data,
        )

        snapshot_path = Mock(spec=Path)
        snapshot_path.exists.return_value = False

        metadata = {
            "artifact_manifest": {"snapshot_path": "/var/lib/snapshots/vm/snap-1"}
        }

        with patch("homelab_vm_provisioner.snapshot_service.Path", return_value=snapshot_path):
            result = snapshot_delete_record_data("test-vm", "snap-1", metadata)

        mock_shutil.rmtree.assert_not_called()
        self.assertTrue(result["deleted"])


class CopyLocalFileTest(unittest.TestCase):
    """Test copy_local_file delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.copy_local_file")
    def test_delegates_to_cli_copy_local_file(self, mock_cli_copy):
        """Should delegate to CLI copy_local_file function."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import copy_local_file

        mock_cli_copy.return_value = None
        src = Path("/tmp/source.txt")
        dst = Path("/tmp/dest.txt")

        copy_local_file(src, dst)

        mock_cli_copy.assert_called_once_with(src, dst)


class CopyLocalTreeTest(unittest.TestCase):
    """Test copy_local_tree delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.copy_local_tree")
    def test_delegates_to_cli_copy_local_tree(self, mock_cli_copy_tree):
        """Should delegate to CLI copy_local_tree function."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import copy_local_tree

        mock_cli_copy_tree.return_value = None
        src = Path("/tmp/source-dir")
        dst = Path("/tmp/dest-dir")

        copy_local_tree(src, dst)

        mock_cli_copy_tree.assert_called_once_with(src, dst)


class ChownPathToCurrentUserTest(unittest.TestCase):
    """Test chown_path_to_current_user delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.chown_path_to_current_user")
    def test_delegates_to_cli_chown(self, mock_cli_chown):
        """Should delegate to CLI chown_path_to_current_user function."""
        from pathlib import Path

        from homelab_vm_provisioner.snapshot_service import (
            chown_path_to_current_user,
        )

        mock_cli_chown.return_value = None
        path = Path("/tmp/test")

        chown_path_to_current_user(path)

        mock_cli_chown.assert_called_once_with(path)


class RestoredNetworkConfigTest(unittest.TestCase):
    """Test restored_network_config delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.restored_network_config")
    def test_delegates_to_cli_restored_network_config(self, mock_cli_restored):
        """Should delegate to CLI restored_network_config function."""
        from homelab_vm_provisioner.snapshot_service import (
            restored_network_config,
        )

        mock_cli_restored.return_value = {"mode": "nat"}
        runtime_state = {"network": {"mode": "nat"}}
        config_snapshot = {"vm": {"name": "test-vm"}}

        result = restored_network_config("test-vm", runtime_state, config_snapshot)

        mock_cli_restored.assert_called_once_with("test-vm", runtime_state, config_snapshot)
        self.assertEqual(result, {"mode": "nat"})


class CleanupVmRuntimeDefinitionTest(unittest.TestCase):
    """Test cleanup_vm_runtime_definition delegates to workflows function."""

    @patch("homelab_vm_provisioner.service_workflows.cleanup_vm_runtime_definition")
    def test_delegates_to_workflows_cleanup(self, mock_workflows_cleanup):
        """Should delegate to service_workflows cleanup function."""
        from homelab_vm_provisioner.snapshot_service import (
            cleanup_vm_runtime_definition,
        )

        mock_workflows_cleanup.return_value = None
        network = {"mode": "nat"}
        ports = [{"host": 2222, "guest": 22}]

        cleanup_vm_runtime_definition("test-vm", network, ports, remove_storage=True)

        mock_workflows_cleanup.assert_called_once_with("test-vm", network, ports, True)


class ApplyRuntimeNetworkingTest(unittest.TestCase):
    """Test apply_runtime_networking delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.apply_runtime_networking")
    def test_delegates_to_cli_apply_runtime_networking(self, mock_cli_apply):
        """Should delegate to CLI apply_runtime_networking function."""
        from homelab_vm_provisioner.snapshot_service import (
            apply_runtime_networking,
        )

        mock_cli_apply.return_value = None
        network = {"mode": "nat"}
        ports = [{"host": 2222, "guest": 22}]
        state = {"vm_name": "test-vm"}

        apply_runtime_networking("test-vm", network, "trusted", ports, state)

        mock_cli_apply.assert_called_once_with("test-vm", network, "trusted", ports, state)


class EnsureHostServicesTest(unittest.TestCase):
    """Test ensure_host_services delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.ensure_host_services")
    def test_delegates_to_cli_ensure_host_services(self, mock_cli_ensure):
        """Should delegate to CLI ensure_host_services function."""
        from homelab_vm_provisioner.snapshot_service import ensure_host_services

        mock_cli_ensure.return_value = None

        ensure_host_services()

        mock_cli_ensure.assert_called_once()


if __name__ == "__main__":
    unittest.main()

    """Integration test for snapshot_restore_record_data covering main workflow."""

    @patch("homelab_vm_provisioner.snapshot_service.start_vm_domain")
    @patch("homelab_vm_provisioner.snapshot_service.apply_runtime_networking")
    @patch("homelab_vm_provisioner.snapshot_service.virt_install")
    @patch("homelab_vm_provisioner.snapshot_service.reconcile_networking")
    @patch("homelab_vm_provisioner.snapshot_service.ensure_host_services")
    @patch("homelab_vm_provisioner.snapshot_service.restored_network_config")
    @patch("homelab_vm_provisioner.cli.copy_local_file")
    @patch("homelab_vm_provisioner.cli.copy_local_tree")
    @patch("homelab_vm_provisioner.snapshot_service.copy_image_artifact")
    @patch("homelab_vm_provisioner.snapshot_service.copy_qcow2_image")
    @patch("homelab_vm_provisioner.snapshot_service.cleanup_vm_runtime_definition")
    @patch("homelab_vm_provisioner.snapshot_service.merged_vm_network")
    @patch("homelab_vm_provisioner.snapshot_service.load_vm_state")
    @patch("homelab_vm_provisioner.snapshot_service.host_lifecycle_lock")
    @patch("homelab_vm_provisioner.snapshot_service.resolve_state_artifact_path")
    @patch("homelab_vm_provisioner.snapshot_service.seed_iso_path")
    @patch("homelab_vm_provisioner.snapshot_service.vm_disk_path")
    @patch("homelab_vm_provisioner.system.require_tools")
    def test_restores_snapshot_with_seed_and_vm_data(
        self,
        mock_require,
        mock_disk_path,
        mock_seed_path,
        mock_resolve,
        mock_lock,
        mock_load_state,
        mock_merged_network,
        mock_cleanup,
        mock_copy_qcow2,
        mock_copy_artifact,
        mock_copy_tree,
        mock_copy_file,
        mock_restored_network,
        mock_ensure_host,
        mock_reconcile,
        mock_virt_install,
        mock_apply_networking,
        mock_start,
    ):
        """Should restore snapshot with all artifacts and restart if source was running."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        # Setup mocks
        snapshot_disk = MagicMock(spec=Path)
        snapshot_disk.exists.return_value = True
        snapshot_seed = MagicMock(spec=Path)
        snapshot_seed.exists.return_value = True
        snapshot_vm_data = MagicMock(spec=Path)
        snapshot_vm_data.exists.return_value = True
        snapshot_keys = MagicMock(spec=Path)
        snapshot_keys.exists.return_value = True
        snapshot_key_path = MagicMock(spec=Path)
        snapshot_key_path.exists.return_value = True
        snapshot_pub_path = MagicMock(spec=Path)
        snapshot_pub_path.exists.return_value = True

        mock_disk_path.return_value = Path("/var/lib/vms/test-vm.qcow2")
        mock_seed_path.return_value = Path("/var/lib/vms/test-vm-seed.iso")
        mock_resolve.side_effect = lambda p: Path(p) if isinstance(p, str) else p
        mock_lock.return_value.__enter__ = lambda _: None
        mock_lock.return_value.__exit__ = lambda *_: None
        mock_load_state.return_value = {
            "network": {"mode": "nat"},
            "ports": [{"host": 2222, "guest": 22}],
        }
        mock_merged_network.return_value = {"mode": "nat"}
        mock_restored_network.return_value = {"mode": "nat", "network_group_id": None}

        metadata = {
            "config_snapshot": {
                "vm": {"name": "test-vm", "trust": "trusted"},
                "ports": [{"host": 2222, "guest": 22}],
            },
            "runtime_state_snapshot": {
                "vm_name": "test-vm",
                "vm_data_dir": "/var/lib/vms/vm-data",
                "vcpus": 4,
                "memory_mb": 4096,
                "os_variant": "ubuntu22.04",
                "ports": [{"host": 2222, "guest": 22}],
                "trust": "trusted",
            },
            "artifact_manifest": {
                "disk": str(snapshot_disk),
                "seed_iso": str(snapshot_seed),
                "vm_data_dir": str(snapshot_vm_data),
                "keys_dir": str(snapshot_keys),
            },
            "local_artifacts": {
                "admin_private_key": "/var/lib/keys/test_admin_ed25519",
            },
            "source_was_running": True,
        }

        # Mock Path creation
        with patch("homelab_vm_provisioner.snapshot_service.Path") as mock_path_cls:
            mock_path_cls.side_effect = lambda p: {
                str(snapshot_disk): snapshot_disk,
                str(snapshot_seed): snapshot_seed,
                str(snapshot_vm_data): snapshot_vm_data,
                str(snapshot_keys): snapshot_keys,
            }.get(str(p), MagicMock(spec=Path, exists=lambda: False))
            
            # Also need to mock the keys directory structure
            def resolve_side_effect(p):
                if isinstance(p, str) and "keys" in p:
                    mock_key = MagicMock(spec=Path)
                    mock_key.name = "test_admin_ed25519"
                    return mock_key
                elif isinstance(p, str):
                    return Path(p)
                return p
            
            mock_resolve.side_effect = resolve_side_effect
            
            # Mock the snapshot keys directory / operations
            def path_div_side_effect(name):
                if name == "test_admin_ed25519":
                    return snapshot_key_path
                elif name == "test_admin_ed25519.pub":
                    return snapshot_pub_path
                return MagicMock(spec=Path, exists=lambda: False)
            
            snapshot_keys.__truediv__ = lambda _, name: path_div_side_effect(name)

            result = snapshot_restore_record_data("test-vm", "snap-1", metadata)

        # Verify operations
        mock_cleanup.assert_called_once()
        mock_copy_qcow2.assert_called_once()
        mock_copy_artifact.assert_called_once()
        mock_copy_tree.assert_called_once()
        mock_copy_file.assert_called()
        mock_ensure_host.assert_called_once()
        mock_virt_install.assert_called_once()
        mock_apply_networking.assert_called_once()
        mock_start.assert_called_once_with("test-vm")
        self.assertEqual(result, metadata)

    @patch("homelab_vm_provisioner.snapshot_service.start_vm_domain")
    @patch("homelab_vm_provisioner.snapshot_service.apply_runtime_networking")
    @patch("homelab_vm_provisioner.snapshot_service.virt_install")
    @patch("homelab_vm_provisioner.snapshot_service.reconcile_networking_records")
    @patch("homelab_vm_provisioner.snapshot_service.ensure_host_services")
    @patch("homelab_vm_provisioner.snapshot_service.restored_network_config")
    @patch("homelab_vm_provisioner.cli.copy_local_file")
    @patch("homelab_vm_provisioner.cli.copy_local_tree")
    @patch("homelab_vm_provisioner.snapshot_service.copy_image_artifact")
    @patch("homelab_vm_provisioner.snapshot_service.copy_qcow2_image")
    @patch("homelab_vm_provisioner.snapshot_service.cleanup_vm_runtime_definition")
    @patch("homelab_vm_provisioner.snapshot_service.merged_vm_network")
    @patch("homelab_vm_provisioner.snapshot_service.load_vm_state")
    @patch("homelab_vm_provisioner.snapshot_service.host_lifecycle_lock")
    @patch("homelab_vm_provisioner.snapshot_service.resolve_state_artifact_path")
    @patch("homelab_vm_provisioner.snapshot_service.seed_iso_path")
    @patch("homelab_vm_provisioner.snapshot_service.vm_disk_path")
    @patch("homelab_vm_provisioner.system.require_tools")
    def test_restores_snapshot_with_network_group_and_vm_records(
        self,
        mock_require,
        mock_disk_path,
        mock_seed_path,
        mock_resolve,
        mock_lock,
        mock_load_state,
        mock_merged_network,
        mock_cleanup,
        mock_copy_qcow2,
        mock_copy_artifact,
        mock_copy_tree,
        mock_copy_file,
        mock_restored_network,
        mock_ensure_host,
        mock_reconcile_records,
        mock_virt_install,
        mock_apply_networking,
        mock_start,
    ):
        """Should restore snapshot with network_group_id and call reconcile_networking_records."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from homelab_vm_provisioner.snapshot_service import (
            snapshot_restore_record_data,
        )

        snapshot_disk = MagicMock(spec=Path, exists=lambda: True)
        snapshot_disk.exists.return_value = True

        mock_disk_path.return_value = Path("/var/lib/vms/test-vm.qcow2")
        mock_seed_path.return_value = Path("/var/lib/vms/test-vm-seed.iso")
        mock_lock.return_value.__enter__ = lambda _: None
        mock_lock.return_value.__exit__ = lambda *_: None
        mock_load_state.return_value = {"network": {}, "ports": []}
        mock_merged_network.return_value = {}
        mock_restored_network.return_value = {"network_group_id": "group-123"}

        metadata = {
            "config_snapshot": {"vm": {"name": "test-vm"}},
            "runtime_state_snapshot": {
                "vcpus": 2,
                "memory_mb": 2048,
                "ports": [],
            },
            "artifact_manifest": {"disk": str(snapshot_disk)},
            "source_was_running": False,
        }

        with patch("homelab_vm_provisioner.snapshot_service.Path", return_value=snapshot_disk):
            result = snapshot_restore_record_data(
                "test-vm",
                "snap-1",
                metadata,
                vm_records=[{"name": "test-vm"}],
                network_groups=[{"id": "group-123"}],
            )

        self.assertIsNotNone(result)
        mock_reconcile_records.assert_called_once()
        mock_start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
