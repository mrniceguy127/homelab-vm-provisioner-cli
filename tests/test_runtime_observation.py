"""Tests for homelab_vm_provisioner.runtime_observation module."""

import unittest
from unittest.mock import patch

from homelab_vm_provisioner.runtime_observation import (
    current_domain_state,
    is_libvirt_nat_network,
    merged_vm_network,
    start_vm_domain,
    stop_vm_domain,
)


class IsLibvirtNatNetworkTest(unittest.TestCase):
    """Test is_libvirt_nat_network helper."""

    def test_nat_mode_returns_true(self):
        """Network with mode=nat should return True."""
        network = {"mode": "nat"}
        self.assertTrue(is_libvirt_nat_network(network))

    def test_nat_custom_mode_returns_true(self):
        """Network with mode=nat-custom should return True."""
        network = {"mode": "nat-custom"}
        self.assertTrue(is_libvirt_nat_network(network))

    def test_bridge_mode_returns_false(self):
        """Network with mode=bridge should return False."""
        network = {"mode": "bridge"}
        self.assertFalse(is_libvirt_nat_network(network))

    def test_no_mode_returns_false(self):
        """Network without mode key should return False."""
        network = {}
        self.assertFalse(is_libvirt_nat_network(network))

    def test_none_mode_returns_false(self):
        """Network with mode=None should return False."""
        network = {"mode": None}
        self.assertFalse(is_libvirt_nat_network(network))


class MergedVmNetworkTest(unittest.TestCase):
    """Test merged_vm_network combines persisted and discovered state."""

    @patch("homelab_vm_provisioner.runtime_observation.discover_vm_network")
    @patch("homelab_vm_provisioner.runtime_observation.default_nat_bridge_name")
    def test_merges_persisted_and_discovered(self, mock_bridge_name, mock_discover):
        """Should merge persisted state with discovered network info."""
        mock_discover.return_value = {"vm_ip": "192.168.1.10", "mac": "00:11:22:33:44:55"}
        mock_bridge_name.return_value = "virbr-test"
        
        state = {"network": {"mode": "nat", "name": "test-net"}}
        result = merged_vm_network("test-vm", state)
        
        self.assertEqual(result["mode"], "nat")
        self.assertEqual(result["name"], "test-net")
        self.assertEqual(result["vm_ip"], "192.168.1.10")
        self.assertEqual(result["mac"], "00:11:22:33:44:55")

    @patch("homelab_vm_provisioner.runtime_observation.discover_vm_network")
    @patch("homelab_vm_provisioner.runtime_observation.default_nat_bridge_name")
    def test_sets_defaults_for_nat_network(self, mock_bridge_name, mock_discover):
        """Should set default name and bridge for NAT networks."""
        mock_discover.return_value = {}
        mock_bridge_name.return_value = "virbr-demo"
        
        state = {"network": {"mode": "nat"}}
        result = merged_vm_network("demo", state)
        
        self.assertEqual(result["name"], "demo-net")
        self.assertEqual(result["libvirt_network_name"], "demo-net")
        self.assertEqual(result["bridge_name"], "virbr-demo")

    @patch("homelab_vm_provisioner.runtime_observation.discover_vm_network")
    def test_does_not_override_existing_name(self, mock_discover):
        """Should not override existing network name."""
        mock_discover.return_value = {}
        
        state = {"network": {"mode": "nat", "name": "custom-net"}}
        result = merged_vm_network("demo", state)
        
        self.assertEqual(result["name"], "custom-net")

    @patch("homelab_vm_provisioner.runtime_observation.discover_vm_network")
    def test_handles_no_network_in_state(self, mock_discover):
        """Should handle state with no network key."""
        mock_discover.return_value = {"vm_ip": "10.0.0.5"}
        
        state = {}
        result = merged_vm_network("test-vm", state)
        
        self.assertEqual(result["vm_ip"], "10.0.0.5")

    @patch("homelab_vm_provisioner.runtime_observation.discover_vm_network")
    def test_handles_none_network_in_state(self, mock_discover):
        """Should handle state with network=None."""
        mock_discover.return_value = {}
        
        state = {"network": None}
        result = merged_vm_network("test-vm", state)
        
        self.assertIsInstance(result, dict)


class CurrentDomainStateTest(unittest.TestCase):
    """Test current_domain_state queries libvirt."""

    @patch("homelab_vm_provisioner.runtime_observation.capture_or_none")
    def test_returns_domain_state(self, mock_capture):
        """Should capture virsh domstate output."""
        mock_capture.return_value = "running"
        
        result = current_domain_state("test-vm")
        
        self.assertEqual(result, "running")
        mock_capture.assert_called_once_with(["virsh", "domstate", "test-vm"], sudo=True)

    @patch("homelab_vm_provisioner.runtime_observation.capture_or_none")
    def test_returns_none_when_vm_not_found(self, mock_capture):
        """Should return None when VM doesn't exist."""
        mock_capture.return_value = None
        
        result = current_domain_state("nonexistent")
        
        self.assertIsNone(result)


class StopVmDomainTest(unittest.TestCase):
    """Test stop_vm_domain graceful and forceful shutdown."""

    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_raises_error_when_vm_not_found(self, mock_exists):
        """Should raise FileNotFoundError when VM doesn't exist."""
        mock_exists.return_value = False
        
        with self.assertRaises(FileNotFoundError) as ctx:
            stop_vm_domain("nonexistent")
        
        self.assertIn("VM not found", str(ctx.exception))

    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_returns_false_when_already_stopped(self, mock_exists, mock_state, mock_run):
        """Should return False when VM is already stopped."""
        mock_exists.return_value = True
        mock_state.return_value = "shut off"
        
        result = stop_vm_domain("test-vm")
        
        self.assertFalse(result)
        mock_run.assert_not_called()

    @patch("homelab_vm_provisioner.runtime_observation.time")
    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_graceful_shutdown_when_vm_stops_quickly(self, mock_exists, mock_state, mock_run, mock_time):
        """Should use graceful shutdown when VM stops within timeout."""
        mock_exists.return_value = True
        mock_state.side_effect = ["running", "shut off"]
        mock_time.monotonic.side_effect = [0, 1]  # First check, second check within timeout
        
        result = stop_vm_domain("test-vm", timeout_seconds=60)
        
        self.assertTrue(result)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0], ["virsh", "shutdown", "test-vm"])

    @patch("homelab_vm_provisioner.runtime_observation.time")
    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_forceful_destroy_after_timeout(self, mock_exists, mock_state, mock_run, mock_time):
        """Should forcefully destroy VM after timeout expires."""
        mock_exists.return_value = True
        mock_state.return_value = "running"  # Never stops
        mock_time.monotonic.side_effect = [0, 61]  # Timeout exceeded
        
        result = stop_vm_domain("test-vm", timeout_seconds=60)
        
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(mock_run.call_args_list[0][0][0], ["virsh", "shutdown", "test-vm"])
        self.assertEqual(mock_run.call_args_list[1][0][0], ["virsh", "destroy", "test-vm"])


class StartVmDomainTest(unittest.TestCase):
    """Test start_vm_domain starts stopped VMs."""

    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_raises_error_when_vm_not_found(self, mock_exists):
        """Should raise FileNotFoundError when VM doesn't exist."""
        mock_exists.return_value = False
        
        with self.assertRaises(FileNotFoundError) as ctx:
            start_vm_domain("nonexistent")
        
        self.assertIn("VM not found", str(ctx.exception))

    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_returns_false_when_already_running(self, mock_exists, mock_state, mock_run):
        """Should return False when VM is already running."""
        mock_exists.return_value = True
        mock_state.return_value = "running"
        
        result = start_vm_domain("test-vm")
        
        self.assertFalse(result)
        mock_run.assert_not_called()

    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_starts_stopped_vm(self, mock_exists, mock_state, mock_run):
        """Should start VM when it's stopped."""
        mock_exists.return_value = True
        mock_state.return_value = "shut off"
        
        result = start_vm_domain("test-vm")
        
        self.assertTrue(result)
        mock_run.assert_called_once_with(["virsh", "start", "test-vm"], sudo=True)

    @patch("homelab_vm_provisioner.runtime_observation.run")
    @patch("homelab_vm_provisioner.runtime_observation.current_domain_state")
    @patch("homelab_vm_provisioner.runtime_observation.vm_exists")
    def test_starts_paused_vm(self, mock_exists, mock_state, mock_run):
        """Should start VM when it's in paused state."""
        mock_exists.return_value = True
        mock_state.return_value = "paused"
        
        result = start_vm_domain("test-vm")
        
        self.assertTrue(result)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
