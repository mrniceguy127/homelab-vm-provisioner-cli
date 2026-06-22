"""Tests for homelab_vm_provisioner.service_mode module."""

import unittest
from unittest.mock import patch

from homelab_vm_provisioner.service_mode import (
    clone_vm,
    create_vm,
    destroy_vm,
    reconcile_vm_records,
    refresh_vm_runtime_state,
    start_vm,
    stop_vm,
)


class CreateVmTest(unittest.TestCase):
    """Test create_vm service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.create_from_definition")
    @patch("homelab_vm_provisioner.service_mode.prepare_vm_definition_from_config")
    def test_prepares_and_creates_vm(self, mock_prepare, mock_create):
        """Should prepare definition and create VM."""
        mock_definition = {"vm_name": "test-vm"}
        mock_prepare.return_value = mock_definition
        mock_create.return_value = mock_definition

        config_data = {"vm": {"name": "test-vm"}}
        result = create_vm(config_data)

        mock_prepare.assert_called_once_with(config_data, "<service>")
        mock_create.assert_called_once_with(mock_definition, reconcile_payload=None)
        self.assertEqual(result, mock_definition)

    @patch("homelab_vm_provisioner.service_mode.create_from_definition")
    @patch("homelab_vm_provisioner.service_mode.prepare_vm_definition_from_config")
    def test_passes_reconcile_payload(self, mock_prepare, mock_create):
        """Should pass reconcile_payload to create_from_definition."""
        mock_definition = {"vm_name": "test-vm"}
        mock_prepare.return_value = mock_definition
        mock_create.return_value = mock_definition

        config_data = {"vm": {"name": "test-vm"}}
        reconcile_payload = {"vm_records": [], "policy_only": True}
        create_vm(config_data, reconcile_payload=reconcile_payload)

        mock_create.assert_called_once_with(mock_definition, reconcile_payload=reconcile_payload)


class CloneVmTest(unittest.TestCase):
    """Test clone_vm service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.clone_from_definition")
    @patch("homelab_vm_provisioner.service_mode.prepare_vm_definition_from_config")
    def test_prepares_and_clones_vm(self, mock_prepare, mock_clone):
        """Should prepare definition and clone VM."""
        mock_definition = {"vm_name": "target-vm"}
        mock_prepare.return_value = mock_definition
        mock_clone.return_value = mock_definition

        config_data = {"vm": {"name": "target-vm"}}
        result = clone_vm("source-vm", config_data)

        mock_prepare.assert_called_once_with(config_data, "<service>")
        mock_clone.assert_called_once_with("source-vm", mock_definition, reconcile_payload=None)
        self.assertEqual(result, mock_definition)


class ReconcileVmRecordsTest(unittest.TestCase):
    """Test reconcile_vm_records service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.reconcile_networking_records")
    def test_delegates_to_reconcile_networking_records(self, mock_reconcile):
        """Should delegate to reconcile_networking_records."""
        vm_records = [{"vm_name": "vm1"}]
        reconcile_vm_records(vm_records)

        mock_reconcile.assert_called_once_with(
            vm_records, policy_only=False, allow_destructive=False, network_groups=None
        )

    @patch("homelab_vm_provisioner.service_mode.reconcile_networking_records")
    def test_passes_all_parameters(self, mock_reconcile):
        """Should pass all parameters to reconcile_networking_records."""
        vm_records = [{"vm_name": "vm1"}]
        network_groups = [{"id": "ng-1"}]
        reconcile_vm_records(
            vm_records, network_groups=network_groups, policy_only=True, allow_destructive=True
        )

        mock_reconcile.assert_called_once_with(
            vm_records, policy_only=True, allow_destructive=True, network_groups=network_groups
        )


class StartVmTest(unittest.TestCase):
    """Test start_vm service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.start_vm_internal")
    def test_delegates_to_internal_start_vm(self, mock_start):
        """Should delegate to internal start_vm function."""
        mock_start.return_value = True

        result = start_vm("test-vm")

        mock_start.assert_called_once_with("test-vm")
        self.assertTrue(result)


class StopVmTest(unittest.TestCase):
    """Test stop_vm service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.stop_vm_internal")
    def test_delegates_to_internal_stop_vm(self, mock_stop):
        """Should delegate to internal stop_vm function."""
        mock_stop.return_value = True

        result = stop_vm("test-vm")

        mock_stop.assert_called_once_with("test-vm")
        self.assertTrue(result)


class DestroyVmTest(unittest.TestCase):
    """Test destroy_vm service entrypoint."""

    @patch("homelab_vm_provisioner.service_mode.destroy_vm_internal")
    def test_delegates_to_internal_destroy_vm(self, mock_destroy):
        """Should delegate to internal destroy_vm function."""
        mock_destroy.return_value = None

        result = destroy_vm("test-vm")

        mock_destroy.assert_called_once_with("test-vm")
        self.assertIsNone(result)


class RefreshVmRuntimeStateTest(unittest.TestCase):
    """Test refresh_vm_runtime_state assembles runtime state."""

    @patch("homelab_vm_provisioner.service_mode.current_domain_state")
    @patch("homelab_vm_provisioner.service_mode.merged_vm_network")
    @patch("homelab_vm_provisioner.service_mode.load_vm_state")
    def test_assembles_runtime_state(self, mock_load_state, mock_merged_network, mock_domain_state):
        """Should assemble refreshed runtime state."""
        mock_load_state.return_value = {
            "vm_name": "test-vm",
            "ports": [{"host": 2222, "guest": 22}],
            "mac_address": "52:54:00:11:22:33",
            "ip_address": "10.0.0.10",
        }
        mock_merged_network.return_value = {
            "mode": "nat",
            "mac": "52:54:00:11:22:44",
            "vm_ip": "10.0.0.20",
        }
        mock_domain_state.return_value = "running"

        result = refresh_vm_runtime_state("test-vm")

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["network"]["mode"], "nat")
        self.assertEqual(result["ports"], [{"host": 2222, "guest": 22}])
        self.assertEqual(result["mac_address"], "52:54:00:11:22:44")
        self.assertEqual(result["ip_address"], "10.0.0.20")

    @patch("homelab_vm_provisioner.service_mode.current_domain_state")
    @patch("homelab_vm_provisioner.service_mode.merged_vm_network")
    @patch("homelab_vm_provisioner.service_mode.load_vm_state")
    def test_handles_unknown_domain_state(self, mock_load_state, mock_merged_network, mock_domain_state):
        """Should handle None domain state as unknown."""
        mock_load_state.return_value = {}
        mock_merged_network.return_value = {}
        mock_domain_state.return_value = None

        result = refresh_vm_runtime_state("test-vm")

        self.assertEqual(result["status"], "unknown")

    @patch("homelab_vm_provisioner.service_mode.current_domain_state")
    @patch("homelab_vm_provisioner.service_mode.merged_vm_network")
    @patch("homelab_vm_provisioner.service_mode.load_vm_state")
    def test_prefers_network_mac_over_state_mac(self, mock_load_state, mock_merged_network, mock_domain_state):
        """Should prefer merged network MAC over persisted state MAC."""
        mock_load_state.return_value = {"mac_address": "old-mac"}
        mock_merged_network.return_value = {"mac": "new-mac"}
        mock_domain_state.return_value = "running"

        result = refresh_vm_runtime_state("test-vm")

        self.assertEqual(result["mac_address"], "new-mac")

    @patch("homelab_vm_provisioner.service_mode.current_domain_state")
    @patch("homelab_vm_provisioner.service_mode.merged_vm_network")
    @patch("homelab_vm_provisioner.service_mode.load_vm_state")
    def test_prefers_network_ip_over_state_ip(self, mock_load_state, mock_merged_network, mock_domain_state):
        """Should prefer merged network IP over persisted state IP."""
        mock_load_state.return_value = {"ip_address": "10.0.0.1"}
        mock_merged_network.return_value = {"vm_ip": "10.0.0.2"}
        mock_domain_state.return_value = "running"

        result = refresh_vm_runtime_state("test-vm")

        self.assertEqual(result["ip_address"], "10.0.0.2")


if __name__ == "__main__":
    unittest.main()
