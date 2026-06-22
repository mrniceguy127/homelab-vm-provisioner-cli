"""Additional tests for homelab_vm_provisioner.core module."""

import unittest

from homelab_vm_provisioner.core import (
    find_free_subnet,
    normalize_network_profile,
    validate_ipv4_network,
)


class ValidateIpv4NetworkTest(unittest.TestCase):
    """Test validate_ipv4_network validates IPv4 networks."""

    def test_rejects_ipv6_network(self):
        """Should raise ValueError for IPv6 networks."""
        with self.assertRaises(ValueError) as ctx:
            validate_ipv4_network("2001:db8::/32")
        self.assertIn("Must be an IPv4 network", str(ctx.exception))


class FindFreeSubnetTest(unittest.TestCase):
    """Test find_free_subnet error handling."""

    def test_raises_when_all_subnets_taken(self):
        """Should raise RuntimeError when no free subnets available."""
        # Create existing routes and networks that cover all 192.168.X.0/24 subnets
        routes = "\n".join(f"192.168.{i}." for i in range(100, 251))
        networks = ""

        with self.assertRaises(RuntimeError) as ctx:
            find_free_subnet(routes, networks)

        self.assertIn("Could not find free", str(ctx.exception))


class NormalizeNetworkProfileTest(unittest.TestCase):
    """Test normalize_network_profile handles various profile names."""

    def test_normalizes_bridge_to_bridged(self):
        """Should normalize 'bridge' to 'bridged'."""
        result = normalize_network_profile({"profile": "bridge"})
        self.assertEqual(result, "bridged")

    def test_normalizes_bridged_to_bridged(self):
        """Should keep 'bridged' as 'bridged'."""
        result = normalize_network_profile({"profile": "bridged"})
        self.assertEqual(result, "bridged")

    def test_normalizes_private_to_private(self):
        """Should keep 'private' as 'private'."""
        result = normalize_network_profile({"profile": "private"})
        self.assertEqual(result, "private")

    def test_normalizes_nat_auto_to_isolated_nat(self):
        """Should normalize 'nat-auto' to 'isolated_nat'."""
        result = normalize_network_profile({"mode": "nat-auto"})
        self.assertEqual(result, "isolated_nat")

    def test_normalizes_nat_custom_to_isolated_nat(self):
        """Should normalize 'nat-custom' to 'isolated_nat'."""
        result = normalize_network_profile({"mode": "nat-custom"})
        self.assertEqual(result, "isolated_nat")

    def test_normalizes_nat_to_isolated_nat(self):
        """Should normalize 'nat' to 'isolated_nat'."""
        result = normalize_network_profile({"mode": "nat"})
        self.assertEqual(result, "isolated_nat")

    def test_defaults_to_isolated_nat(self):
        """Should default to 'isolated_nat' when profile not recognized."""
        result = normalize_network_profile({"mode": "unknown"})
        self.assertEqual(result, "isolated_nat")

    def test_defaults_to_isolated_nat_when_none(self):
        """Should default to 'isolated_nat' when config is None."""
        result = normalize_network_profile(None)
        self.assertEqual(result, "isolated_nat")

    def test_defaults_to_isolated_nat_when_empty(self):
        """Should default to 'isolated_nat' when config is empty."""
        result = normalize_network_profile({})
        self.assertEqual(result, "isolated_nat")


if __name__ == "__main__":
    unittest.main()
