import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from homelab_vm_provisioner import config


class ResolveConfigPathTests(unittest.TestCase):
    def test_accepts_existing_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "demo.yaml"
            config_path.write_text("vm: {}\n", encoding="utf-8")

            self.assertEqual(config.resolve_config_path(str(config_path)), config_path)

    def test_expands_config_shorthand_to_configs_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            tmpdir_path = Path(tmpdir)
            configs_dir = tmpdir_path / "configs"
            configs_dir.mkdir()
            config_path = configs_dir / "grant-minecraft.yaml"
            config_path.write_text("vm: {}\n", encoding="utf-8")

            try:
                os.chdir(tmpdir_path)
                resolved = config.resolve_config_path("config/grant-minecraft")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(resolved, Path("configs/grant-minecraft.yaml"))

    def test_raises_for_missing_config(self):
        with self.assertRaisesRegex(FileNotFoundError, "Missing config file"):
            config.resolve_config_path("config/does-not-exist")

    def test_expands_config_shorthand_with_explicit_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "configs" / "demo.yaml"
            config_path.parent.mkdir()
            config_path.write_text("vm: {}\n", encoding="utf-8")

            try:
                os.chdir(tmpdir_path)
                resolved = config.resolve_config_path("config/demo.yaml")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(resolved, Path("configs/demo.yaml"))


class GlobalConfigTests(unittest.TestCase):
    def test_load_global_config_returns_empty_dict_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(config, "GLOBAL_CONFIG_PATH", Path(tmpdir) / "vmctl.yaml"):
                self.assertEqual(config.load_global_config(), {})

    def test_load_global_config_reads_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            global_config_path = Path(tmpdir) / "vmctl.yaml"
            global_config_path.write_text(
                "paths:\n  vm_data_dir: custom/data\n  user_key_dir: custom/keys/users\n",
                encoding="utf-8",
            )

            with patch.object(config, "GLOBAL_CONFIG_PATH", global_config_path):
                loaded = config.load_global_config()

        self.assertEqual(
            loaded,
            {
                "paths": {
                    "vm_data_dir": "custom/data",
                    "user_key_dir": "custom/keys/users",
                }
            },
        )

    def test_load_global_config_rejects_non_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            global_config_path = Path(tmpdir) / "vmctl.yaml"
            global_config_path.write_text("- not-a-mapping\n", encoding="utf-8")

            with patch.object(config, "GLOBAL_CONFIG_PATH", global_config_path):
                with self.assertRaisesRegex(ValueError, "Global config must be a mapping"):
                    config.load_global_config()


class ImageSettingsTests(unittest.TestCase):
    def test_image_name_from_url_uses_url_filename(self):
        self.assertEqual(
            config.image_name_from_url("https://example.invalid/images/ubuntu-24.04.img"),
            "ubuntu-24.04.img",
        )

    def test_image_name_from_url_rejects_missing_filename(self):
        with self.assertRaisesRegex(ValueError, "Could not derive image name"):
            config.image_name_from_url("https://example.invalid/")

    def test_image_settings_default_to_builtin_values(self):
        self.assertEqual(
            config.image_settings_for_config({}, global_config={}),
            {
                "name": config.BASE_IMG_NAME,
                "url": config.BASE_IMG_URL,
                "os_variant": config.OS_VARIANT,
            },
        )

    def test_global_image_override_can_derive_name_from_url(self):
        self.assertEqual(
            config.image_settings_for_config(
                {},
                global_config={
                    "image": {
                        "url": "https://example.invalid/images/ubuntu-24.04.img",
                        "os_variant": "ubuntu24.04",
                    }
                },
            ),
            {
                "name": "ubuntu-24.04.img",
                "url": "https://example.invalid/images/ubuntu-24.04.img",
                "os_variant": "ubuntu24.04",
            },
        )

    def test_vm_image_override_beats_global_image_settings(self):
        self.assertEqual(
            config.image_settings_for_config(
                {
                    "image": {
                        "url": "https://example.invalid/images/fedora-40.qcow2",
                        "os_variant": "fedora40",
                    }
                },
                global_config={
                    "image": {
                        "name": "ubuntu-base.img",
                        "url": "https://example.invalid/images/ubuntu-base.img",
                        "os_variant": "ubuntu24.04",
                    }
                },
            ),
            {
                "name": "fedora-40.qcow2",
                "url": "https://example.invalid/images/fedora-40.qcow2",
                "os_variant": "fedora40",
            },
        )

    def test_image_settings_load_global_config_when_not_provided(self):
        with patch.object(
            config,
            "load_global_config",
            return_value={"image": {"url": "https://example.invalid/images/ubuntu-24.04.img"}},
        ) as load_global_config_mock:
            image_settings = config.image_settings_for_config({})

        load_global_config_mock.assert_called_once_with()
        self.assertEqual(image_settings["name"], "ubuntu-24.04.img")


class DnsSettingsTests(unittest.TestCase):
    def test_dns_settings_default_to_cloudflare_resolvers(self):
        self.assertEqual(
            config.dns_settings_for_config({}, global_config={}),
            {"resolvers": ("1.1.1.1", "1.0.0.1")},
        )

    def test_global_dns_override_is_applied(self):
        self.assertEqual(
            config.dns_settings_for_config(
                {},
                global_config={"dns": {"resolvers": ["9.9.9.9", "149.112.112.112"]}},
            ),
            {"resolvers": ("9.9.9.9", "149.112.112.112")},
        )

    def test_vm_dns_override_beats_global_dns_settings(self):
        self.assertEqual(
            config.dns_settings_for_config(
                {"dns": {"resolvers": ["8.8.8.8", "8.8.4.4"]}},
                global_config={"dns": {"resolvers": ["9.9.9.9"]}},
            ),
            {"resolvers": ("8.8.8.8", "8.8.4.4")},
        )

    def test_dns_settings_load_global_config_when_not_provided(self):
        with patch.object(
            config,
            "load_global_config",
            return_value={"dns": {"resolvers": ["8.8.8.8"]}},
        ) as load_global_config_mock:
            dns_settings = config.dns_settings_for_config({})

        load_global_config_mock.assert_called_once_with()
        self.assertEqual(dns_settings, {"resolvers": ("8.8.8.8",)})

    def test_dns_settings_reject_non_list_values(self):
        with self.assertRaisesRegex(ValueError, "dns.resolvers must be a list"):
            config.dns_settings_for_config({"dns": {"resolvers": "1.1.1.1"}}, global_config={})

    def test_dns_settings_reject_empty_lists(self):
        with self.assertRaisesRegex(ValueError, "dns.resolvers must contain at least one"):
            config.dns_settings_for_config({"dns": {"resolvers": []}}, global_config={})

    def test_dns_settings_reject_invalid_ip_addresses(self):
        with self.assertRaisesRegex(ValueError, "dns.resolvers contains an invalid IP address"):
            config.dns_settings_for_config(
                {"dns": {"resolvers": ["1.1.1.1", "bad-ip"]}},
                global_config={},
            )


class DefaultPathTests(unittest.TestCase):
    def test_defaults_use_vm_directory_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                self.assertEqual(config.default_vm_data_root({}), repo_root / "data" / "vm" / "data")
                self.assertEqual(config.default_vm_state_root({}), repo_root / "data" / "vm" / "state")
                self.assertEqual(
                    config.default_user_key_dir({}),
                    repo_root / "data" / "vm" / "keys" / "users",
                )
                self.assertEqual(
                    config.default_admin_key_dir({}),
                    repo_root / "data" / "vm" / "keys" / "admin",
                )
                self.assertEqual(
                    config.default_vm_data_dir("demo", {}),
                    repo_root / "data" / "vm" / "data" / "demo",
                )

    def test_global_config_overrides_default_roots(self):
        global_config = {
            "paths": {
                "vm_data_dir": "custom/vm-data",
                "vm_state_dir": "custom/state",
                "user_key_dir": "custom/user-keys",
                "admin_key_dir": "custom/admin-keys",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                self.assertEqual(
                    config.default_vm_data_root(global_config),
                    repo_root / "data" / "custom" / "vm-data",
                )
                self.assertEqual(
                    config.default_vm_state_root(global_config),
                    repo_root / "data" / "custom" / "state",
                )
                self.assertEqual(
                    config.default_user_key_dir(global_config),
                    repo_root / "data" / "custom" / "user-keys",
                )
                self.assertEqual(
                    config.default_admin_key_dir(global_config),
                    repo_root / "data" / "custom" / "admin-keys",
                )

    def test_legacy_provider_key_dir_alias_maps_to_admin_key_dir(self):
        global_config = {"paths": {"provider_key_dir": "legacy/provider-keys"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                self.assertEqual(
                    config.default_admin_key_dir(global_config),
                    repo_root / "data" / "legacy" / "provider-keys",
                )

    def test_vm_data_dir_can_be_configured_per_vm_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                self.assertEqual(
                    config.vm_data_dir_for_config(
                        "demo",
                        {"paths": {"vm_data_dir": "vm/artifacts/demo"}},
                        global_config={},
                    ),
                    repo_root / "data" / "vm" / "artifacts" / "demo",
                )

    def test_resolve_user_key_path_uses_configured_user_key_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            user_key_dir = repo_root / "data" / "vm" / "keys" / "users"
            user_key_dir.mkdir(parents=True)
            tenant_key = user_key_dir / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            with patch.object(config, "PROJECT_DIR", repo_root):
                resolved = config.resolve_user_key_path("tenant.pub", global_config={})

        self.assertEqual(resolved, tenant_key)

    def test_resolve_user_key_path_prefers_existing_project_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            project_key = repo_root / "keys" / "tenant.pub"
            project_key.parent.mkdir(parents=True)
            project_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            with patch.object(config, "PROJECT_DIR", repo_root):
                resolved = config.resolve_user_key_path("keys/tenant.pub", global_config={})

        self.assertEqual(resolved, repo_root / "data" / "keys" / "tenant.pub")

    def test_resolve_user_key_path_returns_default_user_key_dir_for_missing_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                resolved = config.resolve_user_key_path("tenant.pub", global_config={})

        self.assertEqual(resolved, repo_root / "data" / "vm" / "keys" / "users" / "tenant.pub")

    def test_resolve_user_key_path_handles_user_key_dir_equal_to_relative_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            tmpdir_path = Path(tmpdir)
            relative_key = tmpdir_path / "tenant.pub"
            relative_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            try:
                os.chdir(tmpdir_path)
                with patch.object(config, "default_user_key_dir", return_value=Path(".")):
                    resolved = config.resolve_user_key_path("tenant.pub", global_config={})
            finally:
                os.chdir(original_cwd)

        self.assertEqual(resolved, Path("tenant.pub"))

    def test_resolve_user_key_path_keeps_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            absolute_key = Path(tmpdir) / "keys" / "tenant.pub"

            self.assertEqual(
                config.resolve_user_key_path(str(absolute_key), global_config={}),
                absolute_key,
            )

    def test_resolve_user_key_path_returns_project_relative_fallback_for_nested_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                resolved = config.resolve_user_key_path("keys/team/tenant.pub", global_config={})

        self.assertEqual(resolved, repo_root / "data" / "keys" / "team" / "tenant.pub")


class StateFileTests(unittest.TestCase):
    def test_state_file_follows_vm_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root):
                self.assertEqual(
                    config.state_file_for_vm("demo", {}),
                    repo_root / "data" / "vm" / "state" / "demo.yaml",
                )

    def test_save_and_load_vm_state_use_global_default_state_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            legacy_root = repo_root / ".build"
            state = {"network": {"name": "demo-net"}, "ports": [{"host": 2222}]}

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", legacy_root
            ), patch.object(config, "load_global_config", return_value={}):
                config.save_vm_state("demo", state)
                loaded = config.load_vm_state("demo")
                self.assertTrue((repo_root / "data" / "vm" / "state" / "demo.yaml").exists())

        self.assertEqual(loaded, state)

    def test_save_and_load_vm_state_use_global_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            legacy_root = repo_root / ".build"
            global_config = {"paths": {"vm_state_dir": "custom/state"}}
            state = {"network": {"name": "demo-net"}}

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", legacy_root
            ), patch.object(config, "load_global_config", return_value=global_config):
                config.save_vm_state("demo", state)
                loaded = config.load_vm_state("demo")
                self.assertTrue((repo_root / "data" / "custom" / "state" / "demo.yaml").exists())

        self.assertEqual(loaded, state)

    def test_load_vm_state_returns_empty_dict_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", repo_root / ".build"
            ), patch.object(config, "load_global_config", return_value={}):
                self.assertEqual(config.load_vm_state("missing"), {})

    def test_delete_vm_state_removes_new_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            legacy_root = repo_root / ".build"

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", legacy_root
            ), patch.object(config, "load_global_config", return_value={}):
                config.save_vm_state("demo", {"vm_name": "demo"})
                config.delete_vm_state("demo")

                self.assertFalse(config.state_file_for_vm("demo", {}).exists())

    def test_load_vm_state_falls_back_to_legacy_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            legacy_root = repo_root / ".build"
            legacy_state_path = legacy_root / "demo" / "state.yaml"
            legacy_state_path.parent.mkdir(parents=True)
            legacy_state_path.write_text("network:\n  name: demo-net\n", encoding="utf-8")

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", legacy_root
            ), patch.object(config, "load_global_config", return_value={}):
                loaded = config.load_vm_state("demo")

        self.assertEqual(loaded["network"], {"name": "demo-net"})
        self.assertEqual(loaded["vm_data_dir"], str(legacy_root / "demo"))

    def test_load_vm_state_maps_legacy_provider_key_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            state_root = repo_root / "data" / "vm" / "state"
            state_root.mkdir(parents=True)
            state_path = state_root / "demo.yaml"
            state_path.write_text(
                "provider_private_key: /vm/keys/provider/demo_provider_ed25519\n",
                encoding="utf-8",
            )

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", repo_root / ".build"
            ), patch.object(config, "load_global_config", return_value={}):
                loaded = config.load_vm_state("demo")

        self.assertEqual(
            loaded["admin_private_key"],
            "/vm/keys/provider/demo_provider_ed25519",
        )

    def test_load_vm_state_rewrites_stale_config_path_to_current_saved_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            state_root = repo_root / "data" / "vm" / "state"
            config_root = repo_root / "data" / "configs"
            state_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            current_config_path = config_root / "demo.yaml"
            current_config_path.write_text("vm:\n  name: demo\n", encoding="utf-8")

            stale_config_path = repo_root / "runtime" / "configs" / "demo.yaml"
            (state_root / "demo.yaml").write_text(
                f"config_path: {stale_config_path}\n",
                encoding="utf-8",
            )

            with patch.object(config, "PROJECT_DIR", repo_root), patch.object(
                config, "LEGACY_VM_BUILD_DIR", repo_root / ".build"
            ), patch.object(config, "load_global_config", return_value={}):
                loaded = config.load_vm_state("demo")

        self.assertEqual(loaded["config_path"], str(current_config_path))


class LoadConfigFromStdinTests(unittest.TestCase):
    """Tests for loading configuration from stdin or pipes."""

    def test_load_config_from_stdin_with_valid_yaml(self):
        """Test loading a valid YAML config from stdin."""
        yaml_content = """
vm:
  name: demo
  user: tenant
  ram_mb: 4096
  vcpus: 2
  disk_gb: 40

network:
  mode: nat-auto

packages:
  - htop
"""
        with patch("sys.stdin", read=lambda: yaml_content.encode("utf-8")):
            result = config.load_config_from_stdin()

        self.assertEqual(result["vm"]["name"], "demo")
        self.assertEqual(result["vm"]["user"], "tenant")
        self.assertEqual(result["vm"]["ram_mb"], 4096)
        self.assertEqual(result["network"]["mode"], "nat-auto")
        self.assertEqual(result["packages"], ["htop"])

    def test_load_config_from_stdin_with_buffer(self):
        """Test loading config from a buffer-like stdin."""
        import io

        yaml_content = """
vm:
  name: test-vm
  user: admin
  ram_mb: 2048

network:
  mode: bridge
  bridge_name: br0
"""
        stdin_buffer = io.StringIO(yaml_content)
        with patch("sys.stdin", stdin_buffer):
            result = config.load_config_from_stdin()

        self.assertEqual(result["vm"]["name"], "test-vm")
        self.assertEqual(result["vm"]["ram_mb"], 2048)
        self.assertEqual(result["network"]["mode"], "bridge")
        self.assertEqual(result["network"]["bridge_name"], "br0")

    def test_load_config_from_stdin_raises_on_invalid_yaml(self):
        """Test that invalid YAML raises an appropriate error."""
        import io

        invalid_yaml = """
vm:
  name: demo
  invalid: [unclosed bracket
"""
        stdin_buffer = io.StringIO(invalid_yaml)
        with patch("sys.stdin", stdin_buffer):
            with self.assertRaises(Exception):  # yaml.YAMLError or similar
                config.load_config_from_stdin()

    def test_load_config_from_stdin_with_empty_input(self):
        """Test that empty stdin raises or returns None."""
        import io

        stdin_buffer = io.StringIO("")
        with patch("sys.stdin", stdin_buffer):
            result = config.load_config_from_stdin()
            # Empty YAML returns None
            self.assertIsNone(result)

    def test_load_config_from_stdin_with_minimal_config(self):
        """Test loading minimal valid config from stdin."""
        import io

        yaml_content = "vm:\n  name: minimal\n"
        stdin_buffer = io.StringIO(yaml_content)
        with patch("sys.stdin", stdin_buffer):
            result = config.load_config_from_stdin()

        self.assertEqual(result["vm"]["name"], "minimal")
