import unittest
from unittest.mock import call, patch

from homelab_vm_provisioner import firewall
from homelab_vm_provisioner.constants import BLOCKED_PRIVATE_RANGES


class RuleSpecTests(unittest.TestCase):
    def test_builds_firewalld_forward_port_spec(self):
        self.assertEqual(
            firewall.forward_port_spec(
                {"host": 2222, "guest": 22, "proto": "tcp"},
                "192.168.240.50",
            ),
            "port=2222:proto=tcp:toaddr=192.168.240.50:toport=22",
        )

    def test_builds_firewalld_direct_forward_rule_spec(self):
        self.assertEqual(
            firewall.direct_forward_rule_args(
                {"host": 2222, "guest": 22, "proto": "tcp"},
                "192.168.240.50",
            ),
            [
                "ipv4",
                "filter",
                "FORWARD",
                "-1000",
                "-p",
                "tcp",
                "-d",
                "192.168.240.50",
                "--dport",
                "22",
                "-j",
                "ACCEPT",
            ],
        )

    def test_builds_nft_forward_rule_spec(self):
        self.assertEqual(
            firewall.nft_forward_rule_args(
                {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI", "handle": "18"},
                "virbr-demo",
                {"host": 2222, "guest": 22, "proto": "tcp"},
                "192.168.240.50",
            ),
            [
                "ip",
                "filter",
                "LIBVIRT_FWI",
                "handle",
                "18",
                "oifname",
                "virbr-demo",
                "ip",
                "daddr",
                "192.168.240.50",
                "tcp",
                "dport",
                "22",
                "accept",
            ],
        )

    def test_direct_forward_ports_deduplicate_configured_ports(self):
        self.assertEqual(
            firewall.direct_forward_ports(
                [
                    {"host": 2222, "guest": 22, "proto": "tcp"},
                    {"host": 2022, "guest": 22, "proto": "tcp"},
                    {"host": 8080, "guest": 80, "proto": "tcp"},
                    {"host": 51153, "guest": 25565, "proto": "udp"},
                ]
            ),
            [
                {"guest": "22", "proto": "tcp"},
                {"guest": "80", "proto": "tcp"},
                {"guest": "25565", "proto": "udp"},
            ],
        )


class BridgeAndNftLookupTests(unittest.TestCase):
    def test_nft_chain_location_finds_chain_table_and_family(self):
        self.assertEqual(
            firewall.nft_chain_location(
                "LIBVIRT_FWI",
                ruleset_text=(
                    "table inet firewalld {\n"
                    "    chain input {\n"
                    "    }\n"
                    "}\n"
                    "table ip filter {\n"
                    "    chain LIBVIRT_FWI {\n"
                    "    }\n"
                    "}"
                ),
            ),
            {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
        )

    def test_nft_chain_location_returns_none_when_chain_is_missing(self):
        self.assertIsNone(
            firewall.nft_chain_location(
                "LIBVIRT_FWI",
                ruleset_text="table ip filter {\n}",
            )
        )

    def test_bridge_interface_for_vm_ip_extracts_dev_name(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value="192.168.240.50 dev virbr-demo src 192.168.240.1 uid 0",
        ):
            self.assertEqual(firewall.bridge_interface_for_vm_ip("192.168.240.50"), "virbr-demo")

    def test_bridge_interface_for_vm_ip_returns_none_when_missing(self):
        with patch.object(firewall, "capture_or_none", return_value=None):
            self.assertIsNone(firewall.bridge_interface_for_vm_ip("192.168.240.50"))

    def test_wait_for_bridge_interface_returns_first_match(self):
        with patch.object(
            firewall,
            "bridge_interface_for_vm_ip",
            side_effect=[None, "virbr-demo"],
        ), patch.object(firewall.time, "sleep"):
            self.assertEqual(firewall.wait_for_bridge_interface("192.168.240.50"), "virbr-demo")

    def test_wait_for_bridge_interface_returns_none_when_missing(self):
        with patch.object(firewall, "bridge_interface_for_vm_ip", return_value=None), patch.object(
            firewall.time, "sleep"
        ):
            self.assertIsNone(firewall.wait_for_bridge_interface("192.168.240.50", attempts=2))

    def test_nft_chain_exists_checks_capture(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value="table ip filter {\n    chain LIBVIRT_FWI {\n    }\n}",
        ):
            self.assertTrue(firewall.nft_chain_exists("LIBVIRT_FWI"))

        with patch.object(firewall, "capture_or_none", return_value=None):
            self.assertFalse(firewall.nft_chain_exists("LIBVIRT_FWI"))

    def test_wait_for_nft_chain_returns_chain_location_when_chain_appears(self):
        with patch.object(
            firewall,
            "nft_chain_location",
            side_effect=[None, {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"}],
        ), patch.object(
            firewall.time, "sleep"
        ):
            self.assertEqual(
                firewall.wait_for_nft_chain("LIBVIRT_FWI"),
                {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
            )

    def test_wait_for_nft_chain_returns_none_when_chain_never_appears(self):
        with patch.object(firewall, "nft_chain_location", return_value=None), patch.object(
            firewall.time, "sleep"
        ):
            self.assertIsNone(firewall.wait_for_nft_chain("LIBVIRT_FWI", attempts=2))

    def test_nft_rule_handle_extracts_handle_value(self):
        self.assertEqual(
            firewall.nft_rule_handle(
                'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 22 accept # handle 7'
            ),
            "7",
        )
        self.assertIsNone(firewall.nft_rule_handle('oifname "virbr-demo" reject'))

    def test_list_nft_chain_rules_returns_only_handle_lines(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value=(
                "table ip filter {\n"
                "\tchain LIBVIRT_FWI {\n"
                '        oifname "virbr-demo" reject # handle 18\n'
                '        oifname "virbr-demo" ip daddr 192.168.240.50 tcp '
                'dport 22 accept # handle 7\n'
                "\t}\n"
                "}"
            ),
        ):
            self.assertEqual(
                firewall.list_nft_chain_rules(
                    {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"}
                ),
                [
                    'oifname "virbr-demo" reject # handle 18',
                    'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 22 accept # handle 7',
                ],
            )

    def test_find_nft_bridge_reject_handle_filters_by_bridge(self):
        with patch.object(
            firewall,
            "list_nft_chain_rules",
            return_value=[
                'oifname "virbr-other" reject # handle 11',
                'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 22 accept # handle 12',
                'oifname "virbr-demo" reject # handle 18',
            ],
        ):
            self.assertEqual(
                firewall.find_nft_bridge_reject_handle(
                    {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
                    "virbr-demo",
                ),
                "18",
            )

    def test_wait_for_nft_bridge_reject_handle_returns_handle_when_found(self):
        with patch.object(
            firewall,
            "find_nft_bridge_reject_handle",
            side_effect=[None, "18"],
        ), patch.object(firewall.time, "sleep"):
            self.assertEqual(
                firewall.wait_for_nft_bridge_reject_handle(
                    {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
                    "virbr-demo",
                ),
                "18",
            )

    def test_wait_for_nft_bridge_reject_handle_returns_none_when_missing(self):
        with patch.object(
            firewall,
            "find_nft_bridge_reject_handle",
            return_value=None,
        ), patch.object(
            firewall.time, "sleep"
        ):
            self.assertIsNone(
                firewall.wait_for_nft_bridge_reject_handle(
                    {"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
                    "virbr-demo",
                    attempts=2,
                )
            )

    def test_insert_nft_forward_rule_uses_libvirt_chain(self):
        with patch.object(
            firewall,
            "wait_for_nft_chain",
            return_value={"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
        ), patch.object(
            firewall,
            "wait_for_nft_bridge_reject_handle",
            return_value="18",
        ), patch.object(
            firewall, "run"
        ) as run_mock:
            self.assertTrue(
                firewall.insert_nft_forward_rule(
                    "virbr-demo",
                    {"host": 2222, "guest": 22, "proto": "tcp"},
                    "192.168.240.50",
                )
            )

        run_mock.assert_called_once_with(
            [
                "nft",
                "insert",
                "rule",
                "ip",
                "filter",
                "LIBVIRT_FWI",
                "handle",
                "18",
                "oifname",
                "virbr-demo",
                "ip",
                "daddr",
                "192.168.240.50",
                "tcp",
                "dport",
                "22",
                "accept",
            ],
            sudo=True,
            check=False,
        )

    def test_insert_nft_forward_rule_skips_when_chain_is_missing(self):
        with patch.object(firewall, "wait_for_nft_chain", return_value=None), patch.object(
            firewall, "run"
        ) as run_mock:
            self.assertFalse(
                firewall.insert_nft_forward_rule(
                    "virbr-demo",
                    {"host": 2222, "guest": 22, "proto": "tcp"},
                    "192.168.240.50",
                )
            )

        run_mock.assert_not_called()

    def test_insert_nft_forward_rule_skips_when_reject_handle_is_missing(self):
        with patch.object(
            firewall,
            "wait_for_nft_chain",
            return_value={"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
        ), patch.object(
            firewall,
            "wait_for_nft_bridge_reject_handle",
            return_value=None,
        ), patch.object(firewall, "run") as run_mock:
            self.assertFalse(
                firewall.insert_nft_forward_rule(
                    "virbr-demo",
                    {"host": 2222, "guest": 22, "proto": "tcp"},
                    "192.168.240.50",
                )
            )

        run_mock.assert_not_called()

    def test_list_nft_forward_rules_returns_only_handle_lines(self):
        with patch.object(
            firewall,
            "nft_chain_location",
            return_value={"family": "ip", "table": "filter", "chain": "LIBVIRT_FWI"},
        ), patch.object(
            firewall,
            "capture_or_none",
            return_value=(
                "table ip filter {\n"
                "\tchain LIBVIRT_FWI {\n"
                '        oifname "virbr-demo" reject # handle 18\n'
                '        oifname "virbr-demo" ip daddr 192.168.240.50 tcp '
                'dport 22 accept # handle 7\n'
                '        oifname "virbr-demo" ip daddr 192.168.240.50 tcp '
                'dport 80 accept # handle 8\n'
                "\t}\n"
                "}"
            ),
        ):
            self.assertEqual(
                firewall.list_nft_forward_rules(),
                [
                    'oifname "virbr-demo" reject # handle 18',
                    'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 22 accept # handle 7',
                    'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 80 accept # handle 8',
                ],
            )

    def test_find_nft_forward_rule_handles_for_vm_filters_by_destination(self):
        with patch.object(
            firewall,
            "list_nft_forward_rules",
            return_value=[
                'oifname "virbr-demo" ip daddr 192.168.240.50 tcp dport 22 accept # handle 7',
                'oifname "virbr-demo" ip daddr 192.168.240.50 udp dport 25565 accept # handle 8',
                'oifname "virbr-demo" ip daddr 192.168.240.51 tcp dport 80 accept # handle 9',
            ],
        ):
            self.assertEqual(
                firewall.find_nft_forward_rule_handles_for_vm("192.168.240.50"),
                ["7", "8"],
            )


class ZoneLookupTests(unittest.TestCase):
    def test_firewalld_zone_exists_checks_permanent_zones(self):
        with patch.object(firewall, "capture_or_none", return_value="public demo-zone"):
            self.assertTrue(firewall.firewalld_zone_exists("demo-zone"))
            self.assertFalse(firewall.firewalld_zone_exists("missing-zone"))

    def test_firewalld_zone_for_cidr_returns_matching_zone(self):
        with patch.object(
            firewall,
            "capture_or_none",
            side_effect=["public demo-zone", "10.0.0.0/8", "192.168.240.0/24"],
        ):
            self.assertEqual(
                firewall.firewalld_zone_for_cidr("192.168.240.0/24", preferred_zone="public"),
                "demo-zone",
            )

    def test_firewalld_zone_for_cidr_returns_none_when_zones_cannot_be_listed(self):
        with patch.object(firewall, "capture_or_none", return_value=None):
            self.assertIsNone(firewall.firewalld_zone_for_cidr("192.168.240.0/24"))

    def test_firewalld_zone_for_cidr_returns_none_when_no_zone_matches(self):
        with patch.object(
            firewall,
            "capture_or_none",
            side_effect=["public demo-zone", "10.0.0.0/8", "172.16.0.0/12"],
        ):
            self.assertIsNone(firewall.firewalld_zone_for_cidr("192.168.240.0/24"))

    def test_list_zone_forward_ports_splits_output(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value=(
                "port=2222:proto=tcp:toaddr=1.2.3.4:toport=22 "
                "port=8080:proto=tcp:toaddr=1.2.3.4:toport=80"
            ),
        ):
            self.assertEqual(
                firewall.list_zone_forward_ports("demo-zone"),
                [
                    "port=2222:proto=tcp:toaddr=1.2.3.4:toport=22",
                    "port=8080:proto=tcp:toaddr=1.2.3.4:toport=80",
                ],
            )

    def test_list_zone_forward_ports_returns_empty_when_unset(self):
        with patch.object(firewall, "capture_or_none", return_value=None):
            self.assertEqual(firewall.list_zone_forward_ports(), [])

    def test_find_forward_port_rules_for_vm_scans_global_and_zone_rules(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value="public demo-zone",
        ), patch.object(
            firewall,
            "list_zone_forward_ports",
            side_effect=[
                ["port=2222:proto=tcp:toaddr=192.168.240.50:toport=22"],
                ["port=8080:proto=tcp:toaddr=192.168.240.50:toport=80"],
                ["port=9090:proto=tcp:toaddr=192.168.240.51:toport=90"],
            ],
        ):
            self.assertEqual(
                firewall.find_forward_port_rules_for_vm("192.168.240.50"),
                [
                    (None, "port=2222:proto=tcp:toaddr=192.168.240.50:toport=22"),
                    ("public", "port=8080:proto=tcp:toaddr=192.168.240.50:toport=80"),
                ],
            )

    def test_list_direct_rules_splits_output_lines(self):
        with patch.object(
            firewall,
            "capture_or_none",
            return_value=(
                "ipv4 filter FORWARD -1000 -p tcp -d 192.168.240.50 --dport 22 -j ACCEPT\n"
                "ipv4 filter FORWARD -1000 -p udp -d 192.168.240.50 --dport 25565 -j ACCEPT"
            ),
        ):
            self.assertEqual(
                firewall.list_direct_rules(),
                [
                    [
                        "ipv4",
                        "filter",
                        "FORWARD",
                        "-1000",
                        "-p",
                        "tcp",
                        "-d",
                        "192.168.240.50",
                        "--dport",
                        "22",
                        "-j",
                        "ACCEPT",
                    ],
                    [
                        "ipv4",
                        "filter",
                        "FORWARD",
                        "-1000",
                        "-p",
                        "udp",
                        "-d",
                        "192.168.240.50",
                        "--dport",
                        "25565",
                        "-j",
                        "ACCEPT",
                    ],
                ],
            )

    def test_find_direct_forward_rules_for_vm_filters_by_destination(self):
        with patch.object(
            firewall,
            "list_direct_rules",
            return_value=[
                [
                    "ipv4",
                    "filter",
                    "FORWARD",
                    "-1000",
                    "-p",
                    "tcp",
                    "-d",
                    "192.168.240.50",
                    "--dport",
                    "22",
                    "-j",
                    "ACCEPT",
                ],
                ["ipv4", "filter", "INPUT", "-1000", "-j", "ACCEPT"],
                [
                    "ipv4",
                    "filter",
                    "FORWARD",
                    "-1000",
                    "-p",
                    "tcp",
                    "-d",
                    "192.168.240.51",
                    "--dport",
                    "80",
                    "-j",
                    "ACCEPT",
                ],
            ],
        ):
            self.assertEqual(
                firewall.find_direct_forward_rules_for_vm("192.168.240.50"),
                [
                    [
                        "ipv4",
                        "filter",
                        "FORWARD",
                        "-1000",
                        "-p",
                        "tcp",
                        "-d",
                        "192.168.240.50",
                        "--dport",
                        "22",
                        "-j",
                        "ACCEPT",
                    ]
                ],
            )

    def test_firewalld_zone_is_empty_returns_false_on_any_data(self):
        with patch.object(firewall, "capture_or_none", side_effect=["", "interface0"]):
            self.assertFalse(firewall.firewalld_zone_is_empty("demo-zone"))

    def test_firewalld_zone_is_empty_returns_true_for_empty_results(self):
        with patch.object(firewall, "capture_or_none", return_value=""):
            self.assertTrue(firewall.firewalld_zone_is_empty("demo-zone"))


class ApplyFirewalldNatPolicyTests(unittest.TestCase):
    def test_applies_zone_rules_reload_and_nft_insert(self):
        with patch.object(firewall, "capture", return_value="public"), patch.object(
            firewall, "wait_for_bridge_interface", return_value="virbr-demo"
        ), patch.object(
            firewall,
            "insert_nft_forward_rule",
            return_value=True,
        ) as insert_mock, patch.object(firewall, "run") as run_mock:
            zone_created = firewall.apply_firewalld_nat_policy(
                {
                    "zone": "demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                "untrusted",
                [
                    {"host": 2222, "guest": 22, "proto": "tcp"},
                    {"host": 2022, "guest": 22, "proto": "tcp"},
                ],
            )

        self.assertTrue(zone_created)
        self.assertIn(
            call(["firewall-cmd", "--permanent", "--new-zone", "demo-zone"], sudo=True),
            run_mock.call_args_list,
        )
        self.assertIn(
            call(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    "demo-zone",
                    "--set-target",
                    "ACCEPT",
                ],
                sudo=True,
            ),
            run_mock.call_args_list,
        )
        self.assertIn(
            call(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--add-forward-port=port=2222:proto=tcp:toaddr=192.168.240.50:toport=22",
                ],
                sudo=True,
            ),
            run_mock.call_args_list,
        )
        self.assertIn(
            call(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--direct",
                    "--add-rule",
                    "ipv4",
                    "filter",
                    "FORWARD",
                    "-1000",
                    "-p",
                    "tcp",
                    "-d",
                    "192.168.240.50",
                    "--dport",
                    "22",
                    "-j",
                    "ACCEPT",
                ],
                sudo=True,
            ),
            run_mock.call_args_list,
        )
        self.assertEqual(
            insert_mock.call_args_list,
            [call("virbr-demo", {"guest": "22", "proto": "tcp"}, "192.168.240.50")],
        )
        self.assertIn(call(["firewall-cmd", "--reload"], sudo=True), run_mock.call_args_list)

        rich_rule_calls = [
            args
            for args in run_mock.call_args_list
            if "--add-rich-rule" in args.args[0]
        ]
        self.assertEqual(len(rich_rule_calls), len(BLOCKED_PRIVATE_RANGES))

    def test_trusted_vm_uses_existing_zone_without_rich_rules(self):
        with patch.object(firewall, "capture", return_value="demo-zone public"), patch.object(
            firewall, "wait_for_bridge_interface"
        ) as bridge_mock, patch.object(
            firewall,
            "insert_nft_forward_rule",
        ) as insert_mock, patch.object(firewall, "run") as run_mock:
            zone_created = firewall.apply_firewalld_nat_policy(
                {
                    "zone": "demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                "trusted",
                [],
            )

        self.assertFalse(zone_created)
        bridge_mock.assert_not_called()
        insert_mock.assert_not_called()
        self.assertEqual(
            run_mock.call_args_list,
            [
                call(
                    [
                        "firewall-cmd",
                        "--permanent",
                        "--zone",
                        "demo-zone",
                        "--set-target",
                        "ACCEPT",
                    ],
                    sudo=True,
                ),
                call(
                    [
                        "firewall-cmd",
                        "--permanent",
                        "--zone",
                        "demo-zone",
                        "--add-source",
                        "192.168.240.0/24",
                    ],
                    sudo=True,
                ),
                call(["firewall-cmd", "--reload"], sudo=True),
            ],
        )

    def test_skips_nft_insert_when_bridge_cannot_be_resolved(self):
        with patch.object(firewall, "capture", return_value="public"), patch.object(
            firewall, "wait_for_bridge_interface", return_value=None
        ), patch.object(firewall, "insert_nft_forward_rule") as insert_mock, patch.object(
            firewall, "run"
        ):
            firewall.apply_firewalld_nat_policy(
                {
                    "zone": "demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                "trusted",
                [{"host": 2222, "guest": 22, "proto": "tcp"}],
            )

        insert_mock.assert_not_called()


class RemoveRuleTests(unittest.TestCase):
    def test_remove_forward_port_rule_uses_zone_when_provided(self):
        with patch.object(firewall, "run") as run_mock:
            firewall.remove_forward_port_rule(
                "port=2222:proto=tcp:toaddr=1.2.3.4:toport=22",
                zone="demo-zone",
            )

        run_mock.assert_called_once_with(
            [
                "firewall-cmd",
                "--permanent",
                "--zone",
                "demo-zone",
                "--remove-forward-port=port=2222:proto=tcp:toaddr=1.2.3.4:toport=22",
            ],
            sudo=True,
            check=False,
        )

    def test_remove_direct_rule_uses_firewalld_direct_remove(self):
        with patch.object(firewall, "run") as run_mock:
            firewall.remove_direct_rule(
                [
                    "ipv4",
                    "filter",
                    "FORWARD",
                    "-1000",
                    "-p",
                    "tcp",
                    "-d",
                    "192.168.240.50",
                    "--dport",
                    "22",
                    "-j",
                    "ACCEPT",
                ]
            )

        run_mock.assert_called_once_with(
            [
                "firewall-cmd",
                "--permanent",
                "--direct",
                "--remove-rule",
                "ipv4",
                "filter",
                "FORWARD",
                "-1000",
                "-p",
                "tcp",
                "-d",
                "192.168.240.50",
                "--dport",
                "22",
                "-j",
                "ACCEPT",
            ],
            sudo=True,
            check=False,
        )

    def test_remove_nft_forward_rule_uses_nft_delete(self):
        with patch.object(
            firewall,
            "nft_chain_location",
            return_value={"family": "inet", "table": "firewalld", "chain": "LIBVIRT_FWI"},
        ), patch.object(firewall, "run") as run_mock:
            firewall.remove_nft_forward_rule("7")

        run_mock.assert_called_once_with(
            [
                "nft",
                "delete",
                "rule",
                "inet",
                "firewalld",
                "LIBVIRT_FWI",
                "handle",
                "7",
            ],
            sudo=True,
            check=False,
        )

    def test_remove_nft_forward_rule_returns_when_chain_is_missing(self):
        with patch.object(firewall, "nft_chain_location", return_value=None), patch.object(
            firewall, "run"
        ) as run_mock:
            firewall.remove_nft_forward_rule("7")

        run_mock.assert_not_called()


class CleanupFirewalldVmPolicyTests(unittest.TestCase):
    def test_removes_vm_specific_policy(self):
        direct_rule = [
            "ipv4",
            "filter",
            "FORWARD",
            "-1000",
            "-p",
            "tcp",
            "-d",
            "192.168.240.50",
            "--dport",
            "22",
            "-j",
            "ACCEPT",
        ]

        with patch.object(firewall, "tool_exists", return_value=True), patch.object(
            firewall, "firewalld_zone_exists", return_value=True
        ), patch.object(
            firewall, "find_direct_forward_rules_for_vm", return_value=[direct_rule]
        ), patch.object(
            firewall, "find_nft_forward_rule_handles_for_vm", return_value=["7"]
        ), patch.object(
            firewall,
            "find_forward_port_rules_for_vm",
            return_value=[(None, "port=2222:proto=tcp:toaddr=192.168.240.50:toport=22")],
        ), patch.object(firewall, "remove_direct_rule") as remove_direct_rule_mock, patch.object(
            firewall, "remove_nft_forward_rule"
        ) as remove_nft_rule_mock, patch.object(
            firewall, "remove_forward_port_rule"
        ) as remove_forward_rule_mock, patch.object(
            firewall, "firewalld_zone_is_empty", return_value=True
        ), patch.object(firewall, "run") as run_mock:
            firewall.cleanup_firewalld_vm_policy(
                "demo",
                {
                    "zone": "custom-demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                [{"host": 2222, "guest": 22, "proto": "tcp"}],
            )

        remove_direct_rule_mock.assert_called_once_with(direct_rule)
        remove_nft_rule_mock.assert_called_once_with("7")
        remove_forward_rule_mock.assert_called_once_with(
            "port=2222:proto=tcp:toaddr=192.168.240.50:toport=22",
            zone=None,
        )
        self.assertIn(
            call(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    "custom-demo-zone",
                    "--remove-source",
                    "192.168.240.0/24",
                ],
                sudo=True,
                check=False,
            ),
            run_mock.call_args_list,
        )
        self.assertIn(
            call(
                ["firewall-cmd", "--permanent", "--delete-zone", "custom-demo-zone"],
                sudo=True,
                check=False,
            ),
            run_mock.call_args_list,
        )
        self.assertEqual(
            run_mock.call_args_list[-1],
            call(["firewall-cmd", "--reload"], sudo=True, check=False),
        )

    def test_returns_early_when_firewalld_is_unavailable(self):
        with patch.object(firewall, "tool_exists", return_value=False), patch.object(
            firewall, "run"
        ) as run_mock:
            firewall.cleanup_firewalld_vm_policy("demo", {}, [])

        run_mock.assert_not_called()

    def test_uses_port_fallback_and_cidr_lookup_when_no_rule_scan_matches(self):
        with patch.object(firewall, "tool_exists", return_value=True), patch.object(
            firewall, "firewalld_zone_exists", return_value=False
        ), patch.object(
            firewall, "firewalld_zone_for_cidr", return_value="demo-zone"
        ), patch.object(
            firewall, "find_direct_forward_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_nft_forward_rule_handles_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_forward_port_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "remove_direct_rule"
        ) as remove_direct_rule_mock, patch.object(
            firewall, "remove_nft_forward_rule"
        ) as remove_nft_rule_mock, patch.object(
            firewall, "remove_forward_port_rule"
        ) as remove_forward_rule_mock, patch.object(
            firewall, "firewalld_zone_is_empty", return_value=False
        ), patch.object(firewall, "run") as run_mock:
            firewall.cleanup_firewalld_vm_policy(
                "demo",
                {
                    "zone": "demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                [{"host": 2222, "guest": 22, "proto": "tcp"}],
            )

        remove_direct_rule_mock.assert_called_once_with(
            [
                "ipv4",
                "filter",
                "FORWARD",
                "-1000",
                "-p",
                "tcp",
                "-d",
                "192.168.240.50",
                "--dport",
                "22",
                "-j",
                "ACCEPT",
            ]
        )
        remove_nft_rule_mock.assert_not_called()
        remove_forward_rule_mock.assert_called_once_with(
            "port=2222:proto=tcp:toaddr=192.168.240.50:toport=22"
        )
        self.assertEqual(
            run_mock.call_args_list[-1],
            call(["firewall-cmd", "--reload"], sudo=True, check=False),
        )

    def test_fallback_direct_rules_do_not_run_without_configured_ports(self):
        with patch.object(firewall, "tool_exists", return_value=True), patch.object(
            firewall, "firewalld_zone_exists", return_value=False
        ), patch.object(
            firewall, "firewalld_zone_for_cidr", return_value="demo-zone"
        ), patch.object(
            firewall, "find_direct_forward_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_nft_forward_rule_handles_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_forward_port_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "remove_direct_rule"
        ) as remove_direct_rule_mock, patch.object(
            firewall, "remove_nft_forward_rule"
        ) as remove_nft_rule_mock, patch.object(
            firewall, "remove_forward_port_rule"
        ) as remove_forward_rule_mock, patch.object(
            firewall, "firewalld_zone_is_empty", return_value=False
        ), patch.object(firewall, "run"):
            firewall.cleanup_firewalld_vm_policy(
                "demo",
                {
                    "zone": "demo-zone",
                    "cidr": "192.168.240.0/24",
                    "vm_ip": "192.168.240.50",
                },
                [],
            )

        remove_direct_rule_mock.assert_not_called()
        remove_nft_rule_mock.assert_not_called()
        remove_forward_rule_mock.assert_not_called()

    def test_zone_cleanup_without_cidr_still_removes_rich_rules_and_reloads(self):
        with patch.object(firewall, "tool_exists", return_value=True), patch.object(
            firewall, "firewalld_zone_exists", return_value=True
        ), patch.object(
            firewall, "find_forward_port_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_direct_forward_rules_for_vm", return_value=[]
        ), patch.object(
            firewall, "find_nft_forward_rule_handles_for_vm", return_value=[]
        ), patch.object(
            firewall, "firewalld_zone_is_empty", return_value=False
        ), patch.object(firewall, "run") as run_mock:
            firewall.cleanup_firewalld_vm_policy(
                "demo",
                {"zone": "demo-zone", "vm_ip": "192.168.240.50"},
                [],
            )

        rich_rule_calls = [
            args
            for args in run_mock.call_args_list
            if "--remove-rich-rule" in args.args[0]
        ]
        self.assertEqual(len(rich_rule_calls), len(BLOCKED_PRIVATE_RANGES))
        self.assertEqual(
            run_mock.call_args_list[-1],
            call(["firewall-cmd", "--reload"], sudo=True, check=False),
        )
