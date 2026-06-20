import unittest
from unittest.mock import call, patch

from homelab_vm_provisioner import reconciler


class LibvirtNetworkXmlTests(unittest.TestCase):
    def test_build_libvirt_network_xml_includes_nat_forward_for_nat_profiles(self):
        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }
        vm_records = [
            {
                "vm_name": "alpha",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
            }
        ]

        xml_text = reconciler.build_libvirt_network_xml(network_group, vm_records)

        self.assertIn("<forward mode='nat'/>", xml_text)
        self.assertIn("<host mac='52:54:00:11:22:33' name='alpha' ip='10.80.0.2'/>", xml_text)
        self.assertIn("netmask='255.255.255.240'", xml_text)

    def test_build_libvirt_network_xml_omits_nat_forward_for_private_profiles(self):
        network_group = {
            "profile": "private",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }

        xml_text = reconciler.build_libvirt_network_xml(network_group, [])

        self.assertNotIn("<forward mode='nat'/>", xml_text)

    def test_network_xml_match_ignores_runtime_fields_and_host_order(self):
        current_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <uuid>runtime-uuid</uuid>
          <forward mode='nat'/>
          <bridge delay='0' stp='on' name='hvpb12345678'/>
          <mac address='52:54:00:aa:bb:cc'/>
          <ip netmask='255.255.255.240' address='10.80.0.1'>
            <dhcp>
              <host ip='10.80.0.3' name='bravo' mac='52:54:00:11:22:44'/>
              <range end='10.80.0.14' start='10.80.0.2'/>
              <host ip='10.80.0.2' name='alpha' mac='52:54:00:11:22:33'/>
            </dhcp>
          </ip>
        </network>
        """
        desired_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <forward mode='nat'/>
          <bridge name='hvpb12345678' stp='on' delay='0'/>
          <ip address='10.80.0.1' netmask='255.255.255.240'>
            <dhcp>
              <range start='10.80.0.2' end='10.80.0.14'/>
              <host mac='52:54:00:11:22:33' name='alpha' ip='10.80.0.2'/>
              <host mac='52:54:00:11:22:44' name='bravo' ip='10.80.0.3'/>
            </dhcp>
          </ip>
        </network>
        """

        matches, current_spec, desired_spec = reconciler._network_xml_matches(current_xml, desired_xml)

        self.assertTrue(matches)
        self.assertEqual(current_spec, desired_spec)

    def test_plan_libvirt_network_update_uses_net_update_for_host_only_drift(self):
        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }
        vm_records = [
            {
                "vm_name": "alpha",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
            },
            {
                "vm_name": "bravo",
                "mac_address": "52:54:00:11:22:44",
                "ip_address": "10.80.0.3",
            },
        ]
        current_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <forward mode='nat'/>
          <bridge name='hvpb12345678' stp='on' delay='0'/>
          <ip address='10.80.0.1' netmask='255.255.255.240'>
            <dhcp>
              <range start='10.80.0.2' end='10.80.0.14'/>
              <host mac='52:54:00:11:22:33' name='alpha' ip='10.80.0.2'/>
            </dhcp>
          </ip>
        </network>
        """

        with patch.object(reconciler, "capture_or_none", return_value=current_xml):
            plan = reconciler.plan_libvirt_network_update(network_group, vm_records)

        self.assertEqual(plan["action"], "update-hosts")
        self.assertEqual(plan["host_updates"]["remove"], [])
        self.assertEqual(
            plan["host_updates"]["add"],
            [{"mac": "52:54:00:11:22:44", "name": "bravo", "ip": "10.80.0.3"}],
        )

    def test_ensure_libvirt_network_refuses_recreate_when_active_vms_are_attached(self):
        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }
        vm_records = [
            {
                "vm_name": "alpha",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
            }
        ]
        current_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <forward mode='nat'/>
          <bridge name='hvpb-oldbridge' stp='on' delay='0'/>
          <ip address='10.80.0.1' netmask='255.255.255.240'>
            <dhcp>
              <range start='10.80.0.2' end='10.80.0.14'/>
            </dhcp>
          </ip>
        </network>
        """

        with patch.object(reconciler, "capture_or_none", return_value=current_xml), patch.object(
            reconciler, "_attached_domain_names", return_value=(["alpha"], ["alpha"])
        ), patch.object(reconciler, "bridge_interface_exists", return_value=False), patch.object(
            reconciler, "cleanup_bridge_interface"
        ), patch.object(reconciler, "run") as run_mock:
            with self.assertRaises(reconciler.NetworkReconcileSafetyError) as ctx:
                reconciler.ensure_libvirt_network(network_group, vm_records)

        self.assertEqual(ctx.exception.details["active_attached_vms"], ["alpha"])
        run_mock.assert_not_called()

    def test_ensure_libvirt_network_updates_dhcp_hosts_without_recreate(self):
        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }
        vm_records = [
            {
                "vm_name": "alpha",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
            },
            {
                "vm_name": "bravo",
                "mac_address": "52:54:00:11:22:44",
                "ip_address": "10.80.0.3",
            },
        ]
        current_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <forward mode='nat'/>
          <bridge name='hvpb12345678' stp='on' delay='0'/>
          <ip address='10.80.0.1' netmask='255.255.255.240'>
            <dhcp>
              <range start='10.80.0.2' end='10.80.0.14'/>
              <host mac='52:54:00:11:22:33' name='alpha' ip='10.80.0.2'/>
            </dhcp>
          </ip>
        </network>
        """

        with patch.object(reconciler, "capture_or_none", return_value=current_xml), patch.object(
            reconciler, "ensure_libvirt_network_active"
        ) as ensure_active_mock, patch.object(reconciler, "run") as run_mock:
            result = reconciler.ensure_libvirt_network(network_group, vm_records)

        self.assertEqual(result["action"], "update-hosts")
        ensure_active_mock.assert_called_once_with("hvp-ng-demo", bridge_name="hvpb12345678")
        self.assertEqual(
            run_mock.call_args_list,
            [
                call(
                    [
                        "virsh",
                        "net-update",
                        "hvp-ng-demo",
                        "add-last",
                        "ip-dhcp-host",
                        "<host mac='52:54:00:11:22:44' name='bravo' ip='10.80.0.3'/>",
                        "--live",
                        "--config",
                    ],
                    sudo=True,
                ),
            ],
        )

    def test_ensure_libvirt_network_activates_matching_inactive_network(self):
        network_group = {
            "profile": "isolated_nat",
            "libvirt_network_name": "hvp-ng-demo",
            "bridge_name": "hvpb12345678",
            "subnet_cidr": "10.80.0.0/28",
            "gateway_ip": "10.80.0.1",
            "dhcp_start": "10.80.0.2",
            "dhcp_end": "10.80.0.14",
        }
        vm_records = [
            {
                "vm_name": "alpha",
                "mac_address": "52:54:00:11:22:33",
                "ip_address": "10.80.0.2",
            }
        ]
        current_xml = """
        <network>
          <name>hvp-ng-demo</name>
          <forward mode='nat'/>
          <bridge name='hvpb12345678' stp='on' delay='0'/>
          <ip address='10.80.0.1' netmask='255.255.255.240'>
            <dhcp>
              <range start='10.80.0.2' end='10.80.0.14'/>
              <host mac='52:54:00:11:22:33' name='alpha' ip='10.80.0.2'/>
            </dhcp>
          </ip>
        </network>
        """

        with patch.object(reconciler, "capture_or_none", return_value=current_xml), patch.object(
            reconciler, "ensure_libvirt_network_active"
        ) as ensure_active_mock:
            result = reconciler.ensure_libvirt_network(network_group, vm_records)

        self.assertEqual(result["action"], "none")
        ensure_active_mock.assert_called_once_with("hvp-ng-demo", bridge_name="hvpb12345678")


class PolicyPlanTests(unittest.TestCase):
    def assertSetElements(self, plan, table_key, set_name, expected_elements):
        set_specs = plan[f"{table_key}_sets"]
        matching = [set_spec for set_spec in set_specs if set_spec["name"] == set_name]
        self.assertEqual(len(matching), 1, f"expected exactly one set named {set_name}")
        self.assertEqual(matching[0]["elements"], expected_elements)

    def test_build_nftables_plan_renders_vm_policy_and_port_forward_rules(self):
        network_groups = [
            {
                "id": "ng-a",
                "profile": "isolated_nat",
                "bridge_name": "hvpb11111111",
                "subnet_cidr": "10.80.0.0/28",
                "gateway_ip": "10.80.0.1",
            },
            {
                "id": "ng-b",
                "profile": "isolated_nat",
                "bridge_name": "hvpb22222222",
                "subnet_cidr": "10.80.0.16/28",
                "gateway_ip": "10.80.0.17",
            },
        ]
        live_vm_records = [
            {
                "vm_name": "alpha",
                "network_group_id": "ng-a",
                "ip_address": "10.80.0.2",
                "allow_same_group_traffic": False,
                "allow_host_access": False,
                "allow_private_lan_access": False,
                "internet_access": False,
                "ports": [{"host": 2222, "guest": 22, "proto": "tcp"}],
            },
            {
                "vm_name": "bravo",
                "network_group_id": "ng-b",
                "ip_address": "10.80.0.18",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": True,
                "internet_access": True,
                "ports": [],
            },
        ]

        plan = reconciler.build_nftables_plan(network_groups, live_vm_records, global_config={})

        self.assertSetElements(plan, "filter", "managed_vm_ipv4", ["10.80.0.2", "10.80.0.18"])
        self.assertSetElements(plan, "filter", "hvpb11111111_vm_ipv4", ["10.80.0.2"])
        self.assertSetElements(plan, "filter", "hvpb22222222_vm_ipv4", ["10.80.0.18"])
        self.assertSetElements(plan, "filter", "vm_tcp_services", ["10.80.0.2 . 22"])
        self.assertIn(
            'tcp dport 2222 dnat to 10.80.0.2:22 comment "alpha port-forward 2222->22/tcp"',
            plan["nat_rules"]["prerouting"],
        )
        self.assertIn(
            'ct status dnat ip daddr . tcp dport @vm_tcp_services accept comment "managed tcp port-forwards"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'ct status dnat ip saddr . tcp sport @vm_tcp_services accept comment "managed tcp port-forwards return"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'ether type ip ip saddr @hvpb11111111_same_group_reject_vm_ipv4 ip daddr 10.80.0.0/28 drop comment "ng-a same-bridge drop"',
            plan["bridge_filter_rules"]["forward"],
        )
        self.assertIn(
            'iifname "hvpb11111111" ip saddr @hvpb11111111_vm_ipv4 ip daddr @hvpb11111111_cross_group_ipv4 reject comment "ng-a cross-group reject"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'iifname "hvpb11111111" ip saddr @hvpb11111111_private_lan_reject_vm_ipv4 ip daddr @private_lan_ipv4 reject comment "ng-a private-lan reject"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'iifname "hvpb11111111" ip saddr @hvpb11111111_internet_reject_vm_ipv4 reject comment "ng-a internet reject"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'ether type ip ip saddr @hvpb22222222_same_group_allow_vm_ipv4 ip daddr 10.80.0.16/28 accept comment "ng-b same-bridge allow"',
            plan["bridge_filter_rules"]["forward"],
        )
        self.assertIn(
            'iifname "hvpb22222222" ip saddr @hvpb22222222_private_lan_allow_vm_ipv4 ip daddr @private_lan_ipv4 accept comment "ng-b private-lan allow"',
            plan["filter_rules"]["forward"],
        )
        self.assertIn(
            'iifname "hvpb11111111" ip saddr @hvpb11111111_vm_ipv4 ip daddr 10.80.0.1 udp dport @gateway_udp_service_ports accept comment "ng-a host udp services"',
            plan["filter_rules"]["input"],
        )
        self.assertIn(
            'iifname "hvpb11111111" ip saddr @hvpb11111111_host_reject_vm_ipv4 reject comment "ng-a host reject"',
            plan["filter_rules"]["input"],
        )
        self.assertNotIn(
            'iifname "hvpb22222222" ip saddr @hvpb22222222_host_reject_vm_ipv4 reject comment "ng-b host reject"',
            plan["filter_rules"]["input"],
        )
        self.assertEqual(
            sum(1 for rule in plan["filter_rules"]["forward"] if "managed tcp port-forwards" in rule),
            2,
        )

    def test_build_nftables_plan_treats_standalone_nat_vm_as_isolated_group(self):
        network_groups = [
            {
                "id": "standalone-alpha",
                "profile": "isolated_nat",
                "bridge_name": "virbr-alpha",
                "subnet_cidr": "192.168.240.0/24",
                "gateway_ip": "192.168.240.1",
            }
        ]
        live_vm_records = [
            {
                "vm_name": "alpha",
                "network_group_id": "standalone-alpha",
                "ip_address": "192.168.240.50",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": False,
                "internet_access": True,
                "ports": [{"host": 2222, "guest": 22, "proto": "tcp"}],
            }
        ]

        plan = reconciler.build_nftables_plan(network_groups, live_vm_records, global_config={})

        self.assertSetElements(plan, "filter", "vm_tcp_services", ["192.168.240.50 . 22"])
        self.assertIn(
            'tcp dport 2222 dnat to 192.168.240.50:22 comment "alpha port-forward 2222->22/tcp"',
            plan["nat_rules"]["prerouting"],
        )
        self.assertIn(
            'ether type ip ip saddr @virbr_alpha_same_group_allow_vm_ipv4 ip daddr 192.168.240.0/24 accept comment "standalone-alpha same-bridge allow"',
            plan["bridge_filter_rules"]["forward"],
        )

    def test_build_nftables_plan_is_deterministic_and_compact_for_multiple_vms(self):
        network_groups = [
            {
                "id": "ng-a",
                "profile": "isolated_nat",
                "bridge_name": "hvpb11111111",
                "subnet_cidr": "10.80.0.0/28",
                "gateway_ip": "10.80.0.1",
            }
        ]
        live_vm_records = [
            {
                "vm_name": "charlie",
                "network_group_id": "ng-a",
                "ip_address": "10.80.0.4",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": True,
                "internet_access": True,
                "ports": [{"host": 8080, "guest": 80, "proto": "tcp"}],
            },
            {
                "vm_name": "alpha",
                "network_group_id": "ng-a",
                "ip_address": "10.80.0.2",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": True,
                "internet_access": True,
                "ports": [{"host": 2222, "guest": 22, "proto": "tcp"}],
            },
        ]

        first_plan = reconciler.build_nftables_plan(network_groups, live_vm_records, global_config={})
        second_plan = reconciler.build_nftables_plan(
            network_groups,
            list(reversed(live_vm_records)),
            global_config={},
        )

        self.assertEqual(first_plan, second_plan)
        self.assertSetElements(
            first_plan,
            "filter",
            "vm_tcp_services",
            ["10.80.0.2 . 22", "10.80.0.4 . 80"],
        )
        self.assertEqual(
            len([rule for rule in first_plan["filter_rules"]["forward"] if "managed tcp port-forwards" in rule]),
            2,
        )
        self.assertNotIn(
            'ct status dnat ip daddr 10.80.0.2 tcp dport 22 accept',
            "\n".join(first_plan["filter_rules"]["forward"]),
        )

    def test_build_nftables_plan_omits_empty_vm_sets(self):
        plan = reconciler.build_nftables_plan([], [], global_config={})

        self.assertEqual(plan["managed_vm_ips"], [])
        self.assertEqual(plan["nat_rules"]["prerouting"], [])
        self.assertEqual(plan["bridge_filter_rules"]["forward"], [])
        self.assertEqual([set_spec for set_spec in plan["filter_sets"] if set_spec["name"] == "managed_vm_ipv4"], [])

    def test_build_nftables_plan_updates_sets_when_vm_or_port_is_removed(self):
        network_groups = [
            {
                "id": "ng-a",
                "profile": "isolated_nat",
                "bridge_name": "hvpb11111111",
                "subnet_cidr": "10.80.0.0/28",
                "gateway_ip": "10.80.0.1",
            }
        ]
        original_vms = [
            {
                "vm_name": "alpha",
                "network_group_id": "ng-a",
                "ip_address": "10.80.0.2",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": True,
                "internet_access": True,
                "ports": [{"host": 2222, "guest": 22, "proto": "tcp"}],
            },
            {
                "vm_name": "bravo",
                "network_group_id": "ng-a",
                "ip_address": "10.80.0.3",
                "allow_same_group_traffic": True,
                "allow_host_access": True,
                "allow_private_lan_access": True,
                "internet_access": True,
                "ports": [{"host": 8080, "guest": 80, "proto": "tcp"}],
            },
        ]
        reduced_vms = [original_vms[0]]

        original_plan = reconciler.build_nftables_plan(network_groups, original_vms, global_config={})
        reduced_plan = reconciler.build_nftables_plan(network_groups, reduced_vms, global_config={})

        self.assertSetElements(
            original_plan,
            "filter",
            "vm_tcp_services",
            ["10.80.0.2 . 22", "10.80.0.3 . 80"],
        )
        self.assertSetElements(reduced_plan, "filter", "vm_tcp_services", ["10.80.0.2 . 22"])
        self.assertEqual(
            reduced_plan["nat_rules"]["prerouting"],
            ['tcp dport 2222 dnat to 10.80.0.2:22 comment "alpha port-forward 2222->22/tcp"'],
        )


class ReconcileTests(unittest.TestCase):
    def test_reconcile_networking_skips_libvirt_for_policy_only_mode(self):
        nftables_plan = {
            "backend": "nftables",
            "managed_subnets": [],
            "managed_vm_ips": [],
            "filter_rules": {"forward": [], "input": []},
            "nat_rules": {"prerouting": [], "postrouting": []},
            "bridge_filter_rules": {"forward": []},
        }

        with patch.object(reconciler, "load_global_config", return_value={}), patch.object(
            reconciler, "configured_vm_records", return_value=[]
        ), patch.object(reconciler, "grouped_network_records", return_value=[]), patch.object(
            reconciler, "ensure_libvirt_network"
        ) as ensure_mock, patch.object(
            reconciler, "build_nftables_plan", return_value=nftables_plan
        ) as build_mock, patch.object(reconciler, "apply_nftables_plan") as apply_mock:
            result = reconciler.reconcile_networking(policy_only=True)

        ensure_mock.assert_not_called()
        build_mock.assert_called_once_with([], [], global_config={})
        apply_mock.assert_called_once_with(nftables_plan)
        self.assertTrue(result["policy_only"])
        self.assertEqual(result["backend"], "nftables")

    def test_reconcile_networking_uses_native_nftables_backend(self):
        nftables_plan = {
            "backend": "nftables",
            "managed_subnets": ["10.80.0.0/28"],
            "managed_vm_ips": ["10.80.0.2"],
            "filter_rules": {"forward": [], "input": []},
            "nat_rules": {"prerouting": ["tcp dport 2222 dnat to 10.80.0.2:22"], "postrouting": []},
            "bridge_filter_rules": {"forward": []},
        }
        vm_records = [{"state_exists": True, "ip_address": "10.80.0.2"}]
        network_groups = [{"id": "ng-a", "bridge_name": "hvpb11111111", "profile": "isolated_nat"}]

        with patch.object(reconciler, "load_global_config", return_value={}), patch.object(
            reconciler, "configured_vm_records", return_value=vm_records
        ), patch.object(
            reconciler, "grouped_network_records", return_value=network_groups
        ), patch.object(reconciler, "ensure_libvirt_network") as ensure_mock, patch.object(
            reconciler, "build_nftables_plan", return_value=nftables_plan
        ) as build_mock, patch.object(
            reconciler,
            "apply_nftables_plan",
            return_value={"verify": {"filter": {"family": "inet", "name": "hvp_filter"}}},
        ) as apply_mock:
            result = reconciler.reconcile_networking(policy_only=True)

        ensure_mock.assert_not_called()
        build_mock.assert_called_once_with(
            network_groups,
            vm_records,
            global_config={},
        )
        apply_mock.assert_called_once_with(nftables_plan)
        self.assertTrue(result["policy_only"])
        self.assertEqual(result["backend"], "nftables")
        self.assertIsNotNone(result["nftables"])
