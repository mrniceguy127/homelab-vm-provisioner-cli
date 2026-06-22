"""Tests for homelab_vm_provisioner.constants module."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from homelab_vm_provisioner import constants


class ConstantsTest(unittest.TestCase):
    """Test constant definitions and computed paths."""

    def test_package_dir_is_absolute(self):
        """Package directory should be absolute path."""
        self.assertTrue(constants.PACKAGE_DIR.is_absolute())
        self.assertTrue(constants.PACKAGE_DIR.exists())

    def test_project_dir_is_parent_of_package(self):
        """Project directory should be parent of package directory."""
        self.assertEqual(constants.PROJECT_DIR, constants.PACKAGE_DIR.parent)

    def test_templates_dir_exists(self):
        """Templates directory should exist within package."""
        self.assertEqual(constants.TEMPLATES_DIR, constants.PACKAGE_DIR / "templates")
        self.assertTrue(constants.TEMPLATES_DIR.exists())

    def test_default_data_dir_name(self):
        """Default data directory name should be 'data'."""
        self.assertEqual(constants.DEFAULT_DATA_DIR_NAME, "data")

    def test_admin_user_constant(self):
        """Admin user should be vmadmin."""
        self.assertEqual(constants.ADMIN_USER, "vmadmin")

    def test_img_dir_path(self):
        """Image directory should be /var/lib/libvirt/images."""
        self.assertEqual(constants.IMG_DIR, Path("/var/lib/libvirt/images"))

    def test_base_image_name(self):
        """Base image name should be debian-12 qcow2."""
        self.assertIn("debian-12", constants.BASE_IMG_NAME)
        self.assertTrue(constants.BASE_IMG_NAME.endswith(".qcow2"))

    def test_base_image_url_is_debian(self):
        """Base image URL should point to Debian cloud images."""
        self.assertIn("debian", constants.BASE_IMG_URL.lower())
        self.assertTrue(constants.BASE_IMG_URL.startswith("https://"))

    def test_os_variant(self):
        """OS variant should be generic."""
        self.assertEqual(constants.OS_VARIANT, "generic")

    def test_default_required_tools(self):
        """Required tools tuple should contain essential commands."""
        self.assertIsInstance(constants.DEFAULT_REQUIRED_TOOLS, tuple)
        self.assertIn("virsh", constants.DEFAULT_REQUIRED_TOOLS)
        self.assertIn("virt-install", constants.DEFAULT_REQUIRED_TOOLS)
        self.assertIn("qemu-img", constants.DEFAULT_REQUIRED_TOOLS)
        self.assertIn("cloud-localds", constants.DEFAULT_REQUIRED_TOOLS)
        self.assertIn("nft", constants.DEFAULT_REQUIRED_TOOLS)
        self.assertIn("ssh-keygen", constants.DEFAULT_REQUIRED_TOOLS)

    def test_install_hint_contains_packages(self):
        """Install hint should mention key package names."""
        self.assertIn("libvirt", constants.INSTALL_HINT)
        self.assertIn("qemu", constants.INSTALL_HINT)
        self.assertIn("nftables", constants.INSTALL_HINT)

    def test_blocked_private_ranges(self):
        """Blocked private ranges should include RFC1918 and link-local."""
        self.assertIsInstance(constants.BLOCKED_PRIVATE_RANGES, list)
        self.assertIn("10.0.0.0/8", constants.BLOCKED_PRIVATE_RANGES)
        self.assertIn("172.16.0.0/12", constants.BLOCKED_PRIVATE_RANGES)
        self.assertIn("192.168.0.0/16", constants.BLOCKED_PRIVATE_RANGES)
        self.assertIn("169.254.0.0/16", constants.BLOCKED_PRIVATE_RANGES)

    def test_default_dns_resolvers(self):
        """Default DNS resolvers should be Cloudflare 1.1.1.1."""
        self.assertIsInstance(constants.DEFAULT_VM_DNS_RESOLVERS, tuple)
        self.assertIn("1.1.1.1", constants.DEFAULT_VM_DNS_RESOLVERS)
        self.assertIn("1.0.0.1", constants.DEFAULT_VM_DNS_RESOLVERS)

    def test_global_config_path_in_data_dir(self):
        """Global config path should be in data directory."""
        self.assertTrue(str(constants.GLOBAL_CONFIG_PATH).endswith("vmctl.yaml"))

    def test_legacy_vm_build_dir(self):
        """Legacy VM build directory should be .build in project root."""
        self.assertEqual(constants.LEGACY_VM_BUILD_DIR, constants.PROJECT_DIR / ".build")


class ResolveDefaultDataDirTest(unittest.TestCase):
    """Test _resolve_default_data_dir behavior with different env vars."""

    def test_no_env_var_uses_default(self):
        """When PROVISIONER_DATA_DIR is not set, use PROJECT_DIR/data."""
        with patch.dict(os.environ, {}, clear=False):
            if "PROVISIONER_DATA_DIR" in os.environ:
                del os.environ["PROVISIONER_DATA_DIR"]
            
            # Re-import to get fresh calculation
            import importlib
            importlib.reload(constants)
            
            # The actual value is computed at import time, so check the pattern
            self.assertTrue(str(constants.GLOBAL_CONFIG_PATH).endswith("data/vmctl.yaml"))

    def test_env_var_with_absolute_path(self):
        """When PROVISIONER_DATA_DIR is absolute, use it directly."""
        test_path = "/tmp/test-data-dir"
        with patch.dict(os.environ, {"PROVISIONER_DATA_DIR": test_path}, clear=False):
            result = constants._resolve_default_data_dir()
            self.assertEqual(result, Path(test_path))

    def test_env_var_with_relative_path(self):
        """When PROVISIONER_DATA_DIR is relative, resolve from PROJECT_DIR."""
        test_path = "custom-data"
        with patch.dict(os.environ, {"PROVISIONER_DATA_DIR": test_path}, clear=False):
            result = constants._resolve_default_data_dir()
            self.assertEqual(result, constants.PROJECT_DIR / test_path)

    def test_env_var_with_tilde_expansion(self):
        """When PROVISIONER_DATA_DIR contains ~, expand it."""
        test_path = "~/my-data"
        with patch.dict(os.environ, {"PROVISIONER_DATA_DIR": test_path}, clear=False):
            result = constants._resolve_default_data_dir()
            self.assertFalse(str(result).startswith("~"))
            self.assertTrue(result.is_absolute())


if __name__ == "__main__":
    unittest.main()
