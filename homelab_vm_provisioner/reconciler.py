"""Reconcile VM networking from saved configuration and runtime state."""

import ipaddress
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import (
    default_config_file_for_vm,
    default_vm_state_root,
    load_config,
    load_global_config,
    load_vm_state,
)
from .constants import BLOCKED_PRIVATE_RANGES
from .core import normalize_network_profile as core_normalize_network_profile
from .managed_nftables import apply_ruleset as apply_managed_nftables_ruleset
from .managed_nftables import verify_tables as verify_managed_nftables_tables
from .provision import (
    bridge_interface_exists,
    cleanup_bridge_interface,
    ensure_libvirt_network_active,
)
from .system import capture_or_none, run


class NetworkReconcileSafetyError(RuntimeError):
    """Raised when destructive libvirt network reconciliation would impact live VMs."""

    def __init__(self, network_name, attached_vms, active_attached_vms):
        self.details = {
            "code": "network_recreate_blocked",
            "network_name": network_name,
            "attached_vms": attached_vms,
            "active_attached_vms": active_attached_vms,
        }
        active_summary = ", ".join(active_attached_vms)
        super().__init__(
            f"Refusing to recreate libvirt network {network_name} while active attached VMs exist: "
            f"{active_summary}. Retry only with an explicit destructive reconcile after those VMs are stopped."
        )


def _log_reconcile(message, **context):
    suffix = f" {json.dumps(context, sort_keys=True)}" if context else ""
    print(f"[reconcile] {message}{suffix}")


def configured_private_lan_cidrs(global_config=None):
    """Return configured private LAN CIDRs eligible for admin access."""
    if global_config is None:
        global_config = load_global_config()

    networking = global_config.get("networking") or {}
    values = networking.get("private_lan_cidrs") or []
    return [str(value).strip() for value in values if str(value).strip()]


def blocked_private_lan_targets(network_groups, global_config=None):
    """Return the private LAN CIDRs that managed VMs should treat as blocked by default."""
    return list(BLOCKED_PRIVATE_RANGES)


def normalize_network_profile(network):
    """Map legacy and current network identifiers into one profile value."""
    # Delegate to pure function from core
    return core_normalize_network_profile(network)


def configured_vm_records():
    """Load desired VM networking records from saved VM configs and runtime state."""
    config_root = default_config_file_for_vm("placeholder").parent
    if not config_root.exists():
        return []

    state_root = default_vm_state_root()
    records = []
    for config_path in sorted(config_root.glob("*.yaml")):
        config = load_config(config_path) or {}
        vm = config.get("vm") or {}
        config_network = config.get("network") or {}
        vm_name = vm.get("name") or config_path.stem
        state_path = state_root / f"{vm_name}.yaml"
        state_exists = state_path.exists()
        state = load_vm_state(vm_name) if state_exists else {}
        effective_network = {**(state.get("network") or {}), **config_network}
        profile = normalize_network_profile(effective_network)
        synthetic_group_id = None
        if state_exists and profile != "bridged":
            synthetic_group_id = f"standalone-{vm_name}"

        group_id = (
            vm.get("network_group_id")
            or effective_network.get("network_group_id")
            or synthetic_group_id
        )
        if not group_id:
            continue

        default_private_lan_access = str(vm.get("trust") or state.get("trust") or "untrusted") == "trusted"

        records.append(
            {
                "vm_name": vm_name,
                "config_path": str(config_path),
                "owner_user_id": vm.get("owner_user_id"),
                "network_group_id": group_id,
                "network_group_name": effective_network.get("group_name") or vm_name,
                "profile": profile,
                "libvirt_network_name": effective_network.get("libvirt_network_name") or effective_network.get("name"),
                "bridge_name": effective_network.get("bridge_name"),
                "subnet_cidr": effective_network.get("subnet_cidr") or effective_network.get("cidr"),
                "gateway_ip": effective_network.get("gateway_ip") or effective_network.get("gateway"),
                "dhcp_start": effective_network.get("dhcp_start"),
                "dhcp_end": effective_network.get("dhcp_end"),
                "mac_address": vm.get("mac_address") or effective_network.get("mac"),
                "ip_address": vm.get("ip_address") or effective_network.get("vm_ip"),
                "allow_same_group_traffic": vm.get("allow_same_group_traffic", True),
                "allow_host_access": vm.get("allow_host_access", True),
                "allow_private_lan_access": bool(
                    vm.get("allow_private_lan_access", default_private_lan_access)
                ),
                "internet_access": vm.get("internet_access", True),
                "ports": config.get("ports") or state.get("ports") or [],
                "state_exists": state_exists,
            }
        )

    return records


def grouped_network_records(vm_records):
    """Group VM records by network-group id."""
    groups = {}
    for record in vm_records:
        group = groups.setdefault(
            record["network_group_id"],
            {
                "id": record["network_group_id"],
                "owner_user_id": record["owner_user_id"],
                "name": record["network_group_name"],
                "profile": record["profile"],
                "libvirt_network_name": record["libvirt_network_name"],
                "bridge_name": record["bridge_name"],
                "subnet_cidr": record["subnet_cidr"],
                "gateway_ip": record["gateway_ip"],
                "dhcp_start": record["dhcp_start"],
                "dhcp_end": record["dhcp_end"],
                "vms": [],
            },
        )
        group["vms"].append(record)

    return list(groups.values())


def build_libvirt_network_xml(network_group, vm_records):
    """Render the desired libvirt XML for one managed network group."""
    if network_group["profile"] == "bridged":
        return None

    subnet = ipaddress.ip_network(network_group["subnet_cidr"], strict=False)
    hosts = "\n".join(
        f"      <host mac='{vm['mac_address']}' name='{vm['vm_name']}' ip='{vm['ip_address']}'/>"
        for vm in sorted(vm_records, key=lambda item: item["vm_name"])
        if vm.get("mac_address") and vm.get("ip_address")
    )
    forward = "  <forward mode='nat'/>\n" if network_group["profile"] in ("nat", "isolated_nat") else ""

    return (
        "<network>\n"
        f"  <name>{network_group['libvirt_network_name']}</name>\n"
        f"{forward}"
        f"  <bridge name='{network_group['bridge_name']}' stp='on' delay='0'/>\n"
        f"  <ip address='{network_group['gateway_ip']}' netmask='{subnet.netmask}'>\n"
        "    <dhcp>\n"
        f"      <range start='{network_group['dhcp_start']}' end='{network_group['dhcp_end']}'/>\n"
        f"{hosts}\n"
        "    </dhcp>\n"
        "  </ip>\n"
        "</network>"
    )


def _filter_rule(chain, priority, source, destination, action, in_interface=None):
    rule = ["ipv4", "filter", chain, str(priority)]
    if in_interface:
        rule.extend(["-i", in_interface])
    rule.extend(["-s", source, "-d", destination, "-j", action])
    return rule


def _forward_rule(priority, source, destination, action, in_interface=None):
    return _filter_rule("FORWARD", priority, source, destination, action, in_interface=in_interface)


def _nft_string(value):
    return json.dumps(str(value))


def _nft_rule(parts, comment=None):
    line = " ".join(str(part) for part in parts if part is not None)
    if comment:
        line = f"{line} comment {_nft_string(comment)}"
    return line


def _sorted_enabled_ports(ports):
    enabled_ports = []
    for port in ports:
        if port.get("enabled", True) is False:
            continue
        enabled_ports.append(
            {
                "host": int(port.get("external_port", port.get("host"))),
                "guest": int(port.get("internal_port", port.get("guest"))),
                "proto": str(port.get("protocol", port.get("proto", "tcp"))).strip().lower()
                or "tcp",
            }
        )

    return sorted(
        enabled_ports,
        key=lambda item: (item["proto"], item["host"], item["guest"]),
    )


def _nft_identifier(value):
    """Convert an arbitrary label into a stable nftables identifier."""

    normalized = "".join(ch if ch.isalnum() else "_" for ch in str(value).strip().lower())
    normalized = normalized.strip("_") or "set"
    if normalized[0].isdigit():
        normalized = f"s_{normalized}"
    return normalized


def _sorted_ipv4_addresses(values):
    unique_values = {str(value).strip() for value in values if str(value).strip()}
    return [str(value) for value in sorted(unique_values, key=ipaddress.ip_address)]


def _sorted_ipv4_networks(values):
    unique_networks = {
        str(ipaddress.ip_network(str(value).strip(), strict=False))
        for value in values
        if str(value).strip()
    }
    return [
        str(value)
        for value in sorted(
            unique_networks,
            key=lambda item: (
                int(ipaddress.ip_network(item, strict=False).network_address),
                ipaddress.ip_network(item, strict=False).prefixlen,
            ),
        )
    ]


def _sorted_service_tuples(values):
    return [
        f"{ip_address} . {service_port}"
        for ip_address, service_port in sorted(
            values,
            key=lambda item: (int(ipaddress.ip_address(item[0])), int(item[1])),
        )
    ]


def _append_nft_set(plan, table_key, name, set_type, elements, flags=None):
    """Append one deterministic set definition when it has elements."""

    if not elements:
        return None

    plan[f"{table_key}_sets"].append(
        {
            "name": name,
            "type": set_type,
            "elements": elements,
            "flags": flags or [],
        }
    )
    return name


def build_nftables_plan(network_groups, live_vm_records, global_config=None):
    """Build the desired application-owned nftables tables."""

    if global_config is None:
        global_config = load_global_config()

    plan = {
        "backend": "nftables",
        "managed_subnets": _sorted_ipv4_networks(
            group["subnet_cidr"] for group in network_groups if group.get("subnet_cidr")
        ),
        "managed_vm_ips": _sorted_ipv4_addresses(
            record["ip_address"] for record in live_vm_records if record.get("ip_address")
        ),
        "filter_sets": [],
        "filter_rules": {
            "forward": [],
            "input": [],
        },
        "nat_sets": [],
        "nat_rules": {
            "prerouting": [],
            "postrouting": [],
        },
        "bridge_filter_sets": [],
        "bridge_filter_rules": {
            "forward": [],
        },
    }

    blocked_private_targets = blocked_private_lan_targets(network_groups, global_config)
    subnet_groups = {
        group["id"]: group
        for group in sorted(network_groups, key=lambda item: item["id"])
        if group.get("profile") != "bridged" and group.get("subnet_cidr")
    }
    subnet_group_list = list(subnet_groups.values())

    _append_nft_set(
        plan,
        "filter",
        "managed_vm_ipv4",
        "ipv4_addr",
        _sorted_ipv4_addresses(plan["managed_vm_ips"]),
    )
    _append_nft_set(
        plan,
        "filter",
        "managed_subnets_ipv4",
        "ipv4_addr",
        _sorted_ipv4_networks(plan["managed_subnets"]),
        flags=["interval"],
    )
    private_lan_set = _append_nft_set(
        plan,
        "filter",
        "private_lan_ipv4",
        "ipv4_addr",
        _sorted_ipv4_networks(blocked_private_targets),
        flags=["interval"],
    )
    gateway_udp_ports = _append_nft_set(
        plan,
        "filter",
        "gateway_udp_service_ports",
        "inet_service",
        ["53", "67"],
    )
    gateway_tcp_ports = _append_nft_set(
        plan,
        "filter",
        "gateway_tcp_service_ports",
        "inet_service",
        ["53"],
    )

    dnat_service_sets = {"tcp": set(), "udp": set()}

    for group in subnet_group_list:
        bridge_name = group.get("bridge_name")
        gateway_ip = group.get("gateway_ip")
        subnet_cidr = group.get("subnet_cidr")
        if not bridge_name or not gateway_ip or not subnet_cidr:
            continue

        group_vms = [
            vm
            for vm in sorted(live_vm_records, key=lambda item: item.get("vm_name") or "")
            if vm.get("network_group_id") == group["id"] and vm.get("ip_address")
        ]
        if not group_vms:
            continue

        set_prefix = _nft_identifier(bridge_name)
        all_vm_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(vm["ip_address"] for vm in group_vms),
        )
        host_allow_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_host_allow_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_host_access", True)
            ),
        )
        host_reject_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_host_reject_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_host_access", True) is False
            ),
        )
        same_group_allow_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_same_group_allow_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_same_group_traffic", True)
            ),
        )
        same_group_reject_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_same_group_reject_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_same_group_traffic", True) is False
            ),
        )
        private_allow_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_private_lan_allow_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_private_lan_access")
            ),
        )
        private_reject_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_private_lan_reject_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if not vm.get("allow_private_lan_access")
            ),
        )
        internet_reject_set = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_internet_reject_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("internet_access", True) is False
            ),
        )
        cross_group_targets = _append_nft_set(
            plan,
            "filter",
            f"{set_prefix}_cross_group_ipv4",
            "ipv4_addr",
            _sorted_ipv4_networks(
                other_group["subnet_cidr"]
                for other_group in subnet_group_list
                if other_group["id"] != group["id"]
            ),
            flags=["interval"],
        )
        bridge_same_group_allow_set = _append_nft_set(
            plan,
            "bridge_filter",
            f"{set_prefix}_same_group_allow_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_same_group_traffic", True)
            ),
        )
        bridge_same_group_reject_set = _append_nft_set(
            plan,
            "bridge_filter",
            f"{set_prefix}_same_group_reject_vm_ipv4",
            "ipv4_addr",
            _sorted_ipv4_addresses(
                vm["ip_address"] for vm in group_vms if vm.get("allow_same_group_traffic", True) is False
            ),
        )

        if all_vm_set and gateway_udp_ports:
            plan["filter_rules"]["input"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{all_vm_set}",
                        "ip",
                        "daddr",
                        gateway_ip,
                        "udp",
                        "dport",
                        f"@{gateway_udp_ports}",
                        "accept",
                    ],
                    comment=f"{group['id']} host udp services",
                )
            )
        if all_vm_set and gateway_tcp_ports:
            plan["filter_rules"]["input"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{all_vm_set}",
                        "ip",
                        "daddr",
                        gateway_ip,
                        "tcp",
                        "dport",
                        f"@{gateway_tcp_ports}",
                        "accept",
                    ],
                    comment=f"{group['id']} host tcp services",
                )
            )
        if host_reject_set:
            plan["filter_rules"]["input"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{host_reject_set}",
                        "ct state established,related accept",
                    ],
                    comment=f"{group['id']} host reject (let host in)",
                )
            )
            plan["filter_rules"]["input"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{host_reject_set}",
                        "reject",
                    ],
                    comment=f"{group['id']} host reject",
                )
            )
        if host_allow_set:
            plan["filter_rules"]["input"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{host_allow_set}",
                        "accept",
                    ],
                    comment=f"{group['id']} host accept",
                )
            )
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{host_allow_set}",
                        "ip",
                        "daddr",
                        gateway_ip,
                        "accept",
                    ],
                    comment=f"{group['id']} allow vm access to host",
                )
            )
        if bridge_same_group_allow_set:
            plan["bridge_filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "ether",
                        "type",
                        "ip",
                        "ip",
                        "saddr",
                        f"@{bridge_same_group_allow_set}",
                        "ip",
                        "daddr",
                        subnet_cidr,
                        "accept",
                    ],
                    comment=f"{group['id']} same-bridge allow",
                )
            )
        if same_group_allow_set:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{same_group_allow_set}",
                        "ip",
                        "daddr",
                        subnet_cidr,
                        "accept",
                    ],
                    comment=f"{group['id']} allow same group traffic",
                )
            )
        if bridge_same_group_reject_set:
            plan["bridge_filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "ether",
                        "type",
                        "ip",
                        "ip",
                        "saddr",
                        f"@{bridge_same_group_reject_set}",
                        "ip",
                        "daddr",
                        subnet_cidr,
                        "drop",
                    ],
                    comment=f"{group['id']} same-bridge drop",
                )
            )
        if same_group_reject_set:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{same_group_reject_set}",
                        "ip",
                        "daddr",
                        subnet_cidr,
                        "reject",
                    ],
                    comment=f"{group['id']} reject same group traffic",
                )
            )
        if all_vm_set and cross_group_targets:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{all_vm_set}",
                        "ip",
                        "daddr",
                        f"@{cross_group_targets}",
                        "reject",
                    ],
                    comment=f"{group['id']} cross-group reject",
                )
            )
        if private_lan_set and private_allow_set:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{private_allow_set}",
                        "ip",
                        "daddr",
                        f"@{private_lan_set}",
                        "accept",
                    ],
                    comment=f"{group['id']} private-lan allow",
                )
            )
        if private_lan_set and private_reject_set:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{private_reject_set}",
                        "ip",
                        "daddr",
                        f"@{private_lan_set}",
                        "reject",
                    ],
                    comment=f"{group['id']} private-lan reject",
                )
            )
        if internet_reject_set:
            plan["filter_rules"]["forward"].append(
                _nft_rule(
                    [
                        "iifname",
                        _nft_string(bridge_name),
                        "ip",
                        "saddr",
                        f"@{internet_reject_set}",
                        "reject",
                    ],
                    comment=f"{group['id']} internet reject",
                )
            )

    for vm in sorted(
        live_vm_records,
        key=lambda item: (item.get("network_group_id") or "", item.get("vm_name") or ""),
    ):
        vm_ip = vm.get("ip_address")
        if not vm_ip:
            continue

        for port in _sorted_enabled_ports(vm.get("ports") or []):
            nat_comment = f"{vm['vm_name']} port-forward {port['host']}->{port['guest']}/{port['proto']}"
            plan["nat_rules"]["prerouting"].append(
                _nft_rule(
                    [
                        port["proto"],
                        "dport",
                        str(port["host"]),
                        "dnat",
                        "to",
                        f"{vm_ip}:{port['guest']}",
                    ],
                    comment=nat_comment,
                )
            )
            dnat_service_sets[port["proto"]].add((vm_ip, int(port["guest"])))

    for proto, service_pairs in sorted(dnat_service_sets.items()):
        set_name = _append_nft_set(
            plan,
            "filter",
            f"vm_{proto}_services",
            "ipv4_addr . inet_service",
            _sorted_service_tuples(service_pairs),
        )
        if not set_name:
            continue

        plan["filter_rules"]["forward"].append(
            _nft_rule(
                [
                    "ct",
                    "status",
                    "dnat",
                    "ip",
                    "daddr",
                    ".",
                    proto,
                    "dport",
                    f"@{set_name}",
                    "accept",
                ],
                comment=f"managed {proto} port-forwards",
            )
        )
        plan["filter_rules"]["forward"].append(
            _nft_rule(
                [
                    "ct",
                    "status",
                    "dnat",
                    "ip",
                    "saddr",
                    ".",
                    proto,
                    "sport",
                    f"@{set_name}",
                    "accept",
                ],
                comment=f"managed {proto} port-forwards return",
            )
        )

    return plan


def _sorted_host_specs(dhcp_node):
    hosts = []
    if dhcp_node is None:
        return hosts

    for host_node in dhcp_node.findall("host"):
        hosts.append(
            {
                "mac": host_node.get("mac"),
                "name": host_node.get("name"),
                "ip": host_node.get("ip"),
            }
        )

    return sorted(hosts, key=lambda host: (host.get("name") or "", host.get("mac") or "", host.get("ip") or ""))


def _libvirt_structural_spec(spec):
    return {
        "name": spec.get("name"),
        "forward_mode": spec.get("forward_mode"),
        "bridge": spec.get("bridge"),
        "ip": spec.get("ip"),
        "dhcp_range": spec.get("dhcp_range"),
    }


def _build_dhcp_host_xml(host_spec):
    return f"<host mac='{host_spec['mac']}' name='{host_spec['name']}' ip='{host_spec['ip']}'/>"


def _planned_dhcp_host_updates(current_spec, desired_spec):
    current_hosts = {host.get("name"): host for host in current_spec.get("hosts") or [] if host.get("name")}
    desired_hosts = {host.get("name"): host for host in desired_spec.get("hosts") or [] if host.get("name")}

    removals = []
    additions = []

    for name, current_host in current_hosts.items():
        desired_host = desired_hosts.get(name)
        if desired_host != current_host:
            removals.append(current_host)

    for name, desired_host in desired_hosts.items():
        current_host = current_hosts.get(name)
        if current_host != desired_host:
            additions.append(desired_host)

    return {
        "remove": sorted(removals, key=lambda host: host["name"]),
        "add": sorted(additions, key=lambda host: host["name"]),
    }


def _libvirt_network_spec(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    bridge_node = root.find("bridge")
    forward_node = root.find("forward")
    ip_node = root.find("ip")
    dhcp_node = ip_node.find("dhcp") if ip_node is not None else None
    range_node = dhcp_node.find("range") if dhcp_node is not None else None

    return {
        "name": root.findtext("name"),
        "forward_mode": forward_node.get("mode") if forward_node is not None else None,
        "bridge": {
            "name": bridge_node.get("name") if bridge_node is not None else None,
            "stp": bridge_node.get("stp") if bridge_node is not None else None,
            "delay": bridge_node.get("delay") if bridge_node is not None else None,
        },
        "ip": {
            "address": ip_node.get("address") if ip_node is not None else None,
            "netmask": ip_node.get("netmask") if ip_node is not None else None,
        },
        "dhcp_range": {
            "start": range_node.get("start") if range_node is not None else None,
            "end": range_node.get("end") if range_node is not None else None,
        },
        "hosts": _sorted_host_specs(dhcp_node),
    }


def _list_domain_names(active_only=False):
    cmd = ["virsh", "list", "--name"] if active_only else ["virsh", "list", "--all", "--name"]
    output = capture_or_none(cmd, sudo=True) or ""
    return [line.strip() for line in output.splitlines() if line.strip()]


def _domain_uses_managed_network(vm_name, network_name, bridge_name=None):
    xml_text = capture_or_none(["virsh", "dumpxml", vm_name], sudo=True)
    if not xml_text:
        return False

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False

    for interface_node in root.findall(".//devices/interface"):
        source_node = interface_node.find("source")
        if source_node is None:
            continue

        if interface_node.get("type") == "network" and source_node.get("network") == network_name:
            return True
        if bridge_name and interface_node.get("type") == "bridge" and source_node.get("bridge") == bridge_name:
            return True

    return False


def _attached_domain_names(network_name, bridge_name=None):
    all_domains = _list_domain_names(active_only=False)
    active_domains = set(_list_domain_names(active_only=True))
    attached_domains = []
    active_attached_domains = []

    for vm_name in all_domains:
        if not _domain_uses_managed_network(vm_name, network_name, bridge_name=bridge_name):
            continue
        attached_domains.append(vm_name)
        if vm_name in active_domains:
            active_attached_domains.append(vm_name)

    return attached_domains, active_attached_domains


def _network_xml_matches(current_xml, desired_xml):
    current_spec = _libvirt_network_spec(current_xml)
    desired_spec = _libvirt_network_spec(desired_xml)
    return current_spec == desired_spec and current_spec is not None, current_spec, desired_spec


def plan_libvirt_network_update(network_group, vm_records, allow_destructive=False):
    """Plan the required libvirt update for one managed network group."""
    desired_xml = build_libvirt_network_xml(network_group, vm_records)
    if desired_xml is None:
        return {
            "name": network_group["libvirt_network_name"],
            "action": "skip",
            "status": "skipped",
            "reason": "bridged-profile",
        }

    network_name = network_group["libvirt_network_name"]
    current_xml = capture_or_none(["virsh", "net-dumpxml", network_name], sudo=True)
    current_spec = _libvirt_network_spec(current_xml) if current_xml else None
    desired_spec = _libvirt_network_spec(desired_xml)
    structural_match = current_spec is not None and _libvirt_structural_spec(current_spec) == _libvirt_structural_spec(desired_spec)
    host_updates = (
        _planned_dhcp_host_updates(current_spec, desired_spec)
        if current_spec is not None
        else {"remove": [], "add": []}
    )
    hosts_match = not host_updates["remove"] and not host_updates["add"]

    _log_reconcile(
        "libvirt network xml comparison",
        network=network_name,
        current_exists=bool(current_xml),
        structural_match=structural_match,
        hosts_match=hosts_match,
        current_structural=_libvirt_structural_spec(current_spec) if current_spec is not None else None,
        desired_structural=_libvirt_structural_spec(desired_spec),
        current_hosts=(current_spec or {}).get("hosts", []),
        desired_hosts=desired_spec.get("hosts", []),
    )

    if not current_xml:
        return {
            "name": network_name,
            "action": "define",
            "status": "defined",
            "drift_detected": False,
            "desired_xml": desired_xml,
        }

    if structural_match and hosts_match:
        return {
            "name": network_name,
            "action": "none",
            "status": "unchanged",
            "drift_detected": False,
        }

    if structural_match:
        return {
            "name": network_name,
            "action": "update-hosts",
            "status": "updated-hosts",
            "drift_detected": True,
            "host_updates": host_updates,
        }

    attached_vms, active_attached_vms = _attached_domain_names(
        network_name,
        bridge_name=network_group.get("bridge_name"),
    )
    _log_reconcile(
        "libvirt network structural drift detected",
        network=network_name,
        allow_destructive=allow_destructive,
        attached_vms=attached_vms,
        active_attached_vms=active_attached_vms,
    )
    if active_attached_vms and not allow_destructive:
        raise NetworkReconcileSafetyError(network_name, attached_vms, active_attached_vms)

    return {
        "name": network_name,
        "action": "recreate",
        "status": "recreated",
        "drift_detected": True,
        "desired_xml": desired_xml,
        "attached_vms": attached_vms,
        "active_attached_vms": active_attached_vms,
    }


def validate_networking_changes(vm_records=None, allow_destructive=False):
    """Validate whether libvirt networking can converge safely without mutating state."""
    if vm_records is None:
        vm_records = configured_vm_records()

    network_groups = grouped_network_records(vm_records)
    plans = [
        plan_libvirt_network_update(group, group["vms"], allow_destructive=allow_destructive)
        for group in network_groups
    ]
    return {
        "network_groups": [group["id"] for group in network_groups],
        "libvirt_networks": plans,
    }


def _run_logged_network_command(command, network_name, check=True):
    _log_reconcile("executing libvirt network command", network=network_name, command=command[1])
    run(command, sudo=True, check=check)


def _run_logged_net_update(network_name, action, host_spec):
    _log_reconcile(
        "executing libvirt net-update",
        network=network_name,
        action=action,
        host=host_spec,
    )
    run(
        [
            "virsh",
            "net-update",
            network_name,
            action,
            "ip-dhcp-host",
            _build_dhcp_host_xml(host_spec),
            "--live",
            "--config",
        ],
        sudo=True,
    )


def _network_plan_summary(plan):
    summary = dict(plan)
    summary.pop("desired_xml", None)
    return summary


def ensure_libvirt_network(network_group, vm_records, allow_destructive=False):
    """Ensure one managed libvirt network matches the desired group state."""
    plan = plan_libvirt_network_update(
        network_group,
        vm_records,
        allow_destructive=allow_destructive,
    )
    network_name = plan["name"]

    if plan["action"] == "skip":
        return _network_plan_summary(plan)

    if plan["action"] == "none":
        ensure_libvirt_network_active(network_name, bridge_name=network_group.get("bridge_name"))
        return _network_plan_summary(plan)

    if plan["action"] == "update-hosts":
        ensure_libvirt_network_active(network_name, bridge_name=network_group.get("bridge_name"))
        for host_spec in plan["host_updates"]["remove"]:
            _run_logged_net_update(network_name, "delete", host_spec)
        for host_spec in plan["host_updates"]["add"]:
            _run_logged_net_update(network_name, "add-last", host_spec)
        return _network_plan_summary(plan)

    if plan["action"] == "recreate":
        _run_logged_network_command(["virsh", "net-destroy", network_name], network_name, check=False)
        _run_logged_network_command(["virsh", "net-undefine", network_name], network_name, check=False)

    if network_group.get("bridge_name") and bridge_interface_exists(network_group["bridge_name"]):
        cleanup_bridge_interface(network_group["bridge_name"])

    xml_path = Path("/tmp") / f"{network_name}.xml"
    xml_path.write_text(plan["desired_xml"], encoding="utf-8")
    _run_logged_network_command(["virsh", "net-define", str(xml_path)], network_name)
    ensure_libvirt_network_active(network_name, bridge_name=network_group.get("bridge_name"))
    return _network_plan_summary(plan)


def apply_nftables_plan(plan):
    """Apply the desired managed nftables tables."""

    apply_result = apply_managed_nftables_ruleset(plan)
    verify_result = verify_managed_nftables_tables()
    return {
        "apply": apply_result,
        "verify": verify_result,
    }


def reconcile_networking(
    policy_only=False,
    allow_destructive=False,
):
    """Reconcile networking state from saved configs and current VM state."""

    global_config = load_global_config()
    vm_records = configured_vm_records()
    return reconcile_networking_records(
        vm_records,
        policy_only=policy_only,
        allow_destructive=allow_destructive,
        global_config=global_config,
    )


def reconcile_networking_records(
    vm_records,
    policy_only=False,
    allow_destructive=False,
    global_config=None,
    network_groups=None,
):
    """Reconcile networking state from externally supplied VM records."""

    if global_config is None:
        global_config = load_global_config()

    if network_groups is None:
        network_groups = grouped_network_records(vm_records)
    else:
        # Use authoritative network_groups data from database
        grouped_records = {
            group["id"]: {**group, "vms": []}
            for group in network_groups
        }
        for record in vm_records:
            network_group_id = record["network_group_id"]
            if network_group_id not in grouped_records:
                # Network group not found in database - this indicates a data consistency issue
                # Log warning and skip this VM or use fallback data
                print(f"WARNING: VM {record['vm_name']} references unknown network_group_id: {network_group_id}")
                # Create fallback entry using VM record data (may be stale)
                grouped_records[network_group_id] = {
                    "id": network_group_id,
                    "owner_user_id": record["owner_user_id"],
                    "name": record["network_group_name"],
                    "profile": record["profile"],
                    "libvirt_network_name": record["libvirt_network_name"],
                    "bridge_name": record["bridge_name"],
                    "subnet_cidr": record["subnet_cidr"],
                    "gateway_ip": record["gateway_ip"],
                    "dhcp_start": record["dhcp_start"],
                    "dhcp_end": record["dhcp_end"],
                    "vms": [],
                }
            # Always use the authoritative network_groups data, only append VM to vms list
            grouped_records[network_group_id]["vms"].append(record)
        network_groups = list(grouped_records.values())
    network_results = []

    _log_reconcile(
        "starting reconcile",
        policy_only=policy_only,
        allow_destructive=allow_destructive,
        network_groups=[group["id"] for group in network_groups],
    )

    if not policy_only:
        for group in network_groups:
            network_results.append(
                ensure_libvirt_network(
                    group,
                    group["vms"],
                    allow_destructive=allow_destructive,
                )
            )

    live_vm_records = [record for record in vm_records if record["state_exists"]]
    plan = build_nftables_plan(network_groups, live_vm_records, global_config=global_config)
    backend_result = apply_nftables_plan(plan)
    forward_port_summary = plan["nat_rules"]["prerouting"]
    managed_interfaces = sorted(
        {
            group["bridge_name"]
            for group in network_groups
            if group.get("bridge_name") and group.get("profile") != "bridged"
        }
    )

    _log_reconcile(
        "completed reconcile",
        policy_only=policy_only,
        managed_interfaces=managed_interfaces,
        forward_ports=forward_port_summary,
        libvirt_networks=network_results,
    )
    return {
        "backend": "nftables",
        "policy_only": policy_only,
        "network_groups": [group["id"] for group in network_groups],
        "libvirt_networks": network_results,
        "managed_interfaces": managed_interfaces,
        "forward_ports": forward_port_summary,
        "nftables": backend_result,
    }
