"""Tests for homelab_vm_provisioner.reconciler helper functions."""

import unittest
from unittest.mock import patch

from homelab_vm_provisioner.reconciler import (
    blocked_private_lan_targets,
    configured_private_lan_cidrs,
    grouped_network_records,
    normalize_network_profile,
)


class ConfiguredPrivateLanCidrsTest(unittest.TestCase):
    """Test configured_private_lan_cidrs extracts CIDRs."""

    @patch("homelab_vm_provisioner.reconciler.load_global_config")
    def test_returns_empty_when_no_config(self, mock_load):
        """Should return empty list when no private_lan_cidrs configured."""
        mock_load.return_value = {}

        result = configured_private_lan_cidrs()

        self.assertEqual(result, [])

    @patch("homelab_vm_provisioner.reconciler.load_global_config")
    def test_returns_configured_cidrs(self, mock_load):
        """Should return configured private LAN CIDRs."""
        mock_load.return_value = {
            "networking": {"private_lan_cidrs": ["192.168.1.0/24", "10.0.0.0/8"]}
        }

        result = configured_private_lan_cidrs()

        self.assertEqual(result, ["192.168.1.0/24", "10.0.0.0/8"])

    @patch("homelab_vm_provisioner.reconciler.load_global_config")
    def test_strips_whitespace(self, mock_load):
        """Should strip whitespace from CIDR values."""
        mock_load.return_value = {"networking": {"private_lan_cidrs": ["  192.168.1.0/24  ", "10.0.0.0/8  "]}}

        result = configured_private_lan_cidrs()

        self.assertEqual(result, ["192.168.1.0/24", "10.0.0.0/8"])

    @patch("homelab_vm_provisioner.reconciler.load_global_config")
    def test_filters_empty_values(self, mock_load):
        """Should filter out empty strings."""
        mock_load.return_value = {"networking": {"private_lan_cidrs": ["192.168.1.0/24", "", "  ", "10.0.0.0/8"]}}

        result = configured_private_lan_cidrs()

        self.assertEqual(result, ["192.168.1.0/24", "10.0.0.0/8"])

    @patch("homelab_vm_provisioner.reconciler.load_global_config")
    def test_uses_provided_global_config(self, mock_load):
        """Should use provided global_config instead of loading."""
        global_config = {"networking": {"private_lan_cidrs": ["172.16.0.0/12"]}}

        result = configured_private_lan_cidrs(global_config=global_config)

        self.assertEqual(result, ["172.16.0.0/12"])
        mock_load.assert_not_called()


class BlockedPrivateLanTargetsTest(unittest.TestCase):
    """Test blocked_private_lan_targets returns blocked ranges."""

    def test_returns_blocked_ranges(self):
        """Should return default blocked private ranges."""
        result = blocked_private_lan_targets([])

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_returns_consistent_list(self):
        """Should return same blocked ranges regardless of network_groups."""
        result1 = blocked_private_lan_targets([])
        result2 = blocked_private_lan_targets([{"id": "ng-1"}])

        self.assertEqual(result1, result2)


class NormalizeNetworkProfileTest(unittest.TestCase):
    """Test normalize_network_profile maps network identifiers."""

    def test_nat_mode_returns_nat(self):
        """Network with mode=nat normalizes to 'isolated_nat'."""
        result = normalize_network_profile({"mode": "nat"})
        self.assertEqual(result, "isolated_nat")

    def test_nat_custom_mode_returns_nat_custom(self):
        """Network with mode=nat-custom normalizes to 'isolated_nat'."""
        result = normalize_network_profile({"mode": "nat-custom"})
        self.assertEqual(result, "isolated_nat")

    def test_bridge_mode_returns_bridged(self):
        """Network with mode=bridge normalizes to 'bridged'."""
        result = normalize_network_profile({"mode": "bridge"})
        self.assertEqual(result, "bridged")

    def test_empty_network_returns_none(self):
        """Empty network config defaults to 'isolated_nat'."""
        result = normalize_network_profile({})
        self.assertEqual(result, "isolated_nat")

    def test_none_mode_returns_none(self):
        """Network with mode=None defaults to 'isolated_nat'."""
        result = normalize_network_profile({"mode": None})
        self.assertEqual(result, "isolated_nat")


class GroupedNetworkRecordsTest(unittest.TestCase):
    """Test grouped_network_records groups VMs by network group."""

    def test_groups_vms_by_network_group_id(self):
        """Should group VM records by network_group_id."""
        vm_records = [
            {
                "vm_name": "vm1",
                "network_group_id": "ng-1",
                "owner_user_id": "user1",
                "network_group_name": "group-1",
                "profile": "nat",
                "libvirt_network_name": "net-1",
                "bridge_name": "br-1",
                "subnet_cidr": "10.0.0.0/24",
                "gateway_ip": "10.0.0.1",
                "dhcp_start": "10.0.0.10",
                "dhcp_end": "10.0.0.100",
            },
            {
                "vm_name": "vm2",
                "network_group_id": "ng-1",
                "owner_user_id": "user1",
                "network_group_name": "group-1",
                "profile": "nat",
                "libvirt_network_name": "net-1",
                "bridge_name": "br-1",
                "subnet_cidr": "10.0.0.0/24",
                "gateway_ip": "10.0.0.1",
                "dhcp_start": "10.0.0.10",
                "dhcp_end": "10.0.0.100",
            },
        ]

        result = grouped_network_records(vm_records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "ng-1")
        self.assertEqual(len(result[0]["vms"]), 2)

    def test_creates_separate_groups(self):
        """Should create separate groups for different network_group_ids."""
        vm_records = [
            {
                "vm_name": "vm1",
                "network_group_id": "ng-1",
                "owner_user_id": "user1",
                "network_group_name": "group-1",
                "profile": "nat",
                "libvirt_network_name": "net-1",
                "bridge_name": "br-1",
                "subnet_cidr": "10.0.0.0/24",
                "gateway_ip": "10.0.0.1",
                "dhcp_start": "10.0.0.10",
                "dhcp_end": "10.0.0.100",
            },
            {
                "vm_name": "vm2",
                "network_group_id": "ng-2",
                "owner_user_id": "user2",
                "network_group_name": "group-2",
                "profile": "bridged",
                "libvirt_network_name": "net-2",
                "bridge_name": "br-2",
                "subnet_cidr": "10.0.1.0/24",
                "gateway_ip": "10.0.1.1",
                "dhcp_start": "10.0.1.10",
                "dhcp_end": "10.0.1.100",
            },
        ]

        result = grouped_network_records(vm_records)

        self.assertEqual(len(result), 2)
        group_ids = {g["id"] for g in result}
        self.assertEqual(group_ids, {"ng-1", "ng-2"})
        # Check each group has 1 VM
        for group in result:
            self.assertEqual(len(group["vms"]), 1)

    def test_preserves_group_metadata(self):
        """Should preserve network group metadata."""
        vm_records = [
            {
                "vm_name": "vm1",
                "network_group_id": "ng-test",
                "owner_user_id": "test-user",
                "network_group_name": "test-group",
                "profile": "nat",
                "libvirt_network_name": "test-net",
                "bridge_name": "br-test",
                "subnet_cidr": "192.168.1.0/24",
                "gateway_ip": "192.168.1.1",
                "dhcp_start": "192.168.1.10",
                "dhcp_end": "192.168.1.100",
            }
        ]

        result = grouped_network_records(vm_records)

        group = result[0]
        self.assertEqual(group["id"], "ng-test")
        self.assertEqual(group["owner_user_id"], "test-user")
        self.assertEqual(group["name"], "test-group")
        self.assertEqual(group["profile"], "nat")
        self.assertEqual(group["bridge_name"], "br-test")
        self.assertEqual(group["subnet_cidr"], "192.168.1.0/24")

    def test_handles_empty_records(self):
        """Should handle empty VM records list."""
        result = grouped_network_records([])

        self.assertEqual(result, [])


class BuildLibvirtNetworkXmlTest(unittest.TestCase):
    """Test build_libvirt_network_xml generates correct XML."""

    def test_returns_none_for_bridged_profile(self):
        """Should return None for bridged networks."""
        from homelab_vm_provisioner.reconciler import build_libvirt_network_xml

        network_group = {"profile": "bridged"}
        result = build_libvirt_network_xml(network_group, [])

        self.assertIsNone(result)

    def test_generates_nat_network_xml(self):
        """Should generate XML for NAT network."""
        from homelab_vm_provisioner.reconciler import build_libvirt_network_xml

        network_group = {
            "profile": "nat",
            "libvirt_network_name": "test-net",
            "bridge_name": "br-test",
            "subnet_cidr": "10.0.0.0/24",
            "gateway_ip": "10.0.0.1",
            "dhcp_start": "10.0.0.10",
            "dhcp_end": "10.0.0.100",
        }
        vm_records = [
            {
                "vm_name": "vm1",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.0.0.10",
            }
        ]

        result = build_libvirt_network_xml(network_group, vm_records)

        self.assertIn("<network>", result)
        self.assertIn("<name>test-net</name>", result)
        self.assertIn("<forward mode='nat'/>", result)
        self.assertIn("bridge name='br-test'", result)
        self.assertIn("address='10.0.0.1'", result)
        self.assertIn("start='10.0.0.10'", result)
        self.assertIn("end='10.0.0.100'", result)
        self.assertIn("host mac='52:54:00:11:22:33' name='vm1' ip='10.0.0.10'", result)

    def test_generates_isolated_nat_network_xml(self):
        """Should generate XML for isolated NAT network."""
        from homelab_vm_provisioner.reconciler import build_libvirt_network_xml

        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "isolated-net",
            "bridge_name": "br-isolated",
            "subnet_cidr": "192.168.1.0/24",
            "gateway_ip": "192.168.1.1",
            "dhcp_start": "192.168.1.10",
            "dhcp_end": "192.168.1.254",
        }

        result = build_libvirt_network_xml(network_group, [])

        self.assertIn("<network>", result)
        self.assertIn("<name>isolated-net</name>", result)
        # isolated_nat should still have forward mode
        self.assertIn("<forward mode='nat'/>", result)

    def test_filters_vms_without_mac_or_ip(self):
        """Should filter out VMs without MAC or IP address."""
        from homelab_vm_provisioner.reconciler import build_libvirt_network_xml

        network_group = {
            "profile": "nat",
            "libvirt_network_name": "test-net",
            "bridge_name": "br-test",
            "subnet_cidr": "10.0.0.0/24",
            "gateway_ip": "10.0.0.1",
            "dhcp_start": "10.0.0.10",
            "dhcp_end": "10.0.0.100",
        }
        vm_records = [
            {"vm_name": "vm1", "mac_address": "52:54:00:11:22:33", "ip_address": "10.0.0.10"},
            {"vm_name": "vm2", "mac_address": None, "ip_address": "10.0.0.11"},  # Missing MAC
            {"vm_name": "vm3", "mac_address": "52:54:00:11:22:44", "ip_address": None},  # Missing IP
            {"vm_name": "vm4"},  # Missing both
        ]

        result = build_libvirt_network_xml(network_group, vm_records)

        # Only vm1 should appear
        self.assertIn("host mac='52:54:00:11:22:33' name='vm1' ip='10.0.0.10'", result)
        self.assertNotIn("vm2", result)
        self.assertNotIn("vm3", result)
        self.assertNotIn("vm4", result)


class SortedEnabledPortsTest(unittest.TestCase):
    """Test _sorted_enabled_ports filters and sorts ports."""

    def test_filters_disabled_ports(self):
        """Should filter out ports with enabled=False."""
        from homelab_vm_provisioner.reconciler import _sorted_enabled_ports

        ports = [
            {"host": 8080, "guest": 80, "enabled": True},
            {"host": 8443, "guest": 443, "enabled": False},
            {"host": 2222, "guest": 22},
        ]

        result = _sorted_enabled_ports(ports)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["host"], 2222)
        self.assertEqual(result[1]["host"], 8080)

    def test_normalizes_port_fields(self):
        """Should normalize external_port/internal_port to host/guest."""
        from homelab_vm_provisioner.reconciler import _sorted_enabled_ports

        ports = [
            {"external_port": 8080, "internal_port": 80, "protocol": "tcp"},
            {"host": 2222, "guest": 22, "proto": "tcp"},
        ]

        result = _sorted_enabled_ports(ports)

        self.assertEqual(result[0]["host"], 2222)
        self.assertEqual(result[0]["guest"], 22)
        self.assertEqual(result[1]["host"], 8080)
        self.assertEqual(result[1]["guest"], 80)

    def test_sorts_by_protocol_host_guest(self):
        """Should sort ports by protocol, then host, then guest."""
        from homelab_vm_provisioner.reconciler import _sorted_enabled_ports

        ports = [
            {"host": 8080, "guest": 80, "proto": "tcp"},
            {"host": 5353, "guest": 53, "proto": "udp"},
            {"host": 2222, "guest": 22, "proto": "tcp"},
        ]

        result = _sorted_enabled_ports(ports)

        self.assertEqual(result[0]["proto"], "tcp")
        self.assertEqual(result[0]["host"], 2222)
        self.assertEqual(result[1]["proto"], "tcp")
        self.assertEqual(result[1]["host"], 8080)
        self.assertEqual(result[2]["proto"], "udp")

    def test_defaults_to_tcp_protocol(self):
        """Should default to tcp protocol when not specified."""
        from homelab_vm_provisioner.reconciler import _sorted_enabled_ports

        ports = [{"host": 8080, "guest": 80}]

        result = _sorted_enabled_ports(ports)

        self.assertEqual(result[0]["proto"], "tcp")


class NftIdentifierTest(unittest.TestCase):
    """Test _nft_identifier converts labels to valid nftables identifiers."""

    def test_normalizes_alphanumeric(self):
        """Should keep alphanumeric characters."""
        from homelab_vm_provisioner.reconciler import _nft_identifier

        result = _nft_identifier("test123")
        self.assertEqual(result, "test123")

    def test_replaces_special_characters(self):
        """Should replace special characters with underscores."""
        from homelab_vm_provisioner.reconciler import _nft_identifier

        result = _nft_identifier("test-vm.local")
        self.assertEqual(result, "test_vm_local")

    def test_strips_underscores(self):
        """Should strip leading/trailing underscores."""
        from homelab_vm_provisioner.reconciler import _nft_identifier

        result = _nft_identifier("--test--")
        self.assertEqual(result, "test")

    def test_prepends_s_when_starts_with_digit(self):
        """Should prepend 's_' when identifier starts with digit."""
        from homelab_vm_provisioner.reconciler import _nft_identifier

        result = _nft_identifier("123test")
        self.assertEqual(result, "s_123test")

    def test_defaults_to_set_when_empty(self):
        """Should default to 'set' when result is empty."""
        from homelab_vm_provisioner.reconciler import _nft_identifier

        result = _nft_identifier("---")
        self.assertEqual(result, "set")


class SortedIpv4AddressesTest(unittest.TestCase):
    """Test _sorted_ipv4_addresses sorts and deduplicates IPs."""

    def test_sorts_ip_addresses(self):
        """Should sort IP addresses numerically."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_addresses

        values = ["192.168.1.10", "10.0.0.1", "172.16.0.5"]

        result = _sorted_ipv4_addresses(values)

        self.assertEqual(result, ["10.0.0.1", "172.16.0.5", "192.168.1.10"])

    def test_removes_duplicates(self):
        """Should remove duplicate IP addresses."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_addresses

        values = ["10.0.0.1", "10.0.0.2", "10.0.0.1"]

        result = _sorted_ipv4_addresses(values)

        self.assertEqual(result, ["10.0.0.1", "10.0.0.2"])

    def test_strips_whitespace(self):
        """Should strip whitespace from IP addresses."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_addresses

        values = ["  10.0.0.1  ", "10.0.0.2"]

        result = _sorted_ipv4_addresses(values)

        self.assertEqual(result, ["10.0.0.1", "10.0.0.2"])

    def test_filters_empty_values(self):
        """Should filter out empty strings."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_addresses

        values = ["10.0.0.1", "", "  ", "10.0.0.2"]

        result = _sorted_ipv4_addresses(values)

        self.assertEqual(result, ["10.0.0.1", "10.0.0.2"])


class SortedIpv4NetworksTest(unittest.TestCase):
    """Test _sorted_ipv4_networks sorts and deduplicates networks."""

    def test_sorts_networks(self):
        """Should sort network CIDRs."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_networks

        values = ["192.168.1.0/24", "10.0.0.0/8", "172.16.0.0/16"]

        result = _sorted_ipv4_networks(values)

        self.assertEqual(result, ["10.0.0.0/8", "172.16.0.0/16", "192.168.1.0/24"])

    def test_removes_duplicate_networks(self):
        """Should remove duplicate networks."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_networks

        values = ["10.0.0.0/24", "10.0.0.0/24", "192.168.1.0/24"]

        result = _sorted_ipv4_networks(values)

        self.assertEqual(len(result), 2)

    def test_normalizes_networks(self):
        """Should normalize networks with strict=False."""
        from homelab_vm_provisioner.reconciler import _sorted_ipv4_networks

        values = ["10.0.0.5/24"]  # Not network address

        result = _sorted_ipv4_networks(values)

        self.assertEqual(result, ["10.0.0.0/24"])


class NftStringTest(unittest.TestCase):
    """Test _nft_string wraps values for nftables."""

    def test_wraps_string_in_quotes(self):
        """Should wrap string value in JSON quotes."""
        from homelab_vm_provisioner.reconciler import _nft_string

        result = _nft_string("test-comment")
        self.assertEqual(result, '"test-comment"')

    def test_escapes_special_characters(self):
        """Should escape special characters in string."""
        from homelab_vm_provisioner.reconciler import _nft_string

        result = _nft_string('test "value"')
        self.assertIn('\\"', result)


class NftRuleTest(unittest.TestCase):
    """Test _nft_rule builds nftables rule strings."""

    def test_builds_rule_without_comment(self):
        """Should build rule string without comment."""
        from homelab_vm_provisioner.reconciler import _nft_rule

        parts = ["add", "rule", "inet", "filter", "input", "accept"]

        result = _nft_rule(parts)

        self.assertEqual(result, "add rule inet filter input accept")

    def test_builds_rule_with_comment(self):
        """Should build rule string with comment."""
        from homelab_vm_provisioner.reconciler import _nft_rule

        parts = ["add", "rule", "inet", "filter", "input", "accept"]

        result = _nft_rule(parts, comment="Allow traffic")

        self.assertIn("add rule inet filter input accept", result)
        self.assertIn("comment", result)
        self.assertIn("Allow traffic", result)

    def test_filters_none_values(self):
        """Should filter out None values from parts."""
        from homelab_vm_provisioner.reconciler import _nft_rule

        parts = ["add", "rule", None, "filter", "input", None, "accept"]

        result = _nft_rule(parts)

        self.assertEqual(result, "add rule filter input accept")


class ForwardRuleTest(unittest.TestCase):
    """Test _forward_rule builds forward rules."""

    def test_builds_forward_rule(self):
        """Should build FORWARD chain rule."""
        from homelab_vm_provisioner.reconciler import _forward_rule

        result = _forward_rule(100, "10.0.0.0/24", "192.168.1.0/24", "accept")

        expected_parts = ["ipv4", "filter", "FORWARD", "100", "-s", "10.0.0.0/24", "-d", "192.168.1.0/24", "-j", "accept"]
        for part in expected_parts:
            self.assertIn(str(part), str(result))

    def test_includes_in_interface_when_provided(self):
        """Should include in-interface when provided."""
        from homelab_vm_provisioner.reconciler import _forward_rule

        result = _forward_rule(100, "10.0.0.0/24", "192.168.1.0/24", "accept", in_interface="br0")

        self.assertIn("-i", result)
        self.assertIn("br0", result)


if __name__ == "__main__":
    unittest.main()
