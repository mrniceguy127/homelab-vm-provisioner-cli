import contextlib
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import call, patch

from homelab_vm_provisioner import cli

from .helpers import completed_process


def printed_output(print_mock):
    return "\n".join(
        " ".join(str(arg) for arg in printed_call.args)
        for printed_call in print_mock.call_args_list
    )


class BuildNetworkConfigTests(unittest.TestCase):
    def test_builds_nat_auto_network(self):
        with patch.object(
            cli,
            "pick_free_subnet",
            return_value={
                "prefix": "192.168.120",
                "cidr": "192.168.120.0/24",
                "gateway": "192.168.120.1",
                "vm_ip": "192.168.120.50",
                "dhcp_start": "192.168.120.50",
                "dhcp_end": "192.168.120.99",
            },
        ), patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            self.assertEqual(
                cli.build_network_config("demo", {"mode": "nat-auto"}),
                {
                    "mode": "nat-auto",
                    "mac": "52:54:00:aa:bb:cc",
                    "prefix": "192.168.120",
                    "cidr": "192.168.120.0/24",
                    "gateway": "192.168.120.1",
                    "vm_ip": "192.168.120.50",
                    "dhcp_start": "192.168.120.50",
                    "dhcp_end": "192.168.120.99",
                    "name": "demo-net",
                    "libvirt_network_name": "demo-net",
                    "bridge_name": cli.default_nat_bridge_name("demo"),
                    "profile": "isolated_nat",
                },
            )

    def test_builds_bridge_network(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            self.assertEqual(
                cli.build_network_config("demo", {"mode": "bridge", "bridge_name": "br1"}),
                {
                    "mode": "bridge",
                    "mac": "52:54:00:aa:bb:cc",
                    "bridge_name": "br1",
                    "vm_ip": "dhcp-from-router",
                    "cidr": "main-lan",
                },
            )

    def test_raises_for_missing_nat_custom_fields(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            with self.assertRaisesRegex(ValueError, "Missing nat-custom network fields"):
                cli.build_network_config("demo", {"mode": "nat-custom"})

    def test_raises_for_invalid_network_mode(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            with self.assertRaisesRegex(ValueError, "network.mode"):
                cli.build_network_config("demo", {"mode": "invalid"})

    def test_builds_nat_custom_network_from_explicit_fields(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            self.assertEqual(
                cli.build_network_config(
                    "demo",
                    {
                        "mode": "nat-custom",
                        "cidr": "192.168.240.0/24",
                        "gateway": "192.168.240.1",
                        "vm_ip": "192.168.240.60",
                        "dhcp_start": "192.168.240.60",
                        "dhcp_end": "192.168.240.99",
                    },
                ),
                {
                    "mode": "nat-custom",
                    "mac": "52:54:00:aa:bb:cc",
                    "cidr": "192.168.240.0/24",
                    "gateway": "192.168.240.1",
                    "vm_ip": "192.168.240.60",
                    "dhcp_start": "192.168.240.60",
                    "dhcp_end": "192.168.240.99",
                    "name": "demo-net",
                    "libvirt_network_name": "demo-net",
                    "bridge_name": cli.default_nat_bridge_name("demo"),
                    "profile": "isolated_nat",
                },
            )

    def test_raises_for_invalid_nat_custom_subnet_prefix(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            with self.assertRaisesRegex(ValueError, "network.subnet_prefix"):
                cli.build_network_config(
                    "demo",
                    {"mode": "nat-custom", "subnet_prefix": "192.168.300"},
                )

    def test_raises_for_nat_custom_address_outside_cidr(self):
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"):
            with self.assertRaisesRegex(ValueError, "network.gateway must be inside network"):
                cli.build_network_config(
                    "demo",
                    {
                        "mode": "nat-custom",
                        "cidr": "192.168.240.0/24",
                        "gateway": "192.168.241.1",
                        "vm_ip": "192.168.240.50",
                        "dhcp_start": "192.168.240.50",
                        "dhcp_end": "192.168.240.99",
                    },
                )

    def test_raises_for_invalid_nat_custom_cidr(self):
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 network"):
            cli._validate_nat_custom_network(
                {
                    "cidr": "not-a-network",
                    "gateway": "192.168.240.1",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.50",
                    "dhcp_end": "192.168.240.99",
                }
            )

    def test_raises_for_nat_custom_non_slash_24_cidr(self):
        with self.assertRaisesRegex(ValueError, "/24 network"):
            cli._validate_nat_custom_network(
                {
                    "cidr": "192.168.240.0/25",
                    "gateway": "192.168.240.1",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.50",
                    "dhcp_end": "192.168.240.99",
                }
            )

    def test_raises_for_invalid_nat_custom_ipv4_address(self):
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 address"):
            cli._validate_nat_custom_network(
                {
                    "cidr": "192.168.240.0/24",
                    "gateway": "bad-address",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.50",
                    "dhcp_end": "192.168.240.99",
                }
            )

    def test_raises_for_nat_custom_ipv6_address(self):
        with self.assertRaisesRegex(ValueError, "Must be an IPv4 address"):
            cli._validate_nat_custom_network(
                {
                    "cidr": "192.168.240.0/24",
                    "gateway": "::1",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.50",
                    "dhcp_end": "192.168.240.99",
                }
            )

    def test_raises_when_dhcp_start_is_greater_than_dhcp_end(self):
        with self.assertRaisesRegex(ValueError, "network.dhcp_start must not be greater"):
            cli._validate_nat_custom_network(
                {
                    "cidr": "192.168.240.0/24",
                    "gateway": "192.168.240.1",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.99",
                    "dhcp_end": "192.168.240.50",
                }
            )


class VmNameValidationTests(unittest.TestCase):
    def test_accepts_vm_name_at_limit(self):
        self.assertIsNone(cli.validate_vm_name("a" * 63))

    def test_rejects_vm_name_over_limit(self):
        with self.assertRaisesRegex(ValueError, "vm.name must be 63 characters or fewer"):
            cli.validate_vm_name("a" * 64)


class SummaryTests(unittest.TestCase):
    def test_print_create_summary_formats_bridge_access(self):
        with patch("builtins.print") as print_mock:
            admin_key = Path("/keys/demo_admin_ed25519")
            cli.print_create_summary(
                "demo",
                "tenant",
                "trusted",
                {
                    "mode": "bridge",
                    "vm_ip": "dhcp-from-router",
                    "mac": "52:54:00:aa:bb:cc",
                },
                admin_key,
                [],
            )

        printed = printed_output(print_mock)
        self.assertIn("Admin SSH:", printed)
        self.assertIn(f"ssh -i {admin_key} vmadmin@VM_LAN_IP", printed)

    def test_print_create_summary_omits_ssh_sections_when_no_guest_ssh_port_exists(self):
        with patch("builtins.print") as print_mock:
            cli.print_create_summary(
                "demo",
                "tenant",
                "trusted",
                {
                    "mode": "nat-custom",
                    "vm_ip": "192.168.240.50",
                    "mac": "52:54:00:aa:bb:cc",
                },
                Path("/keys/demo_admin_ed25519"),
                [{"host": 8080, "guest": 80}],
            )

        printed = printed_output(print_mock)
        self.assertNotIn("Admin SSH:", printed)
        self.assertNotIn("Tenant SSH:", printed)


class ParserAndMainTests(unittest.TestCase):
    def test_build_parser_parses_subcommands(self):
        parser = cli.build_parser()
        args = parser.parse_args(["destroy", "demo"])

        self.assertEqual(args.command, "destroy")
        self.assertEqual(args.name, "demo")

    def test_build_parser_parses_reconcile_flags(self):
        parser = cli.build_parser()
        args = parser.parse_args(["reconcile", "--policy-only", "--allow-destructive"])

        self.assertEqual(args.command, "reconcile")
        self.assertTrue(args.policy_only)
        self.assertTrue(args.allow_destructive)

    def test_main_dispatches_create(self):
        with patch.object(cli, "create") as create_mock:
            cli.main(["create", "configs/demo.yaml"])

        create_mock.assert_called_once_with("configs/demo.yaml")

    def test_main_dispatches_destroy(self):
        with patch.object(cli, "destroy") as destroy_mock:
            cli.main(["destroy", "demo"])

        destroy_mock.assert_called_once_with("demo")

    def test_main_dispatches_reconcile_with_flags(self):
        with patch.object(cli, "reconcile_networking") as reconcile_mock:
            cli.main(["reconcile", "--policy-only", "--allow-destructive"])

        reconcile_mock.assert_called_once_with(policy_only=True, allow_destructive=True)

    def test_main_dispatches_ssh_admin(self):
        with patch.object(cli, "ssh_admin") as ssh_admin_mock:
            cli.main(["ssh-admin", "demo", "--ip", "192.168.1.50"])

        ssh_admin_mock.assert_called_once_with("demo", "192.168.1.50")

    def test_main_ignores_unrecognized_command_objects(self):
        fake_parser = type(
            "Parser",
            (),
            {"parse_args": lambda self, argv=None: type("Args", (), {"command": "noop"})()},
        )()

        with patch.object(cli, "build_parser", return_value=fake_parser), patch.object(
            cli, "create"
        ) as create_mock, patch.object(cli, "destroy") as destroy_mock, patch.object(
            cli, "ssh_admin"
        ) as ssh_admin_mock:
            self.assertIsNone(cli.main([]))

        create_mock.assert_not_called()
        destroy_mock.assert_not_called()
        ssh_admin_mock.assert_not_called()

    def test_build_parser_accepts_no_config_for_stdin(self):
        """Test that the parser accepts omitted config argument for stdin."""
        parser = cli.build_parser()
        args = parser.parse_args(["create"])

        self.assertEqual(args.command, "create")
        self.assertIsNone(args.config)

    def test_main_dispatches_create_without_config_for_stdin(self):
        """Test that main() dispatches create with None when no config provided."""
        with patch.object(cli, "create") as create_mock:
            cli.main(["create"])

        create_mock.assert_called_once_with(None)


class CreateTests(unittest.TestCase):
    def test_builds_nat_custom_network_from_subnet_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    f"""\
                    vm:
                      name: demo
                      user: tenant
                      ssh_key_file: {tenant_key.as_posix()}
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40
                      allow_sudo: false
                      trust: untrusted
                      template: base

                    network:
                      mode: nat-custom
                      subnet_prefix: 192.168.240

                    packages:
                      - htop

                    ports:
                      - host: 2222
                        guest: 22
                    """
                ),
                encoding="utf-8",
            )

            vm_data_dir = tmpdir_path / "vm" / "data" / "demo"
            admin_key_dir = tmpdir_path / "vm" / "keys" / "admin"
            admin_key = admin_key_dir / "demo_admin_ed25519"
            global_config = {
                "paths": {
                    "vm_data_dir": "vm/data",
                    "admin_key_dir": "vm/keys/admin",
                    "user_key_dir": "vm/keys/users",
                    "vm_state_dir": "vm/state",
                }
            }
            image_settings = {
                "name": "ubuntu-24.04.img",
                "url": "https://example.invalid/images/ubuntu-24.04.img",
                "os_variant": "ubuntu24.04",
            }
            dns_settings = {"resolvers": ("1.1.1.1", "1.0.0.1")}

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value=global_config
            ), patch.object(
                cli, "vm_data_dir_for_config", return_value=vm_data_dir
            ) as vm_data_dir_mock, patch.object(
                cli, "default_admin_key_dir", return_value=admin_key_dir
            ) as admin_key_dir_mock, patch.object(
                cli,
                "admin_keypair",
                return_value=(admin_key, "ssh-ed25519 AAA admin"),
            ) as admin_keypair_mock, patch.object(
                cli, "random_mac", return_value="52:54:00:aa:bb:cc"
            ), patch.object(
                cli, "run"
            ), patch.object(
                cli, "image_settings_for_config", return_value=image_settings
            ) as image_settings_mock, patch.object(
                cli, "dns_settings_for_config", return_value=dns_settings
            ) as dns_settings_mock, patch.object(
                cli, "validate_os_variant"
            ) as validate_os_variant_mock, patch.object(
                cli, "ensure_base_image", return_value=Path("/images/ubuntu-24.04.img")
            ), patch.object(
                cli, "create_vm_disk", return_value=Path("/images/demo.qcow2")
            ), patch.object(
                cli, "create_nat_network"
            ) as create_nat_network_mock, patch.object(
                cli,
                "render_templates",
                return_value=(Path("/build/user-data"), Path("/build/meta-data")),
            ) as render_templates_mock, patch.object(
                cli, "save_vm_state"
            ) as save_state_mock, patch.object(
                cli, "create_seed_iso", return_value=Path("/images/demo-seed.iso")
            ), patch.object(
                cli, "virt_install"
            ) as virt_install_mock, patch.object(
                cli, "reconcile_networking"
            ) as reconcile_mock:
                cli.create(str(config_path))

        expected_network = {
            "mode": "nat-custom",
            "mac": "52:54:00:aa:bb:cc",
            "prefix": "192.168.240",
            "cidr": "192.168.240.0/24",
            "gateway": "192.168.240.1",
            "vm_ip": "192.168.240.50",
            "dhcp_start": "192.168.240.50",
            "dhcp_end": "192.168.240.99",
            "name": "demo-net",
            "libvirt_network_name": "demo-net",
            "bridge_name": cli.default_nat_bridge_name("demo"),
            "profile": "isolated_nat",
        }

        vm_data_dir_mock.assert_called_once()
        admin_key_dir_mock.assert_called_once_with(global_config)
        admin_keypair_mock.assert_called_once_with(
            "demo",
            admin_key_dir=admin_key_dir,
        )
        image_settings_mock.assert_called_once_with(
            {
                "vm": {
                    "name": "demo",
                    "user": "tenant",
                    "ssh_key_file": tenant_key.as_posix(),
                    "ram_mb": 4096,
                    "vcpus": 2,
                    "disk_gb": 40,
                    "allow_sudo": False,
                    "trust": "untrusted",
                    "template": "base",
                },
                "network": {
                    "mode": "nat-custom",
                    "subnet_prefix": "192.168.240",
                },
                "packages": ["htop"],
                "ports": [{"host": 2222, "guest": 22}],
            },
            global_config=global_config,
        )
        dns_settings_mock.assert_called_once_with(
            {
                "vm": {
                    "name": "demo",
                    "user": "tenant",
                    "ssh_key_file": tenant_key.as_posix(),
                    "ram_mb": 4096,
                    "vcpus": 2,
                    "disk_gb": 40,
                    "allow_sudo": False,
                    "trust": "untrusted",
                    "template": "base",
                },
                "network": {
                    "mode": "nat-custom",
                    "subnet_prefix": "192.168.240",
                },
                "packages": ["htop"],
                "ports": [{"host": 2222, "guest": 22}],
            },
            global_config=global_config,
        )
        validate_os_variant_mock.assert_called_once_with("ubuntu24.04")
        create_nat_network_mock.assert_called_once_with("demo", expected_network)

        render_context, template_name, render_vm_data_dir = render_templates_mock.call_args.args
        self.assertEqual(template_name, "base")
        self.assertEqual(render_vm_data_dir, vm_data_dir)
        self.assertEqual(
            render_context,
            {
                "vm_name": "demo",
                "admin_user": "vmadmin",
                "admin_public_key": "ssh-ed25519 AAA admin",
                "vm_user": "tenant",
                "vm_public_key": "ssh-ed25519 AAA tenant",
                "vm_sudo": "false",
                "packages": ("htop",),
                "dns_resolvers": ("1.1.1.1", "1.0.0.1"),
                "setup_script_content": None,
            },
        )

        first_state = save_state_mock.call_args_list[0].args[1]
        self.assertEqual(first_state["config_path"], str(config_path))
        self.assertEqual(first_state["vm_data_dir"], str(vm_data_dir))
        self.assertEqual(first_state["admin_private_key"], str(admin_key))

        second_state = save_state_mock.call_args_list[1].args[1]
        self.assertEqual(second_state["network"], expected_network)

        virt_install_mock.assert_called_once_with(
            "demo",
            {
                "name": "demo",
                "user": "tenant",
                "ssh_key_file": tenant_key.as_posix(),
                "ram_mb": 4096,
                "vcpus": 2,
                "disk_gb": 40,
                "allow_sudo": False,
                "trust": "untrusted",
                "template": "base",
            },
            "network=demo-net,model=virtio,mac=52:54:00:aa:bb:cc",
            Path("/images/demo.qcow2"),
            Path("/images/demo-seed.iso"),
            "ubuntu24.04",
        )
        reconcile_mock.assert_called_once_with(policy_only=True)
        self.assertEqual(save_state_mock.call_count, 2)

    def test_rejects_invalid_trust_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")
            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    f"""\
                    vm:
                      name: demo
                      user: tenant
                      ssh_key_file: {tenant_key.as_posix()}
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40
                      trust: maybe
                    """
                ),
                encoding="utf-8",
            )

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ):
                with self.assertRaisesRegex(ValueError, "vm.trust"):
                    cli.create(str(config_path))

    def test_rejects_vm_name_that_is_too_long(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")
            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    f"""\
                    vm:
                      name: {'a' * 64}
                      user: tenant
                      ssh_key_file: {tenant_key.as_posix()}
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40
                    """
                ),
                encoding="utf-8",
            )

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(cli, "save_vm_state") as save_vm_state_mock:
                with self.assertRaisesRegex(ValueError, "vm.name must be 63 characters or fewer"):
                    cli.create(str(config_path))

        save_vm_state_mock.assert_not_called()

    def test_raises_when_vm_ssh_key_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    """\
                    vm:
                      name: demo
                      user: tenant
                      ssh_key_file: missing.pub
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40
                    """
                ),
                encoding="utf-8",
            )

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(
                cli, "resolve_user_key_path", return_value=Path(tmpdir) / "missing.pub"
            ):
                with self.assertRaisesRegex(FileNotFoundError, "Missing VM SSH key file"):
                    cli.create(str(config_path))

    def test_raises_early_when_os_variant_is_unsupported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")
            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    f"""\
                    vm:
                      name: demo
                      user: tenant
                      ssh_key_file: {tenant_key.as_posix()}
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40
                    """
                ),
                encoding="utf-8",
            )

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(
                cli, "image_settings_for_config", return_value={"os_variant": "debian12"}
            ), patch.object(
                cli, "validate_os_variant", side_effect=ValueError("bad os variant")
            ), patch.object(cli, "save_vm_state") as save_vm_state_mock:
                with self.assertRaisesRegex(ValueError, "bad os variant"):
                    cli.create(str(config_path))

        save_vm_state_mock.assert_not_called()

    def test_allows_vm_creation_without_tenant_ssh_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    """\
                    vm:
                      name: demo
                      user: tenant
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40

                    network:
                      mode: nat-custom
                      subnet_prefix: 192.168.240
                    """
                ),
                encoding="utf-8",
            )

            vm_data_dir = tmpdir_path / "vm" / "data" / "demo"
            admin_key_dir = tmpdir_path / "vm" / "keys" / "admin"
            admin_key = admin_key_dir / "demo_admin_ed25519"
            image_settings = {
                "name": "ubuntu-24.04.img",
                "url": "https://example.invalid/images/ubuntu-24.04.img",
                "os_variant": "ubuntu24.04",
            }
            dns_settings = {"resolvers": ("9.9.9.9", "149.112.112.112")}

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(
                cli, "resolve_user_key_path"
            ) as resolve_user_key_path_mock, patch.object(
                cli, "vm_data_dir_for_config", return_value=vm_data_dir
            ), patch.object(
                cli, "default_admin_key_dir", return_value=admin_key_dir
            ), patch.object(
                cli, "admin_keypair", return_value=(admin_key, "ssh-ed25519 AAA admin")
            ), patch.object(
                cli, "random_mac", return_value="52:54:00:aa:bb:cc"
            ), patch.object(
                cli, "run"
            ), patch.object(
                cli, "image_settings_for_config", return_value=image_settings
            ), patch.object(
                cli, "dns_settings_for_config", return_value=dns_settings
            ), patch.object(
                cli, "validate_os_variant"
            ), patch.object(
                cli, "ensure_base_image", return_value=Path("/images/ubuntu-24.04.img")
            ), patch.object(
                cli, "create_vm_disk", return_value=Path("/images/demo.qcow2")
            ), patch.object(
                cli, "create_nat_network"
            ), patch.object(
                cli,
                "render_templates",
                return_value=(Path("/build/user-data"), Path("/build/meta-data")),
            ) as render_templates_mock, patch.object(
                cli, "save_vm_state"
            ) as save_state_mock, patch.object(
                cli, "create_seed_iso", return_value=Path("/images/demo-seed.iso")
            ), patch.object(
                cli, "virt_install"
            ), patch.object(
                cli, "reconcile_networking"
            ):
                cli.create(str(config_path))

        resolve_user_key_path_mock.assert_not_called()
        render_context, _, _ = render_templates_mock.call_args.args
        self.assertIsNone(render_context["vm_public_key"])
        self.assertEqual(render_context["dns_resolvers"], ("9.9.9.9", "149.112.112.112"))
        first_state = save_state_mock.call_args_list[0].args[1]
        self.assertEqual(first_state["admin_private_key"], str(admin_key))

    def test_bridge_mode_skips_nft_policy_and_uses_bridge_network_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")
            config_path = tmpdir_path / "demo.yaml"
            config_path.write_text(
                textwrap.dedent(
                    f"""\
                    vm:
                      name: demo
                      user: tenant
                      ssh_key_file: {tenant_key.as_posix()}
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40

                    network:
                      mode: bridge
                      bridge_name: br1
                    """
                ),
                encoding="utf-8",
            )

            vm_data_dir = tmpdir_path / "vm" / "data" / "demo"
            admin_key = tmpdir_path / "vm" / "keys" / "admin" / "demo_admin_ed25519"
            image_settings = {
                "name": "ubuntu-24.04.img",
                "url": "https://example.invalid/images/ubuntu-24.04.img",
                "os_variant": "ubuntu24.04",
            }
            dns_settings = {"resolvers": ("1.1.1.1", "1.0.0.1")}

            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(
                cli, "vm_data_dir_for_config", return_value=vm_data_dir
            ), patch.object(
                cli, "default_admin_key_dir", return_value=tmpdir_path / "vm" / "keys" / "admin"
            ), patch.object(
                cli, "admin_keypair", return_value=(admin_key, "ssh-ed25519 AAA admin")
            ), patch.object(
                cli, "random_mac", return_value="52:54:00:aa:bb:cc"
            ), patch.object(
                cli, "run"
            ), patch.object(
                cli, "image_settings_for_config", return_value=image_settings
            ), patch.object(
                cli, "dns_settings_for_config", return_value=dns_settings
            ), patch.object(
                cli, "validate_os_variant"
            ), patch.object(
                cli, "ensure_base_image", return_value=Path("/images/ubuntu-24.04.img")
            ), patch.object(
                cli, "create_vm_disk", return_value=Path("/images/demo.qcow2")
            ), patch.object(
                cli,
                "render_templates",
                return_value=(Path("/build/user-data"), Path("/build/meta-data")),
            ), patch.object(
                cli, "save_vm_state"
            ) as save_state_mock, patch.object(
                cli, "create_seed_iso", return_value=Path("/images/demo-seed.iso")
            ), patch.object(
                cli, "virt_install"
            ) as virt_install_mock, patch.object(
                cli, "reconcile_networking"
            ) as reconcile_mock, patch("builtins.print") as print_mock:
                cli.create(str(config_path))

        reconcile_mock.assert_not_called()
        self.assertEqual(save_state_mock.call_count, 1)
        virt_install_mock.assert_called_once_with(
            "demo",
            {
                "name": "demo",
                "user": "tenant",
                "ssh_key_file": tenant_key.as_posix(),
                "ram_mb": 4096,
                "vcpus": 2,
                "disk_gb": 40,
            },
            "bridge=br1,model=virtio,mac=52:54:00:aa:bb:cc",
            Path("/images/demo.qcow2"),
            Path("/images/demo-seed.iso"),
            "ubuntu24.04",
        )
        printed = printed_output(print_mock)
        self.assertIn("Bridge mode selected", printed)

    def test_managed_create_validates_networking_before_saving_state(self):
        definition = {
            "vm_name": "demo",
            "vm": {
                "name": "demo",
                "owner_user_id": "user-admin",
                "network_group_id": "ng-demo",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
                "allow_same_group_traffic": True,
                "allow_private_lan_access": False,
                "internet_access": True,
            },
            "network": {
                "network_group_id": "ng-demo",
                "group_name": "default-admin",
                "profile": "isolated_nat",
                "libvirt_network_name": "hvp-ng-demo",
                "name": "hvp-ng-demo",
                "bridge_name": "hvpb-demo",
                "subnet_cidr": "10.80.0.0/28",
                "gateway_ip": "10.80.0.1",
                "dhcp_start": "10.80.0.2",
                "dhcp_end": "10.80.0.14",
                "vm_ip": "10.80.0.2",
                "mac": "52:54:00:11:22:33",
            },
            "ports": [],
            "resolved_config_path": "/configs/demo.yaml",
            "state": {"vm_name": "demo"},
        }

        with patch.object(cli, "require_tools"), patch.object(
            cli, "resolve_config_path", return_value="/configs/demo.yaml"
        ), patch.object(
            cli, "load_config", return_value={"vm": {"name": "demo"}}
        ), patch.object(
            cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()
        ), patch.object(
            cli, "prepare_vm_definition", return_value=definition
        ), patch.object(
            cli, "configured_vm_records", return_value=[]
        ), patch.object(
            cli, "validate_networking_changes", side_effect=RuntimeError("blocked")
        ) as validate_mock, patch.object(cli, "save_vm_state") as save_state_mock:
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                cli.create("/configs/demo.yaml")

        validate_mock.assert_called_once()
        save_state_mock.assert_not_called()

    def test_create_with_stdin_config(self):
        """Test that create command can accept config via stdin when no config argument provided."""
        with tempfile.TemporaryDirectory() as tmpdir, contextlib.ExitStack() as stack:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            config_data = {
                "vm": {
                    "name": "demo-stdin",
                    "user": "tenant",
                    "ssh_key_file": tenant_key.as_posix(),
                    "ram_mb": 4096,
                    "vcpus": 2,
                    "disk_gb": 40,
                    "allow_sudo": False,
                    "trust": "untrusted",
                    "template": "base",
                },
                "network": {
                    "mode": "nat-auto",
                },
                "packages": ["htop"],
                "ports": [{"host": 2222, "guest": 22}],
            }

            vm_data_dir = tmpdir_path / "vm" / "data" / "demo-stdin"
            admin_key_dir = tmpdir_path / "vm" / "keys" / "admin"
            admin_key = admin_key_dir / "demo-stdin_admin_ed25519"
            global_config = {
                "paths": {
                    "vm_data_dir": "vm/data",
                    "admin_key_dir": "vm/keys/admin",
                    "user_key_dir": "vm/keys/users",
                    "vm_state_dir": "vm/state",
                }
            }
            image_settings = {
                "name": "ubuntu-24.04.img",
                "url": "https://example.invalid/images/ubuntu-24.04.img",
                "os_variant": "ubuntu24.04",
            }
            dns_settings = {"resolvers": ("1.1.1.1", "1.0.0.1")}

            stack.enter_context(patch.object(cli, "require_tools"))
            stack.enter_context(patch.object(cli, "load_global_config", return_value=global_config))
            load_stdin_mock = stack.enter_context(patch.object(cli, "load_config_from_stdin", return_value=config_data))
            stack.enter_context(patch.object(cli, "vm_data_dir_for_config", return_value=vm_data_dir))
            stack.enter_context(patch.object(cli, "default_admin_key_dir", return_value=admin_key_dir))
            stack.enter_context(patch.object(cli, "admin_keypair", return_value=(admin_key, "ssh-ed25519 AAA admin")))
            stack.enter_context(patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"))
            stack.enter_context(patch.object(cli, "run"))
            stack.enter_context(patch.object(cli, "image_settings_for_config", return_value=image_settings))
            stack.enter_context(patch.object(cli, "dns_settings_for_config", return_value=dns_settings))
            stack.enter_context(patch.object(cli, "validate_os_variant"))
            stack.enter_context(patch.object(cli, "ensure_base_image", return_value=Path("/images/ubuntu-24.04.img")))
            stack.enter_context(patch.object(cli, "create_vm_disk", return_value=Path("/images/demo-stdin.qcow2")))
            stack.enter_context(patch.object(cli, "create_nat_network"))
            stack.enter_context(patch.object(cli, "render_templates", return_value=(Path("/build/user-data"), Path("/build/meta-data"))))
            stack.enter_context(patch.object(cli, "save_vm_state"))
            stack.enter_context(patch.object(cli, "create_seed_iso", return_value=Path("/images/demo-stdin-seed.iso")))
            virt_install_mock = stack.enter_context(patch.object(cli, "virt_install"))
            stack.enter_context(patch.object(cli, "reconcile_networking"))
            stack.enter_context(patch.object(cli, "pick_free_subnet", return_value={
                "prefix": "192.168.120",
                "cidr": "192.168.120.0/24",
                "gateway": "192.168.120.1",
                "vm_ip": "192.168.120.50",
                "dhcp_start": "192.168.120.50",
                "dhcp_end": "192.168.120.99",
            }))
            
            cli.create(None)

            # Verify stdin was read
            load_stdin_mock.assert_called_once()
            # Verify VM was created
            virt_install_mock.assert_called_once()
            self.assertEqual(virt_install_mock.call_args[0][0], "demo-stdin")


class CloneWithStdinTests(unittest.TestCase):
    def test_clone_with_stdin_config(self):
        """Test that clone command can accept config via stdin when no config argument provided."""
        with tempfile.TemporaryDirectory() as tmpdir, contextlib.ExitStack() as stack:
            tmpdir_path = Path(tmpdir)
            tenant_key = tmpdir_path / "tenant.pub"
            tenant_key.write_text("ssh-ed25519 AAA tenant\n", encoding="utf-8")

            config_data = {
                "vm": {
                    "name": "demo-clone",
                    "user": "tenant",
                    "ssh_key_file": tenant_key.as_posix(),
                    "ram_mb": 2048,
                    "vcpus": 1,
                    "disk_gb": 20,
                    "allow_sudo": False,
                    "trust": "untrusted",
                    "template": "base",
                },
                "network": {
                    "mode": "nat-auto",
                },
                "packages": ["vim"],
            }

            stack.enter_context(patch.object(cli, "require_tools"))
            load_stdin_mock = stack.enter_context(patch.object(cli, "load_config_from_stdin", return_value=config_data))
            stack.enter_context(patch.object(cli, "vm_exists", side_effect=[True, False, False]))
            stack.enter_context(patch.object(cli, "vm_disk_path", side_effect=[Path("/disk/source.qcow2"), Path("/disk/target.qcow2")]))
            stack.enter_context(patch.object(cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(cli, "prepare_vm_definition", return_value={
                "vm_name": "demo-clone",
                "vm_user": "tenant",
                "trust": "untrusted",
                "network": {
                    "mode": "nat-auto",
                    "name": "demo-clone-net",
                    "mac": "52:54:00:aa:bb:cc",
                    "vm_ip": "192.168.120.50",
                },
                "ports": [],
                "resolved_config_path": "<stdin>",
                "state": {"vm_name": "demo-clone"},
                "vm": config_data["vm"],
                "image_settings": {"os_variant": "ubuntu24.04"},
                "admin_private_key": Path("/keys/admin"),
            }))
            stack.enter_context(patch.object(cli, "save_vm_state"))
            stack.enter_context(patch.object(cli, "load_vm_state", return_value={"config_path": "/configs/source.yaml"}))
            stack.enter_context(patch.object(cli, "load_config", return_value={"vm": {"user": "olduser"}}))
            stack.enter_context(patch.object(cli, "stop_vm_domain", return_value=False))
            stack.enter_context(patch.object(cli, "ensure_host_services"))
            stack.enter_context(patch.object(cli, "copy_qcow2_image"))
            stack.enter_context(patch.object(cli, "prepare_cloned_guest_disk"))
            stack.enter_context(patch.object(cli, "create_nat_network"))
            stack.enter_context(patch.object(cli, "render_seed_iso_for_definition", return_value=Path("/seed.iso")))
            stack.enter_context(patch.object(cli, "virt_install"))
            stack.enter_context(patch.object(cli, "reconcile_networking"))
            stack.enter_context(patch.object(cli, "pick_free_subnet", return_value={}))
            stack.enter_context(patch("builtins.print"))
            stack.enter_context(patch.object(Path, "exists", lambda p: str(p) == "/disk/source.qcow2"))
            
            cli.clone("source-vm", None)

            # Verify stdin was read
            load_stdin_mock.assert_called_once()

    def test_clone_validates_required_vm_section(self):
        """Test that clone raises error if config is missing 'vm' section."""
        config_data = {"network": {"mode": "nat-auto"}}

        with patch.object(cli, "require_tools"), patch.object(
            cli, "load_config_from_stdin", return_value=config_data
        ):
            with self.assertRaisesRegex(ValueError, "Config must contain 'vm' section"):
                cli.clone("source-vm", None)

    def test_clone_validates_required_name_field(self):
        """Test that clone raises error if config is missing 'vm.name' field."""
        config_data = {"vm": {"user": "tenant"}}

        with patch.object(cli, "require_tools"), patch.object(
            cli, "load_config_from_stdin", return_value=config_data
        ):
            with self.assertRaisesRegex(ValueError, "Config 'vm' section must contain 'name' field"):
                cli.clone("source-vm", None)

    def test_clone_validates_required_user_field(self):
        """Test that clone raises error if config is missing 'vm.user' field."""
        config_data = {"vm": {"name": "demo"}}

        with patch.object(cli, "require_tools"), patch.object(
            cli, "load_config_from_stdin", return_value=config_data
        ):
            with self.assertRaisesRegex(ValueError, "Config 'vm' section must contain 'user' field"):
                cli.clone("source-vm", None)


class SnapshotRestoreTests(unittest.TestCase):
    def test_restore_preserves_snapshot_mac_and_nat_network_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            snapshot_path = tmpdir_path / "snapshots" / "snap-1"
            snapshot_path.mkdir(parents=True)
            (snapshot_path / "demo.qcow2").write_text("disk", encoding="utf-8")
            (snapshot_path / "demo-seed.iso").write_text("seed", encoding="utf-8")
            (snapshot_path / "config.yaml").write_text(
                textwrap.dedent(
                    """\
                    vm:
                      name: demo
                      user: tenant
                      ram_mb: 4096
                      vcpus: 2
                      disk_gb: 40

                    network:
                      mode: nat-auto
                    """
                ),
                encoding="utf-8",
            )
            (snapshot_path / "state.yaml").write_text(
                textwrap.dedent(
                    """\
                    vm_name: demo
                    config_path: /configs/demo.yaml
                    trust: trusted
                    ports:
                      - host: 2222
                        guest: 22
                    network:
                      mode: nat-auto
                      mac: 52:54:00:11:22:33
                      prefix: 192.168.240
                      cidr: 192.168.240.0/24
                      gateway: 192.168.240.1
                      vm_ip: 192.168.240.50
                      dhcp_start: 192.168.240.50
                      dhcp_end: 192.168.240.99
                      name: demo-net
                      bridge_name: {cli.default_nat_bridge_name('demo')}
                    """
                ),
                encoding="utf-8",
            )

            current_state = {
                "network": {
                    "mode": "nat-auto",
                    "mac": "52:54:00:aa:bb:cc",
                    "prefix": "192.168.122",
                    "cidr": "192.168.122.0/24",
                    "gateway": "192.168.122.1",
                    "vm_ip": "192.168.122.50",
                    "dhcp_start": "192.168.122.50",
                    "dhcp_end": "192.168.122.99",
                    "name": "demo-net",
                    "bridge_name": cli.default_nat_bridge_name("demo"),
                },
                "ports": [{"host": 2222, "guest": 22}],
            }
            restored_state = {
                "vm_name": "demo",
                "config_path": "/configs/demo.yaml",
                "trust": "trusted",
                "ports": [{"host": 2222, "guest": 22}],
                "network": {
                    "mode": "nat-auto",
                    "mac": "52:54:00:11:22:33",
                    "prefix": "192.168.240",
                    "cidr": "192.168.240.0/24",
                    "gateway": "192.168.240.1",
                    "vm_ip": "192.168.240.50",
                    "dhcp_start": "192.168.240.50",
                    "dhcp_end": "192.168.240.99",
                    "name": "demo-net",
                    "bridge_name": cli.default_nat_bridge_name("demo"),
                },
            }
            restored_config = {
                "vm": {
                    "name": "demo",
                    "user": "tenant",
                    "ram_mb": 4096,
                    "vcpus": 2,
                    "disk_gb": 40,
                },
                "network": {"mode": "nat-auto"},
            }

            target_config_path = tmpdir_path / "configs" / "demo.yaml"
            target_state_path = tmpdir_path / "vm" / "state" / "demo.yaml"
            vm_disk = tmpdir_path / "images" / "demo.qcow2"
            seed_iso = tmpdir_path / "images" / "demo-seed.iso"

            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(cli, "require_tools"))
                stack.enter_context(
                    patch.object(
                        cli,
                        "load_snapshot_metadata",
                        return_value={
                            "original_paths": {
                                "config_path": str(target_config_path),
                                "state_path": str(target_state_path),
                            }
                        },
                    )
                )
                stack.enter_context(
                    patch.object(cli, "snapshot_path_for_vm", return_value=snapshot_path)
                )
                stack.enter_context(
                    patch.object(cli, "host_lifecycle_lock", return_value=contextlib.nullcontext())
                )
                stack.enter_context(
                    patch.object(cli, "load_vm_state", side_effect=[current_state, restored_state])
                )
                stack.enter_context(
                    patch.object(cli, "merged_vm_network", return_value=current_state["network"])
                )
                stack.enter_context(patch.object(cli, "cleanup_vm_runtime_definition"))
                stack.enter_context(patch.object(cli, "copy_qcow2_image"))
                stack.enter_context(patch.object(cli, "copy_image_artifact"))
                stack.enter_context(patch.object(cli, "copy_local_file"))
                stack.enter_context(patch.object(cli, "copy_local_tree"))
                stack.enter_context(patch.object(cli, "load_config", return_value=restored_config))
                save_vm_state_mock = stack.enter_context(patch.object(cli, "save_vm_state"))
                stack.enter_context(patch.object(cli, "ensure_host_services"))
                create_nat_network_mock = stack.enter_context(
                    patch.object(cli, "create_nat_network")
                )
                virt_install_mock = stack.enter_context(patch.object(cli, "virt_install"))
                stack.enter_context(patch.object(cli, "stop_vm_domain"))
                stack.enter_context(patch.object(cli, "apply_runtime_networking"))
                stack.enter_context(patch.object(cli, "vm_disk_path", return_value=vm_disk))
                stack.enter_context(patch.object(cli, "seed_iso_path", return_value=seed_iso))
                stack.enter_context(patch.object(cli, "load_global_config", return_value={}))
                stack.enter_context(
                    patch.object(cli, "image_settings_for_config", return_value={"os_variant": "ubuntu24.04"})
                )
                stack.enter_context(
                    patch.object(
                        cli,
                        "pick_free_subnet",
                        side_effect=AssertionError("should not recalculate subnet"),
                    )
                )
                stack.enter_context(
                    patch.object(
                        cli,
                        "random_mac",
                        side_effect=AssertionError("should not regenerate MAC"),
                    )
                )
                stack.enter_context(patch("builtins.print"))

                cli.snapshot_restore("demo", "snap-1")

        saved_state = save_vm_state_mock.call_args.args[1]
        self.assertEqual(saved_state["network"]["mac"], "52:54:00:11:22:33")
        self.assertEqual(saved_state["network"]["prefix"], "192.168.240")
        create_nat_network_mock.assert_called_once_with("demo", saved_state["network"])
        virt_install_mock.assert_called_once_with(
            "demo",
            restored_config["vm"],
            "network=demo-net,model=virtio,mac=52:54:00:11:22:33",
            vm_disk,
            seed_iso,
            "ubuntu24.04",
        )


class SshAdminTests(unittest.TestCase):
    def test_raises_when_vm_is_missing(self):
        with patch.object(cli, "require_tools"), patch.object(cli, "vm_exists", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "VM not found"):
                cli.ssh_admin("demo")

    def test_connects_with_resolved_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            admin_key = Path(tmpdir) / "admin_ed25519"
            admin_key.write_text("private", encoding="utf-8")

            with patch.object(cli, "require_tools"), patch.object(
                cli, "vm_exists", return_value=True
            ), patch.object(
                cli, "load_vm_state", return_value={"admin_private_key": str(admin_key)}
            ), patch.object(
                cli, "resolve_vm_ipv4", return_value=("192.168.122.50", "agent")
            ), patch.object(
                cli.subprocess, "run", return_value=completed_process(returncode=7)
            ) as run_mock:
                with self.assertRaises(SystemExit) as exc:
                    cli.ssh_admin("demo")

        self.assertEqual(exc.exception.code, 7)
        run_mock.assert_called_once_with(
            [
                "ssh",
                "-i",
                str(admin_key),
                "-o",
                "IdentitiesOnly=yes",
                "vmadmin@192.168.122.50",
            ]
        )

    def test_raises_when_ip_cannot_be_resolved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            admin_key = Path(tmpdir) / "admin_ed25519"
            admin_key.write_text("private", encoding="utf-8")

            with patch.object(cli, "require_tools"), patch.object(
                cli, "vm_exists", return_value=True
            ), patch.object(
                cli, "load_vm_state", return_value={"admin_private_key": str(admin_key)}
            ), patch.object(cli, "resolve_vm_ipv4", return_value=(None, None)):
                with self.assertRaisesRegex(RuntimeError, "Could not determine the VM IP"):
                    cli.ssh_admin("demo")

    def test_falls_back_to_default_admin_key_dir_when_state_has_no_key_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            admin_key_dir = Path(tmpdir) / "vm" / "keys" / "admin"
            admin_key = admin_key_dir / "demo_admin_ed25519"
            admin_key_dir.mkdir(parents=True)
            admin_key.write_text("private", encoding="utf-8")

            with patch.object(cli, "require_tools"), patch.object(
                cli, "vm_exists", return_value=True
            ), patch.object(cli, "load_global_config", return_value={}), patch.object(
                cli, "load_vm_state", return_value={}
            ), patch.object(
                cli, "default_admin_key_dir", return_value=admin_key_dir
            ) as default_admin_key_dir_mock, patch.object(
                cli, "resolve_vm_ipv4", return_value=("192.168.122.50", "agent")
            ), patch.object(
                cli.subprocess, "run", return_value=completed_process(returncode=0)
            ):
                with self.assertRaises(SystemExit) as exc:
                    cli.ssh_admin("demo")

        self.assertEqual(exc.exception.code, 0)
        default_admin_key_dir_mock.assert_called_once()

    def test_uses_provided_ip_without_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            admin_key = Path(tmpdir) / "demo_admin_ed25519"
            admin_key.write_text("private", encoding="utf-8")

            with patch.object(cli, "require_tools"), patch.object(
                cli, "vm_exists", return_value=True
            ), patch.object(
                cli, "load_vm_state", return_value={"admin_private_key": str(admin_key)}
            ), patch.object(cli, "resolve_vm_ipv4") as resolve_vm_ipv4_mock, patch.object(
                cli.subprocess, "run", return_value=completed_process(returncode=0)
            ) as run_mock:
                with self.assertRaises(SystemExit) as exc:
                    cli.ssh_admin("demo", vm_ip="192.168.1.50")

        self.assertEqual(exc.exception.code, 0)
        resolve_vm_ipv4_mock.assert_not_called()
        run_mock.assert_called_once_with(
            [
                "ssh",
                "-i",
                str(admin_key),
                "-o",
                "IdentitiesOnly=yes",
                "vmadmin@192.168.1.50",
            ]
        )

    def test_raises_when_admin_key_is_missing(self):
        missing_key = Path("/missing/demo_admin_ed25519")

        with patch.object(cli, "require_tools"), patch.object(
            cli, "vm_exists", return_value=True
        ), patch.object(
            cli, "load_vm_state", return_value={"admin_private_key": str(missing_key)}
        ):
            with self.assertRaisesRegex(FileNotFoundError, "Missing admin SSH key"):
                cli.ssh_admin("demo")


class DestroyTests(unittest.TestCase):
    def test_destroy_validates_managed_networking_before_teardown(self):
        with patch.object(
            cli,
            "host_lifecycle_lock",
            return_value=contextlib.nullcontext(),
        ), patch.object(
            cli, "load_vm_state", return_value={"ports": []}
        ), patch.object(
            cli,
            "merged_vm_network",
            return_value={"network_group_id": "ng-demo", "libvirt_network_name": "hvp-ng-demo"},
        ), patch.object(
            cli, "configured_vm_records", return_value=[]
        ), patch.object(
            cli, "validate_networking_changes", side_effect=RuntimeError("blocked")
        ) as validate_mock, patch.object(
            cli, "cleanup_vm_runtime_definition"
        ) as cleanup_mock:
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                cli.destroy("demo")

        validate_mock.assert_called_once()
        cleanup_mock.assert_not_called()

    def test_destroy_merges_state_and_live_network_then_cleans_everything(self):
        state = {
            "admin_private_key": "/vm/keys/admin/demo_admin_ed25519",
            "vm_data_dir": "/vm/data/demo",
            "network": {
                "name": "state-net",
                "cidr": "192.168.240.0/24",
                "vm_ip": "192.168.240.50",
            },
            "ports": [{"host": 2222, "guest": 22, "proto": "tcp"}],
        }

        with patch.object(cli, "load_vm_state", return_value=state), patch.object(
            cli,
            "discover_vm_network",
            return_value={"name": "live-net", "vm_ip": "192.168.240.55"},
        ), patch.object(
            cli, "vm_exists", return_value=True
        ), patch.object(
            cli, "bridge_interface_exists", side_effect=[True, True]
        ) as bridge_exists_mock, patch.object(
            cli, "cleanup_bridge_interface"
        ) as cleanup_bridge_mock, patch.object(
            cli, "cleanup_vm_storage"
        ) as cleanup_storage_mock, patch.object(
            cli, "cleanup_local_vm_artifacts"
        ) as cleanup_artifacts_mock, patch.object(
            cli, "reconcile_networking"
        ) as reconcile_mock, patch.object(cli, "run") as run_mock:
            cli.destroy("demo")

        reconcile_mock.assert_called_once_with(policy_only=True)
        cleanup_storage_mock.assert_called_once_with("demo")
        self.assertEqual(bridge_exists_mock.call_count, 2)
        cleanup_bridge_mock.assert_has_calls(
            [call(cli.default_nat_bridge_name("demo")), call(cli.legacy_nat_bridge_name("demo"))],
            any_order=True,
        )
        cleanup_artifacts_mock.assert_called_once_with(
            "demo",
            admin_private_key="/vm/keys/admin/demo_admin_ed25519",
            vm_data_dir="/vm/data/demo",
        )
        self.assertEqual(
            run_mock.call_args_list,
            [
                call(["virsh", "destroy", "demo"], sudo=True, check=False),
                call(
                    ["virsh", "undefine", "demo", "--remove-all-storage"],
                    sudo=True,
                    check=False,
                ),
                call(["virsh", "net-destroy", "live-net"], sudo=True, check=False),
                call(["virsh", "net-undefine", "live-net"], sudo=True, check=False),
            ],
        )

    def test_destroy_skips_domain_teardown_when_vm_is_missing(self):
        with patch.object(cli, "load_vm_state", return_value={}), patch.object(
            cli, "discover_vm_network", return_value={}
        ), patch.object(cli, "vm_exists", return_value=False), patch.object(
            cli, "bridge_interface_exists", side_effect=[False, False]
        ), patch.object(
            cli, "cleanup_bridge_interface"
        ) as cleanup_bridge_mock, patch.object(cli, "cleanup_vm_storage"), patch.object(
            cli, "cleanup_local_vm_artifacts"
        ), patch.object(cli, "reconcile_networking") as reconcile_mock, patch.object(cli, "run") as run_mock:
            cli.destroy("demo")

        reconcile_mock.assert_called_once_with(policy_only=True)
        self.assertEqual(
            run_mock.call_args_list,
            [
                call(["virsh", "net-destroy", "demo-net"], sudo=True, check=False),
                call(["virsh", "net-undefine", "demo-net"], sudo=True, check=False),
            ],
        )
        cleanup_bridge_mock.assert_not_called()


class StopTests(unittest.TestCase):
    def test_stop_command_stops_running_vm(self):
        with patch.object(cli, "require_tools"), patch.object(
            cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()
        ), patch.object(
            cli, "stop_vm_domain", return_value=True
        ) as stop_domain_mock:
            cli.stop("demo")
        
        stop_domain_mock.assert_called_once_with("demo")

    def test_stop_command_skips_already_stopped_vm(self):
        with patch.object(cli, "require_tools"), patch.object(
            cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()
        ), patch.object(
            cli, "stop_vm_domain", return_value=False
        ) as stop_domain_mock:
            cli.stop("demo")
        
        stop_domain_mock.assert_called_once_with("demo")

    def test_stop_vm_domain_shuts_down_gracefully(self):
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "current_domain_state", side_effect=["running", "shut off"]
        ), patch.object(
            cli, "run"
        ) as run_mock, patch.object(
            cli.time, "monotonic", side_effect=[0, 1]
        ), patch.object(
            cli.time, "sleep"
        ):
            result = cli.stop_vm_domain("demo")
        
        self.assertTrue(result)
        run_mock.assert_called_once_with(["virsh", "shutdown", "demo"], sudo=True, check=False)

    def test_stop_vm_domain_forces_destroy_on_timeout(self):
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "current_domain_state", return_value="running"
        ), patch.object(
            cli, "run"
        ) as run_mock, patch.object(
            cli.time, "monotonic", side_effect=[0, 70]
        ):
            result = cli.stop_vm_domain("demo", timeout_seconds=5)
        
        self.assertTrue(result)
        self.assertEqual(run_mock.call_args_list, [
            call(["virsh", "shutdown", "demo"], sudo=True, check=False),
            call(["virsh", "destroy", "demo"], sudo=True, check=False)
        ])

    def test_stop_vm_domain_skips_non_running_vm(self):
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "current_domain_state", return_value="shut off"
        ), patch.object(
            cli, "run"
        ) as run_mock:
            result = cli.stop_vm_domain("demo")
        
        self.assertFalse(result)
        run_mock.assert_not_called()

    def test_stop_vm_domain_raises_for_missing_vm(self):
        with patch.object(cli, "vm_exists", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "VM not found: demo"):
                cli.stop_vm_domain("demo")


class SnapshotCreateTests(unittest.TestCase):
    def _setup_snapshot_test_fixtures(self, tmpdir_path):
        """Setup test fixtures for snapshot tests."""
        config_path = tmpdir_path / "configs" / "demo.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("vm:\n  name: demo\n", encoding="utf-8")
        
        state_path = tmpdir_path / "state" / "demo.yaml"
        state_path.parent.mkdir(parents=True)
        state_path.write_text("vm_name: demo\n", encoding="utf-8")
        
        vm_data_dir = tmpdir_path / "vm-data" / "demo"
        vm_data_dir.mkdir(parents=True)
        (vm_data_dir / "user-data").write_text("cloud-init", encoding="utf-8")
        
        admin_key = tmpdir_path / "keys" / "demo_admin_ed25519"
        admin_key.parent.mkdir(parents=True)
        admin_key.write_text("private", encoding="utf-8")
        (tmpdir_path / "keys" / "demo_admin_ed25519.pub").write_text("public", encoding="utf-8")
        
        disk_path = tmpdir_path / "images" / "demo.qcow2"
        disk_path.parent.mkdir(parents=True)
        disk_path.write_text("disk", encoding="utf-8")
        
        seed_path = tmpdir_path / "images" / "demo-seed.iso"
        seed_path.write_text("seed", encoding="utf-8")
        
        snapshot_path = tmpdir_path / "snapshots" / "snap-abc123" / "demo"
        
        state = {
            "config_path": str(config_path),
            "vm_data_dir": str(vm_data_dir),
            "admin_private_key": str(admin_key),
        }
        
        return {
            "config_path": config_path,
            "state_path": state_path,
            "vm_data_dir": vm_data_dir,
            "disk_path": disk_path,
            "seed_path": seed_path,
            "snapshot_path": snapshot_path,
            "state": state,
        }

    def _setup_snapshot_mocks(self, stack, fixtures):
        """Setup mocks for snapshot tests."""
        stack.enter_context(patch.object(cli, "require_tools"))
        stack.enter_context(patch.object(cli, "load_vm_state", return_value=fixtures["state"]))
        stack.enter_context(patch.object(cli, "resolve_config_path", return_value=fixtures["config_path"]))
        stack.enter_context(patch.object(cli, "load_config", return_value={"vm": {"name": "demo"}}))
        stack.enter_context(patch.object(cli, "load_global_config", return_value={}))
        stack.enter_context(patch.object(cli, "current_snapshot_id", return_value="snap-abc123"))
        stack.enter_context(patch.object(cli, "snapshot_path_for_vm", return_value=fixtures["snapshot_path"]))
        stack.enter_context(patch.object(cli, "vm_disk_path", return_value=fixtures["disk_path"]))
        stack.enter_context(patch.object(cli, "seed_iso_path", return_value=fixtures["seed_path"]))
        stack.enter_context(patch.object(cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()))
        stop_mock = stack.enter_context(patch.object(cli, "stop_vm_domain", return_value=True))
        stack.enter_context(patch.object(cli, "vm_exists", return_value=True))
        start_mock = stack.enter_context(patch.object(cli, "start_vm_domain"))
        copy_qcow2_mock = stack.enter_context(patch.object(cli, "copy_qcow2_image"))
        copy_artifact_mock = stack.enter_context(patch.object(cli, "copy_image_artifact"))
        copy_file_mock = stack.enter_context(patch.object(cli, "copy_local_file"))
        copy_tree_mock = stack.enter_context(patch.object(cli, "copy_local_tree"))
        stack.enter_context(patch.object(cli, "state_file_for_vm", return_value=fixtures["state_path"]))
        stack.enter_context(patch.object(cli, "vm_data_dir_for_config", return_value=fixtures["vm_data_dir"]))
        stack.enter_context(patch.object(cli, "resolved_config_assets", return_value={}))
        stack.enter_context(patch.object(cli, "chown_path_to_current_user"))
        
        return {
            "stop_mock": stop_mock,
            "start_mock": start_mock,
            "copy_qcow2_mock": copy_qcow2_mock,
            "copy_artifact_mock": copy_artifact_mock,
            "copy_file_mock": copy_file_mock,
            "copy_tree_mock": copy_tree_mock,
        }

    def test_snapshot_create_copies_all_vm_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir, contextlib.ExitStack() as stack:
            fixtures = self._setup_snapshot_test_fixtures(Path(tmpdir))
            mocks = self._setup_snapshot_mocks(stack, fixtures)
            
            cli.snapshot_create("demo")
            
            mocks["stop_mock"].assert_called_once_with("demo")
            mocks["start_mock"].assert_called_once_with("demo")
            mocks["copy_qcow2_mock"].assert_called_once()
            self.assertTrue(mocks["copy_artifact_mock"].called)
            self.assertTrue(mocks["copy_file_mock"].called)
            mocks["copy_tree_mock"].assert_called_once()

    def test_snapshot_create_cleans_up_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir, contextlib.ExitStack() as stack:
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "configs" / "demo.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("vm:\n  name: demo\n", encoding="utf-8")
            
            disk_path = tmpdir_path / "images" / "demo.qcow2"
            disk_path.parent.mkdir(parents=True)
            disk_path.write_text("disk", encoding="utf-8")
            
            seed_path = tmpdir_path / "images" / "demo-seed.iso"
            seed_path.write_text("seed", encoding="utf-8")
            
            snapshot_path = tmpdir_path / "snapshots" / "snap-abc123" / "demo"
            
            state = {"config_path": str(config_path)}
            
            stack.enter_context(patch.object(cli, "require_tools"))
            stack.enter_context(patch.object(cli, "load_vm_state", return_value=state))
            stack.enter_context(patch.object(cli, "resolve_config_path", return_value=config_path))
            stack.enter_context(patch.object(cli, "load_config", return_value={"vm": {"name": "demo"}}))
            stack.enter_context(patch.object(cli, "load_global_config", return_value={}))
            stack.enter_context(patch.object(cli, "current_snapshot_id", return_value="snap-abc123"))
            stack.enter_context(patch.object(cli, "snapshot_path_for_vm", return_value=snapshot_path))
            stack.enter_context(patch.object(cli, "vm_disk_path", return_value=disk_path))
            stack.enter_context(patch.object(cli, "seed_iso_path", return_value=seed_path))
            stack.enter_context(patch.object(cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(cli, "stop_vm_domain", return_value=False))
            stack.enter_context(patch.object(cli, "vm_exists", return_value=True))
            stack.enter_context(patch.object(cli, "copy_qcow2_image", side_effect=RuntimeError("copy failed")))
            stack.enter_context(patch.object(cli, "state_file_for_vm", return_value=Path("/nonexistent")))
            stack.enter_context(patch.object(cli, "vm_data_dir_for_config", return_value=Path("/nonexistent")))
            stack.enter_context(patch.object(cli, "resolved_config_assets", return_value={}))
            
            with self.assertRaisesRegex(RuntimeError, "copy failed"):
                cli.snapshot_create("demo")
            
            self.assertFalse(snapshot_path.exists())

    def test_snapshot_create_raises_for_missing_config_path(self):
        with patch.object(cli, "require_tools"), patch.object(
            cli, "load_vm_state", return_value={}
        ):
            with self.assertRaisesRegex(FileNotFoundError, "No saved config path"):
                cli.snapshot_create("demo")

    def test_snapshot_create_raises_for_missing_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_path = tmpdir_path / "configs" / "demo.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("vm:\n  name: demo\n", encoding="utf-8")
            
            missing_disk = tmpdir_path / "images" / "demo.qcow2"
            
            with patch.object(cli, "require_tools"), patch.object(
                cli, "load_vm_state", return_value={"config_path": str(config_path)}
            ), patch.object(
                cli, "resolve_config_path", return_value=config_path
            ), patch.object(
                cli, "load_config", return_value={"vm": {"name": "demo"}}
            ), patch.object(
                cli, "load_global_config", return_value={}
            ), patch.object(
                cli, "current_snapshot_id", return_value="snap-abc123"
            ), patch.object(
                cli, "vm_disk_path", return_value=missing_disk
            ):
                with self.assertRaisesRegex(FileNotFoundError, "VM disk was not found"):
                    cli.snapshot_create("demo")


class StartVmDomainTests(unittest.TestCase):
    def test_start_vm_domain_starts_stopped_vm(self):
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "current_domain_state", return_value="shut off"
        ), patch.object(
            cli, "run"
        ) as run_mock:
            result = cli.start_vm_domain("demo")
        
        self.assertTrue(result)
        run_mock.assert_called_once_with(["virsh", "start", "demo"], sudo=True)

    def test_start_vm_domain_skips_running_vm(self):
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "current_domain_state", return_value="running"
        ), patch.object(
            cli, "run"
        ) as run_mock:
            result = cli.start_vm_domain("demo")
        
        self.assertFalse(result)
        run_mock.assert_not_called()

    def test_start_vm_domain_raises_for_missing_vm(self):
        with patch.object(cli, "vm_exists", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "VM not found: demo"):
                cli.start_vm_domain("demo")


class StartCommandTests(unittest.TestCase):
    def test_start_command_with_network_group(self):
        state = {"network": {"network_group_id": "ng-demo"}}
        
        with patch.object(cli, "require_tools"), patch.object(
            cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()
        ), patch.object(
            cli, "load_vm_state", return_value=state
        ), patch.object(
            cli, "reconcile_networking"
        ) as reconcile_mock, patch.object(
            cli, "start_vm_domain", return_value=True
        ) as start_mock:
            cli.start("demo")
        
        reconcile_mock.assert_called_once()
        start_mock.assert_called_once_with("demo")

    def test_start_command_with_nat_network(self):
        state = {"network": {"mode": "nat-custom"}}
        
        with patch.object(cli, "require_tools"), patch.object(
            cli, "host_lifecycle_lock", return_value=contextlib.nullcontext()
        ), patch.object(
            cli, "load_vm_state", return_value=state
        ), patch.object(
            cli, "is_libvirt_nat_network", return_value=True
        ), patch.object(
            cli, "reconcile_networking"
        ) as reconcile_mock, patch.object(
            cli, "start_vm_domain", return_value=False
        ):
            cli.start("demo")
        
        reconcile_mock.assert_called_once()


class HelperFunctionTests(unittest.TestCase):
    def test_current_domain_state_returns_state(self):
        with patch.object(cli, "capture_or_none", return_value="running"):
            state = cli.current_domain_state("demo")
        
        self.assertEqual(state, "running")

    def test_merged_vm_network_merges_state_and_discovery(self):
        state = {"network": {"name": "demo-net", "vm_ip": "192.168.1.50"}}
        
        with patch.object(
            cli, "discover_vm_network", return_value={"vm_ip": "192.168.1.55", "gateway": "192.168.1.1"}
        ), patch.object(
            cli, "is_libvirt_nat_network", return_value=True
        ), patch.object(
            cli, "default_nat_bridge_name", return_value="virbr-demo"
        ):
            network = cli.merged_vm_network("demo", state)
        
        self.assertEqual(network["name"], "demo-net")
        self.assertEqual(network["vm_ip"], "192.168.1.55")
        self.assertEqual(network["gateway"], "192.168.1.1")
        self.assertEqual(network["bridge_name"], "virbr-demo")

    def test_is_libvirt_nat_network_detects_nat_mode(self):
        self.assertTrue(cli.is_libvirt_nat_network({"mode": "nat-auto"}))
        self.assertTrue(cli.is_libvirt_nat_network({"mode": "nat-custom"}))


class RuntimeCleanupTests(unittest.TestCase):
    def test_cleanup_vm_runtime_definition_removes_domain(self):
        network = {"network_group_id": "ng-demo"}
        
        with patch.object(cli, "vm_exists", return_value=True), patch.object(
            cli, "run"
        ) as run_mock, patch.object(
            cli, "cleanup_vm_storage"
        ) as cleanup_storage_mock:
            cli.cleanup_vm_runtime_definition("demo", network, [], remove_storage=True)
        
        cleanup_storage_mock.assert_called_once_with("demo")
        self.assertEqual(run_mock.call_args_list, [
            call(["virsh", "destroy", "demo"], sudo=True, check=False),
            call(["virsh", "undefine", "demo", "--remove-all-storage"], sudo=True, check=False)
        ])

    def test_cleanup_vm_runtime_definition_removes_nat_network(self):
        network = {"mode": "nat-custom", "name": "demo-net", "bridge_name": "virbr-demo"}
        
        with patch.object(cli, "vm_exists", return_value=False), patch.object(
            cli, "is_libvirt_nat_network", return_value=True
        ), patch.object(
            cli, "run"
        ) as run_mock, patch.object(
            cli, "default_nat_bridge_name", return_value="virbr-89e495e7"
        ), patch.object(
            cli, "legacy_nat_bridge_name", return_value="virbr-demo-legacy"
        ), patch.object(
            cli, "bridge_interface_exists", side_effect=[False, False, True]
        ), patch.object(
            cli, "cleanup_bridge_interface"
        ) as cleanup_bridge_mock:
            cli.cleanup_vm_runtime_definition("demo", network, [], remove_storage=False)
        
        self.assertEqual(run_mock.call_args_list, [
            call(["virsh", "net-destroy", "demo-net"], sudo=True, check=False),
            call(["virsh", "net-undefine", "demo-net"], sudo=True, check=False)
        ])
        # Set iteration order is unpredictable - just check it was called once with one of the bridge names
        cleanup_bridge_mock.assert_called_once()
        self.assertIn(cleanup_bridge_mock.call_args[0][0], ["virbr-demo", "virbr-89e495e7", "virbr-demo-legacy"])


class SnapshotHelperTests(unittest.TestCase):
    def test_snapshot_metadata_path_constructs_path(self):
        snapshot_path = Path("/snapshots/demo/snap-1")
        metadata_path = cli.snapshot_metadata_path(snapshot_path)
        
        self.assertEqual(metadata_path, snapshot_path / "metadata.yaml")

    def test_load_snapshot_metadata_returns_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "snap-1"
            snapshot_path.mkdir()
            metadata_file = snapshot_path / "metadata.yaml"
            metadata_file.write_text("snapshot_id: snap-1\ncreated_at: '2024-01-01T10:00:00Z'\n", encoding="utf-8")
            
            with patch.object(cli, "snapshot_path_for_vm", return_value=snapshot_path):
                metadata = cli.load_snapshot_metadata("demo", "snap-1")
            
            self.assertEqual(metadata["snapshot_id"], "snap-1")
            self.assertEqual(metadata["created_at"], "2024-01-01T10:00:00Z")

    def test_load_snapshot_metadata_raises_for_missing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "snap-missing"
            
            with patch.object(cli, "snapshot_path_for_vm", return_value=snapshot_path):
                with self.assertRaisesRegex(FileNotFoundError, "Snapshot not found"):
                    cli.load_snapshot_metadata("demo", "snap-missing")

    def test_list_snapshots_returns_empty_for_missing_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "missing"
            
            with patch.object(cli, "snapshot_root_for_vm", return_value=root):
                snapshots = cli.list_snapshots("demo")
            
            self.assertEqual(snapshots, [])

    def test_list_snapshots_returns_sorted_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            
            snap1 = root / "snap-1"
            snap1.mkdir()
            (snap1 / "metadata.yaml").write_text(
                "snapshot_id: snap-1\ncreated_at: 2024-01-01T10:00:00Z\n", encoding="utf-8"
            )
            
            snap2 = root / "snap-2"
            snap2.mkdir()
            (snap2 / "metadata.yaml").write_text(
                "snapshot_id: snap-2\ncreated_at: 2024-01-02T10:00:00Z\n", encoding="utf-8"
            )
            
            with patch.object(cli, "snapshot_root_for_vm", return_value=root):
                snapshots = cli.list_snapshots("demo")
            
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(snapshots[0]["snapshot_id"], "snap-2")  # Most recent first
            self.assertEqual(snapshots[1]["snapshot_id"], "snap-1")


class BuildNetworkConfigManagedTests(unittest.TestCase):
    def test_build_managed_network_from_network_group(self):
        net_cfg = {
            "network_group_id": "ng-demo",
            "group_name": "demo-group",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb-demo",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
            "vm_ip": "10.80.0.2",
            "mac": "52:54:00:11:22:33",
        }
        
        with patch.object(cli, "normalize_network_profile", return_value="isolated_nat"):
            network = cli.build_network_config("demo", net_cfg)
        
        self.assertEqual(network["network_group_id"], "ng-demo")
        self.assertEqual(network["profile"], "isolated_nat")
        self.assertEqual(network["mode"], "isolated_nat")
        self.assertEqual(network["bridge_name"], "hvpb-demo")

    def test_build_bridged_network_sets_defaults(self):
        net_cfg = {"mode": "bridge"}
        
        network = cli.build_network_config("demo", net_cfg)
        
        self.assertEqual(network["mode"], "bridge")
        self.assertEqual(network["bridge_name"], "br0")
        self.assertEqual(network["vm_ip"], "dhcp-from-router")
        self.assertEqual(network["cidr"], "main-lan")

    def test_build_nat_auto_network(self):
        net_cfg = {"mode": "nat-auto"}
        
        subnet_info = {
            "prefix": "192.168.240",
            "cidr": "192.168.240.0/24",
            "gateway": "192.168.240.1",
            "vm_ip": "192.168.240.50",
            "dhcp_start": "192.168.240.50",
            "dhcp_end": "192.168.240.99",
        }
        
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"), patch.object(
            cli, "pick_free_subnet", return_value=subnet_info
        ), patch.object(
            cli, "default_nat_bridge_name", return_value="virbr-demo"
        ):
            network = cli.build_network_config("demo", net_cfg)
        
        self.assertEqual(network["mode"], "nat-auto")
        self.assertEqual(network["mac"], "52:54:00:aa:bb:cc")
        self.assertEqual(network["prefix"], "192.168.240")
        self.assertEqual(network["gateway"], "192.168.240.1")

    def test_build_nat_custom_network_from_subnet_prefix(self):
        net_cfg = {"mode": "nat-custom", "subnet_prefix": "192.168.100"}
        
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"), patch.object(
            cli, "default_nat_bridge_name", return_value="virbr-demo"
        ):
            network = cli.build_network_config("demo", net_cfg)
        
        self.assertEqual(network["mode"], "nat-custom")
        self.assertEqual(network["prefix"], "192.168.100")
        self.assertEqual(network["gateway"], "192.168.100.1")
        self.assertEqual(network["vm_ip"], "192.168.100.50")
        self.assertEqual(network["dhcp_start"], "192.168.100.50")
        self.assertEqual(network["dhcp_end"], "192.168.100.99")

    def test_build_nat_custom_network_raises_for_invalid_prefix(self):
        net_cfg = {"mode": "nat-custom", "subnet_prefix": "invalid"}
        
        with self.assertRaisesRegex(ValueError, "subnet_prefix must be a valid IPv4 prefix"):
            cli.build_network_config("demo", net_cfg)

    def test_build_nat_custom_network_raises_for_missing_fields(self):
        net_cfg = {"mode": "nat-custom"}  # No subnet_prefix or explicit fields
        
        with self.assertRaisesRegex(ValueError, "Missing nat-custom network fields"):
            cli.build_network_config("demo", net_cfg)

    def test_build_nat_custom_network_from_explicit_fields(self):
        net_cfg = {
            "mode": "nat-custom",
            "cidr": "192.168.100.0/24",
            "gateway": "192.168.100.1",
            "vm_ip": "192.168.100.50",
            "dhcp_start": "192.168.100.50",
            "dhcp_end": "192.168.100.99",
        }
        
        with patch.object(cli, "random_mac", return_value="52:54:00:aa:bb:cc"), patch.object(
            cli, "default_nat_bridge_name", return_value="virbr-demo"
        ):
            network = cli.build_network_config("demo", net_cfg)
        
        self.assertEqual(network["mode"], "nat-custom")
        self.assertEqual(network["cidr"], "192.168.100.0/24")
        self.assertEqual(network["gateway"], "192.168.100.1")

    def test_build_network_raises_for_invalid_mode(self):
        net_cfg = {"mode": "invalid-mode"}
        
        with self.assertRaisesRegex(ValueError, "must be nat-auto, nat-custom, or bridge"):
            cli.build_network_config("demo", net_cfg)

    def test_build_network_raises_for_missing_managed_fields(self):
        net_cfg = {
            "network_group_id": "ng-demo",
            "libvirt_network_name": "hvp-ng-demo",
            # Missing required fields
        }
        
        with patch.object(cli, "normalize_network_profile", return_value="isolated_nat"):
            with self.assertRaisesRegex(ValueError, "Missing managed network-group fields"):
                cli.build_network_config("demo", net_cfg)


class DestroyReconciliationTests(unittest.TestCase):
    def test_destroy_removes_vm(self):
        state = {
            "vm_name": "demo",
            "network": {"mode": "nat-auto", "prefix": "192.168.240"},
            "ports": [],
        }
        
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(cli, "host_lifecycle_lock"))
            stack.enter_context(patch.object(cli, "load_vm_state", return_value=state))
            stack.enter_context(patch.object(cli, "merged_vm_network", return_value=state["network"]))
            stack.enter_context(patch.object(cli, "is_libvirt_nat_network", return_value=True))
            cleanup_mock = stack.enter_context(patch.object(cli, "cleanup_vm_runtime_definition"))
            artifacts_mock = stack.enter_context(patch.object(cli, "cleanup_local_vm_artifacts"))
            reconcile_mock = stack.enter_context(patch.object(cli, "reconcile_networking"))
            
            cli.destroy("demo")
            
            cleanup_mock.assert_called_once_with("demo", state["network"], [], remove_storage=True)
            artifacts_mock.assert_called_once()
            reconcile_mock.assert_called_once_with(policy_only=True)

    def test_destroy_reconciles_for_network_group(self):
        state = {
            "vm_name": "demo",
            "network": {"mode": "isolated_nat", "network_group_id": "ng-demo"},
            "ports": [],
        }
        
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(cli, "host_lifecycle_lock"))
            stack.enter_context(patch.object(cli, "load_vm_state", return_value=state))
            stack.enter_context(patch.object(cli, "merged_vm_network", return_value=state["network"]))
            stack.enter_context(patch.object(cli, "validate_networking_changes"))
            stack.enter_context(patch.object(cli, "cleanup_vm_runtime_definition"))
            stack.enter_context(patch.object(cli, "cleanup_local_vm_artifacts"))
            reconcile_mock = stack.enter_context(patch.object(cli, "reconcile_networking"))
            stack.enter_context(patch.object(cli, "is_libvirt_nat_network", return_value=False))
            stack.enter_context(patch.object(cli, "planned_managed_vm_records", return_value=[]))
            
            cli.destroy("demo")
            
            reconcile_mock.assert_called_once_with()  # No policy_only for network groups


class ValidateNatCustomNetworkTests(unittest.TestCase):
    def test_validates_invalid_cidr(self):
        network = {"cidr": "invalid"}
        
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 network"):
            cli._validate_nat_custom_network(network)

    def test_validates_non_24_prefix(self):
        network = {"cidr": "192.0.0.0/16"}
        
        with self.assertRaisesRegex(ValueError, "/24 network"):
            cli._validate_nat_custom_network(network)

    def test_validates_invalid_gateway(self):
        network = {
            "cidr": "192.168.1.0/24",
            "gateway": "invalid",
            "vm_ip": "192.168.1.50",
            "dhcp_start": "192.168.1.50",
            "dhcp_end": "192.168.1.99",
        }
        
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 address"):
            cli._validate_nat_custom_network(network)

    def test_validates_gateway_outside_cidr(self):
        network = {
            "cidr": "192.168.1.0/24",
            "gateway": "192.168.2.1",
            "vm_ip": "192.168.1.50",
            "dhcp_start": "192.168.1.50",
            "dhcp_end": "192.168.1.99",
        }
        
        with self.assertRaisesRegex(ValueError, "network.gateway must be inside network"):
            cli._validate_nat_custom_network(network)

    def test_validates_dhcp_start_greater_than_end(self):
        network = {
            "cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
            "vm_ip": "192.168.1.50",
            "dhcp_start": "192.168.1.99",
            "dhcp_end": "192.168.1.50",
        }
        
        with self.assertRaisesRegex(ValueError, "dhcp_start must not be greater than"):
            cli._validate_nat_custom_network(network)
