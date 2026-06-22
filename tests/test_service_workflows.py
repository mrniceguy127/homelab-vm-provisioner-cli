"""Tests for homelab_vm_provisioner.service_workflows module."""

import unittest
from unittest.mock import Mock, patch

from homelab_vm_provisioner.service_workflows import (
    is_libvirt_nat_network,
    validate_vm_name,
)


class ValidateVmNameTest(unittest.TestCase):
    """Test validate_vm_name checks name length."""

    def test_valid_name(self):
        """Valid VM names should not raise."""
        validate_vm_name("test-vm")
        validate_vm_name("my-vm-123")
        validate_vm_name("a" * 63)

    def test_too_long_name_raises(self):
        """VM names longer than 63 characters should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            validate_vm_name("a" * 64)
        self.assertIn("63 characters", str(ctx.exception))

    def test_empty_name_is_valid(self):
        """Empty name should not raise (validated elsewhere)."""
        validate_vm_name("")


class IsLibvirtNatNetworkTest(unittest.TestCase):
    """Test is_libvirt_nat_network helper."""

    def test_nat_mode_returns_true(self):
        """Network with mode=nat should return True."""
        self.assertTrue(is_libvirt_nat_network({"mode": "nat"}))

    def test_nat_custom_mode_returns_true(self):
        """Network with mode=nat-custom should return True."""
        self.assertTrue(is_libvirt_nat_network({"mode": "nat-custom"}))

    def test_bridge_mode_returns_false(self):
        """Network with mode=bridge should return False."""
        self.assertFalse(is_libvirt_nat_network({"mode": "bridge"}))

    def test_no_mode_returns_false(self):
        """Network without mode key should return False."""
        self.assertFalse(is_libvirt_nat_network({}))

    def test_none_mode_returns_false(self):
        """Network with mode=None should return False."""
        self.assertFalse(is_libvirt_nat_network({"mode": None}))




class RenderSeedIsoForDefinitionTest(unittest.TestCase):
    """Test render_seed_iso_for_definition creates seed ISO."""

    @patch("homelab_vm_provisioner.service_workflows.create_seed_iso")
    @patch("homelab_vm_provisioner.service_workflows.render_templates")
    def test_renders_and_creates_seed_iso(self, mock_render, mock_create_iso):
        """Should render templates and create seed ISO."""
        from pathlib import Path

        from homelab_vm_provisioner.service_workflows import (
            render_seed_iso_for_definition,
        )

        mock_render.return_value = ("user_data_content", "meta_data_content")
        mock_create_iso.return_value = Path("/tmp/seed.iso")

        definition = {
            "vm_name": "test-vm",
            "render_context": {"vm_user": "testuser"},
            "template": "base",
            "vm_data_dir": Path("/tmp/vm-data"),
        }

        result = render_seed_iso_for_definition(definition)

        mock_render.assert_called_once_with(
            {"vm_user": "testuser"}, "base", Path("/tmp/vm-data")
        )
        mock_create_iso.assert_called_once_with("test-vm", "user_data_content", "meta_data_content")
        self.assertEqual(result, Path("/tmp/seed.iso"))


class CloneFromDefinitionTest(unittest.TestCase):
    """Test clone_from_definition validation."""

    @patch("homelab_vm_provisioner.service_workflows.vm_exists")
    def test_raises_when_target_same_as_source(self, mock_exists):
        """Should raise ValueError when target name equals source name."""
        from homelab_vm_provisioner.service_workflows import (
            clone_from_definition,
        )

        definition = {"vm_name": "same-vm", "vm": {"name": "same-vm"}}

        with self.assertRaises(ValueError) as ctx:
            clone_from_definition("same-vm", definition)
        self.assertIn("different vm.name", str(ctx.exception))

    @patch("homelab_vm_provisioner.service_workflows.vm_exists")
    def test_raises_when_source_not_found(self, mock_exists):
        """Should raise FileNotFoundError when source VM doesn't exist."""
        from homelab_vm_provisioner.service_workflows import (
            clone_from_definition,
        )

        mock_exists.return_value = False
        definition = {"vm_name": "target-vm", "vm": {"name": "target-vm"}}

        with self.assertRaises(FileNotFoundError) as ctx:
            clone_from_definition("source-vm", definition)
        self.assertIn("Source VM not found", str(ctx.exception))

    @patch("homelab_vm_provisioner.service_workflows.vm_exists")
    def test_raises_when_target_already_exists(self, mock_exists):
        """Should raise RuntimeError when target VM already exists."""
        from homelab_vm_provisioner.service_workflows import (
            clone_from_definition,
        )

        mock_exists.side_effect = [True, True]  # source exists, target exists
        definition = {"vm_name": "target-vm", "vm": {"name": "target-vm"}}

        with self.assertRaises(RuntimeError) as ctx:
            clone_from_definition("source-vm", definition)
        self.assertIn("Target VM already exists", str(ctx.exception))


class StartVmTest(unittest.TestCase):
    """Test start_vm starts existing VM with networking."""

    @patch("homelab_vm_provisioner.service_workflows.start_vm_domain")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking")
    @patch("homelab_vm_provisioner.service_workflows.load_vm_state")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_starts_vm_with_network_group(
        self, mock_lock, mock_load_state, mock_reconcile, mock_start_domain
    ):
        """Should reconcile networking and start VM when network_group_id exists."""
        from homelab_vm_provisioner.service_workflows import start_vm

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load_state.return_value = {"network": {"network_group_id": "ng-1"}}

        start_vm("test-vm")

        mock_reconcile.assert_called_once()
        mock_start_domain.assert_called_once_with("test-vm")

    @patch("homelab_vm_provisioner.service_workflows.start_vm_domain")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking")
    @patch("homelab_vm_provisioner.service_workflows.load_vm_state")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_starts_vm_with_nat_network(
        self, mock_lock, mock_load_state, mock_reconcile, mock_start_domain
    ):
        """Should reconcile policy for NAT network and start VM."""
        from homelab_vm_provisioner.service_workflows import start_vm

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load_state.return_value = {"network": {"mode": "nat"}}

        start_vm("test-vm")

        mock_reconcile.assert_called_once_with(policy_only=True)
        mock_start_domain.assert_called_once_with("test-vm")

    @patch("homelab_vm_provisioner.service_workflows.start_vm_domain")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking")
    @patch("homelab_vm_provisioner.service_workflows.load_vm_state")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_starts_vm_without_networking(
        self, mock_lock, mock_load_state, mock_reconcile, mock_start_domain
    ):
        """Should start VM without reconciling when no network_group or NAT."""
        from homelab_vm_provisioner.service_workflows import start_vm

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_load_state.return_value = {"network": {"mode": "bridge"}}

        start_vm("test-vm")

        mock_reconcile.assert_not_called()
        mock_start_domain.assert_called_once_with("test-vm")


class StopVmTest(unittest.TestCase):
    """Test stop_vm stops running VM."""

    @patch("homelab_vm_provisioner.service_workflows.stop_vm_domain")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_stops_vm(self, mock_lock, mock_stop_domain):
        """Should stop VM domain."""
        from homelab_vm_provisioner.service_workflows import stop_vm

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()

        stop_vm("test-vm")

        mock_stop_domain.assert_called_once_with("test-vm")


class BuildNetworkArgTest(unittest.TestCase):
    """Test build_network_arg delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.build_network_arg")
    def test_delegates_to_cli_build_network_arg(self, mock_cli_build):
        """Should delegate to CLI build_network_arg function."""
        from homelab_vm_provisioner.service_workflows import build_network_arg

        mock_cli_build.return_value = "network=bridge,model=virtio"
        network = {"mode": "bridge"}

        result = build_network_arg("test-vm", network)

        mock_cli_build.assert_called_once_with("test-vm", network)
        self.assertEqual(result, "network=bridge,model=virtio")


class EnsureHostServicesWorkflowTest(unittest.TestCase):
    """Test ensure_host_services delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.ensure_host_services")
    def test_delegates_to_cli_ensure_host_services(self, mock_cli_ensure):
        """Should delegate to CLI ensure_host_services function."""
        from homelab_vm_provisioner.service_workflows import ensure_host_services

        mock_cli_ensure.return_value = None

        ensure_host_services()

        mock_cli_ensure.assert_called_once()


class ApplyRuntimeNetworkingWorkflowTest(unittest.TestCase):
    """Test apply_runtime_networking delegates to CLI function."""

    @patch("homelab_vm_provisioner.cli.apply_runtime_networking")
    def test_delegates_to_cli_apply_runtime_networking(self, mock_cli_apply):
        """Should delegate to CLI apply_runtime_networking function."""
        from homelab_vm_provisioner.service_workflows import (
            apply_runtime_networking,
        )

        mock_cli_apply.return_value = None
        network = {"mode": "nat"}
        ports = [{"host": 2222, "guest": 22}]
        state = {"vm_name": "test-vm"}

        apply_runtime_networking("test-vm", network, "trusted", ports, state)

        mock_cli_apply.assert_called_once_with("test-vm", network, "trusted", ports, state)


if __name__ == "__main__":
    unittest.main()

    """Integration test for create_from_definition covering main workflow."""

    @patch("homelab_vm_provisioner.service_workflows.apply_runtime_networking")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking_records")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking")
    @patch("homelab_vm_provisioner.service_workflows.ensure_host_services")
    @patch("homelab_vm_provisioner.service_workflows.virt_install")
    @patch("homelab_vm_provisioner.service_workflows.provision_vm")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_creates_vm_without_network_group(
        self,
        mock_lock,
        mock_provision,
        mock_virt_install,
        mock_ensure_host,
        mock_reconcile,
        mock_reconcile_records,
        mock_apply_networking,
    ):
        """Should create VM without network_group_id using reconcile_networking."""
        from pathlib import Path

        from homelab_vm_provisioner.service_workflows import (
            create_from_definition,
        )

        mock_lock.return_value.__enter__ = lambda _: None
        mock_lock.return_value.__exit__ = lambda *_: None
        mock_provision.return_value = (
            Path("/var/lib/vms/test-vm.qcow2"),
            Path("/var/lib/vms/test-vm-seed.iso"),
        )

        definition = {
            "vm": {"name": "test-vm", "vcpus": 2, "memory_mb": 2048, "trust": "trusted"},
            "os": {"variant": "ubuntu22.04"},
            "network": {"mode": "nat"},
            "ports": [{"host": 2222, "guest": 22}],
        }

        result = create_from_definition(definition)

        mock_provision.assert_called_once()
        mock_virt_install.assert_called_once()
        mock_ensure_host.assert_called_once()
        mock_reconcile.assert_called_once()
        mock_reconcile_records.assert_not_called()
        mock_apply_networking.assert_called_once()
        self.assertIsNotNone(result)
        self.assertIn("vm_name", result)
        self.assertEqual(result["vm_name"], "test-vm")

    @patch("homelab_vm_provisioner.service_workflows.apply_runtime_networking")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking_records")
    @patch("homelab_vm_provisioner.service_workflows.reconcile_networking")
    @patch("homelab_vm_provisioner.service_workflows.ensure_host_services")
    @patch("homelab_vm_provisioner.service_workflows.virt_install")
    @patch("homelab_vm_provisioner.service_workflows.provision_vm")
    @patch("homelab_vm_provisioner.service_workflows.host_lifecycle_lock")
    def test_creates_vm_with_network_group_and_vm_records(
        self,
        mock_lock,
        mock_provision,
        mock_virt_install,
        mock_ensure_host,
        mock_reconcile,
        mock_reconcile_records,
        mock_apply_networking,
    ):
        """Should create VM with network_group_id using reconcile_networking_records."""
        from pathlib import Path

        from homelab_vm_provisioner.service_workflows import (
            create_from_definition,
        )

        mock_lock.return_value.__enter__ = lambda _: None
        mock_lock.return_value.__exit__ = lambda *_: None
        mock_provision.return_value = (
            Path("/var/lib/vms/test-vm.qcow2"),
            Path("/var/lib/vms/test-vm-seed.iso"),
        )

        definition = {
            "vm": {"name": "test-vm", "vcpus": 2, "memory_mb": 2048},
            "os": {"variant": "ubuntu22.04"},
            "network": {"mode": "nat", "network_group_id": "group-123"},
            "ports": [],
        }

        result = create_from_definition(
            definition,
            vm_records=[{"name": "test-vm"}],
            network_groups=[{"id": "group-123"}],
        )

        self.assertIsNotNone(result)
        mock_reconcile_records.assert_called_once()
        mock_reconcile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
