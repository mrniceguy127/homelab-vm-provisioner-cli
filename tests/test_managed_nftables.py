import unittest
from types import SimpleNamespace
from unittest.mock import patch

from homelab_vm_provisioner import managed_nftables


class ManagedNftablesTests(unittest.TestCase):
    def test_render_ruleset_replaces_existing_tables_atomically(self):
        plan = {
            "filter_sets": [
                {
                    "name": "managed_vm_ipv4",
                    "type": "ipv4_addr",
                    "elements": ["10.80.0.2", "10.80.0.3"],
                    "flags": [],
                }
            ],
            "filter_rules": {
                "forward": ["ip daddr @managed_vm_ipv4 ct state established,related accept"],
                "input": ["ct state established,related accept"],
            },
            "nat_sets": [],
            "nat_rules": {
                "prerouting": ["tcp dport 2222 dnat to 10.80.0.2:22"],
                "postrouting": [],
            },
            "bridge_filter_sets": [],
            "bridge_filter_rules": {
                "forward": [
                    'ether type ip ip saddr 10.80.0.2 ip daddr 10.80.0.0/28 drop'
                ],
            },
        }

        ruleset_text = managed_nftables.render_ruleset(
            plan,
            previous_tables={
                "filter": "table inet hvp_filter {}",
                "nat": "table ip hvp_nat {}",
                "bridge_filter": "table bridge hvp_bridge_filter {}",
            },
        )

        self.assertIn("delete table inet hvp_filter", ruleset_text)
        self.assertIn("delete table ip hvp_nat", ruleset_text)
        self.assertIn("delete table bridge hvp_bridge_filter", ruleset_text)
        self.assertIn("table inet hvp_filter {", ruleset_text)
        self.assertIn("set managed_vm_ipv4 {", ruleset_text)
        self.assertIn("elements = { 10.80.0.2, 10.80.0.3 }", ruleset_text)
        self.assertIn("type filter hook forward priority -10; policy accept;", ruleset_text)
        self.assertIn("table ip hvp_nat {", ruleset_text)
        self.assertIn("type nat hook prerouting priority dstnat; policy accept;", ruleset_text)
        self.assertIn("table bridge hvp_bridge_filter {", ruleset_text)
        self.assertIn(
            'ether type ip ip saddr 10.80.0.2 ip daddr 10.80.0.0/28 drop',
            ruleset_text,
        )

    def test_apply_ruleset_passes_batch_to_nft(self):
        plan = {
            "filter_sets": [],
            "filter_rules": {"forward": [], "input": []},
            "nat_sets": [],
            "nat_rules": {"prerouting": [], "postrouting": []},
            "bridge_filter_sets": [],
            "bridge_filter_rules": {"forward": []},
        }

        with patch.object(
            managed_nftables,
            "current_tables",
            return_value={"filter": None, "nat": None, "bridge_filter": None},
        ), patch.object(
            managed_nftables,
            "tool_exists",
            return_value=False,
        ), patch.object(
            managed_nftables.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as run_mock:
            result = managed_nftables.apply_ruleset(plan)

        self.assertEqual(
            result["previous_tables"],
            {"filter": False, "nat": False, "bridge_filter": False},
        )
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0], ["sudo", "nft", "-f", "-"])
        self.assertIn("table inet hvp_filter", run_mock.call_args.kwargs["input"])
        self.assertIn("table bridge hvp_bridge_filter", run_mock.call_args.kwargs["input"])

    def test_apply_ruleset_best_effort_loads_bridge_modules_when_needed(self):
        plan = {
            "filter_sets": [],
            "filter_rules": {"forward": [], "input": []},
            "nat_sets": [],
            "nat_rules": {"prerouting": [], "postrouting": []},
            "bridge_filter_sets": [],
            "bridge_filter_rules": {"forward": ["ip saddr 10.80.0.2 reject"]},
        }

        with patch.object(
            managed_nftables,
            "current_tables",
            return_value={"filter": None, "nat": None, "bridge_filter": None},
        ), patch.object(
            managed_nftables,
            "tool_exists",
            return_value=True,
        ), patch.object(
            managed_nftables.os,
            "geteuid",
            return_value=1,
        ), patch.object(
            managed_nftables,
            "run",
        ) as helper_run_mock, patch.object(
            managed_nftables.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ):
            managed_nftables.apply_ruleset(plan)

        helper_run_mock.assert_any_call(["modprobe", "bridge"], sudo=True, check=False)
        helper_run_mock.assert_any_call(["modprobe", "br_netfilter"], sudo=True, check=False)
        helper_run_mock.assert_any_call(["modprobe", "nf_tables_bridge"], sudo=True, check=False)

    def test_verify_tables_returns_summary_when_required_chains_exist(self):
        with patch.object(
            managed_nftables,
            "list_table",
            side_effect=[
                "table inet hvp_filter {\n    chain forward {\n    }\n    chain input {\n    }\n}",
                "table ip hvp_nat {\n    chain prerouting {\n    }\n    chain postrouting {\n    }\n}",
                "table bridge hvp_bridge_filter {\n    chain forward {\n    }\n}",
            ],
        ):
            summary = managed_nftables.verify_tables()

        self.assertEqual(summary["filter"], {"family": "inet", "name": "hvp_filter"})
        self.assertEqual(summary["nat"], {"family": "ip", "name": "hvp_nat"})
        self.assertEqual(
            summary["bridge_filter"],
            {"family": "bridge", "name": "hvp_bridge_filter"},
        )

    def test_verify_tables_raises_when_chain_is_missing(self):
        with patch.object(
            managed_nftables,
            "list_table",
            side_effect=[
                "table inet hvp_filter {\n    chain forward {\n    }\n}",
                "table ip hvp_nat {\n    chain prerouting {\n    }\n    chain postrouting {\n    }\n}",
                "table bridge hvp_bridge_filter {\n    chain forward {\n    }\n}",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "hvp_filter.input"):
                managed_nftables.verify_tables()

    def test_verify_tables_raises_when_bridge_chain_is_missing(self):
        with patch.object(
            managed_nftables,
            "list_table",
            side_effect=[
                "table inet hvp_filter {\n    chain forward {\n    }\n    chain input {\n    }\n}",
                "table ip hvp_nat {\n    chain prerouting {\n    }\n    chain postrouting {\n    }\n}",
                "table bridge hvp_bridge_filter {\n}",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "hvp_bridge_filter.forward"):
                managed_nftables.verify_tables()

    def test_apply_ruleset_raises_structured_error_with_stderr(self):
        plan = {
            "filter_sets": [],
            "filter_rules": {"forward": [], "input": []},
            "nat_sets": [],
            "nat_rules": {"prerouting": [], "postrouting": []},
            "bridge_filter_sets": [],
            "bridge_filter_rules": {"forward": []},
        }

        with patch.object(
            managed_nftables,
            "current_tables",
            return_value={"filter": None, "nat": None, "bridge_filter": None},
        ), patch.object(
            managed_nftables,
            "tool_exists",
            return_value=False,
        ), patch.object(
            managed_nftables.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="line 3: syntax error"),
        ):
            with self.assertRaises(managed_nftables.ManagedNftablesApplyError) as ctx:
                managed_nftables.apply_ruleset(plan)

        self.assertEqual(ctx.exception.details["code"], "managed_nftables_apply_failed")
        self.assertIn("syntax error", str(ctx.exception))
