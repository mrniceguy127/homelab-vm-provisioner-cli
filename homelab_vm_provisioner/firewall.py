"""Firewalld helpers for VM NAT policy management."""

import time

from .constants import BLOCKED_PRIVATE_RANGES
from .system import capture, capture_or_none, run, tool_exists


def forward_port_spec(port, vm_ip):
    """Build a firewalld forward-port specification string.

    Args:
        port: Port mapping dictionary.
        vm_ip: Destination VM IP address.

    Returns:
        str: Forward-port specification accepted by ``firewall-cmd``.
    """
    return (
        f"port={port['host']}:proto={port.get('proto', 'tcp')}:"
        f"toaddr={vm_ip}:toport={port['guest']}"
    )


def direct_forward_rule_args(port, vm_ip):
    """Build a firewalld direct FORWARD accept rule spec.

    Args:
        port: Port mapping dictionary.
        vm_ip: Destination VM IP address.

    Returns:
        list[str]: Rule arguments accepted by ``firewall-cmd --direct``.
    """
    return [
        "ipv4",
        "filter",
        "FORWARD",
        "-1000",
        "-p",
        port.get("proto", "tcp"),
        "-d",
        vm_ip,
        "--dport",
        str(port["guest"]),
        "-j",
        "ACCEPT",
    ]


def nft_chain_location(chain_name, ruleset_text=None):
    """Return the nft table location for a chain.

    Args:
        chain_name: nft chain name.
        ruleset_text: Optional pre-fetched ``nft list ruleset`` text.

    Returns:
        dict | None: Mapping with ``family``, ``table``, and ``chain`` keys,
        or ``None`` when the chain is absent.
    """
    if ruleset_text is None:
        ruleset_text = capture_or_none(["nft", "list", "ruleset"], sudo=True)
    if not ruleset_text:
        return None

    current_family = None
    current_table = None
    chain_prefix = f"chain {chain_name} "

    for raw_line in ruleset_text.splitlines():
        line = raw_line.strip()

        if line.startswith("table "):
            fields = line.replace("{", " ").split()
            if len(fields) >= 3:
                current_family = fields[1]
                current_table = fields[2]
            else:
                current_family = None
                current_table = None
            continue

        if current_family is None or current_table is None:
            continue

        if line.startswith(chain_prefix):
            return {
                "family": current_family,
                "table": current_table,
                "chain": chain_name,
            }

    return None


def nft_forward_rule_args(chain_location, bridge_if, port, vm_ip):
    """Build an nft ``LIBVIRT_FWI`` accept rule spec.

    Args:
        chain_location: Mapping returned by :func:`nft_chain_location`.
        bridge_if: Outbound bridge interface name.
        port: Port mapping dictionary.
        vm_ip: Destination VM IP address.

    Returns:
        list[str]: Rule arguments accepted by ``nft insert rule`` after ``nft``.
    """
    return [
        chain_location["family"],
        chain_location["table"],
        chain_location["chain"],
        "handle",
        chain_location["handle"],
        "oifname",
        bridge_if,
        "ip",
        "daddr",
        vm_ip,
        port.get("proto", "tcp"),
        "dport",
        str(port["guest"]),
        "accept",
    ]


def direct_forward_ports(ports):
    """Return the guest ports that need direct FORWARD accept rules.

    Args:
        ports: Configured host-to-guest port forwarding rules.

    Returns:
        list[dict]: Unique guest port/protocol mappings.
    """
    direct_ports = []
    seen = set()

    for port in ports:
        proto = port.get("proto", "tcp")
        guest = str(port["guest"])
        key = (proto, guest)
        if key in seen:
            continue

        seen.add(key)
        direct_ports.append({"guest": guest, "proto": proto})

    return direct_ports


def bridge_interface_for_vm_ip(vm_ip):
    """Return the bridge interface that routes traffic to a VM IP.

    Args:
        vm_ip: VM IP address.

    Returns:
        str | None: Linux interface name, or ``None`` when it cannot be
        determined.
    """
    route_text = capture_or_none(["ip", "route", "get", vm_ip])
    if not route_text:
        return None

    fields = route_text.split()
    for index, field in enumerate(fields[:-1]):
        if field == "dev":
            return fields[index + 1]

    return None


def wait_for_bridge_interface(vm_ip, attempts=20, delay_seconds=0.25):
    """Wait for the host to learn the bridge interface for a VM IP.

    Args:
        vm_ip: VM IP address.
        attempts: Number of polling attempts.
        delay_seconds: Delay between attempts.

    Returns:
        str | None: Bridge interface name when found.
    """
    for _ in range(attempts):
        bridge_if = bridge_interface_for_vm_ip(vm_ip)
        if bridge_if is not None:
            return bridge_if
        time.sleep(delay_seconds)

    return None


def nft_chain_exists(chain_name):
    """Return whether an nft chain exists.

    Args:
        chain_name: nft chain name.

    Returns:
        bool: ``True`` when the chain can be listed.
    """
    return nft_chain_location(chain_name) is not None


def wait_for_nft_chain(chain_name, attempts=20, delay_seconds=0.25):
    """Wait for an nft chain to appear.

    Args:
        chain_name: nft chain name.
        attempts: Number of polling attempts.
        delay_seconds: Delay between attempts.

    Returns:
        dict | None: Chain location mapping when the chain exists before timeout.
    """
    for _ in range(attempts):
        chain_location = nft_chain_location(chain_name)
        if chain_location is not None:
            return chain_location
        time.sleep(delay_seconds)

    return None


def nft_rule_handle(rule_line):
    """Extract an nft handle value from a rule listing line.

    Args:
        rule_line: Raw rule line containing ``# handle``.

    Returns:
        str | None: Handle value when present.
    """
    if "# handle " not in rule_line:
        return None

    handle = rule_line.rsplit("# handle ", 1)[-1].strip()
    return handle or None


def list_nft_chain_rules(chain_location):
    """List rule lines from an nft chain.

    Args:
        chain_location: Mapping returned by :func:`nft_chain_location`.

    Returns:
        list[str]: Raw nft rule lines that include handles.
    """
    output = capture_or_none(
        [
            "nft",
            "-a",
            "list",
            "chain",
            chain_location["family"],
            chain_location["table"],
            chain_location["chain"],
        ],
        sudo=True,
    )
    if not output:
        return []

    return [line.strip() for line in output.splitlines() if "# handle " in line]


def find_nft_bridge_reject_handle(chain_location, bridge_if):
    """Find the reject rule handle for a bridge inside ``LIBVIRT_FWI``.

    Args:
        chain_location: Mapping returned by :func:`nft_chain_location`.
        bridge_if: Outbound bridge interface name.

    Returns:
        str | None: Handle value for the bridge reject rule.
    """
    quoted_bridge = f'oifname "{bridge_if}"'
    bare_bridge = f"oifname {bridge_if}"

    for line in list_nft_chain_rules(chain_location):
        if quoted_bridge not in line and bare_bridge not in line:
            continue
        if "reject" not in line:
            continue

        handle = nft_rule_handle(line)
        if handle is not None:
            return handle

    return None


def wait_for_nft_bridge_reject_handle(chain_location, bridge_if, attempts=20, delay_seconds=0.25):
    """Wait for the bridge reject rule handle to appear.

    Args:
        chain_location: Mapping returned by :func:`nft_chain_location`.
        bridge_if: Outbound bridge interface name.
        attempts: Number of polling attempts.
        delay_seconds: Delay between attempts.

    Returns:
        str | None: Handle value when found before timeout.
    """
    for _ in range(attempts):
        handle = find_nft_bridge_reject_handle(chain_location, bridge_if)
        if handle is not None:
            return handle
        time.sleep(delay_seconds)

    return None


def insert_nft_forward_rule(bridge_if, port, vm_ip):
    """Insert an allow rule into ``LIBVIRT_FWI`` for one guest port.

    Args:
        bridge_if: Outbound bridge interface name.
        port: Port mapping dictionary.
        vm_ip: Destination VM IP address.

    Returns:
        bool: ``True`` when the chain existed and the rule insertion was attempted.
    """
    chain_location = wait_for_nft_chain("LIBVIRT_FWI", attempts=60, delay_seconds=0.5)
    if chain_location is None:
        return False

    reject_handle = wait_for_nft_bridge_reject_handle(
        chain_location,
        bridge_if,
        attempts=60,
        delay_seconds=0.5,
    )
    if reject_handle is None:
        return False

    chain_location = {**chain_location, "handle": reject_handle}

    run(
        ["nft", "insert", "rule", *nft_forward_rule_args(chain_location, bridge_if, port, vm_ip)],
        sudo=True,
        check=False,
    )
    return True


def apply_firewalld_nat_policy(network, trust, ports):
    """Apply host firewalld policy for a NAT-backed VM.

    Args:
        network: NAT network settings.
        trust: Trust level from the VM config.
        ports: Host-to-guest port forwarding rules.

    Returns:
        bool: ``True`` when the VM-specific zone had to be created.
    """
    zone = network["zone"]
    cidr = network["cidr"]
    vm_ip = network["vm_ip"]

    existing_zones = capture(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    zone_created = zone not in existing_zones.split()
    if zone_created:
        run(["firewall-cmd", "--permanent", "--new-zone", zone], sudo=True)

    run(["firewall-cmd", "--permanent", "--zone", zone, "--set-target", "ACCEPT"], sudo=True)
    run(["firewall-cmd", "--permanent", "--zone", zone, "--add-source", cidr], sudo=True)

    if trust == "untrusted":
        for blocked_range in BLOCKED_PRIVATE_RANGES:
            run(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    zone,
                    "--add-rich-rule",
                    f'rule family="ipv4" destination address="{blocked_range}" reject',
                ],
                sudo=True,
                check=False,
            )

    for port in ports:
        run(
            [
                "firewall-cmd",
                "--permanent",
                f"--add-forward-port={forward_port_spec(port, vm_ip)}",
            ],
            sudo=True,
        )

    direct_ports = direct_forward_ports(ports)
    for port in direct_ports:
        run(
            [
                "firewall-cmd",
                "--permanent",
                "--direct",
                "--add-rule",
                *direct_forward_rule_args(port, vm_ip),
            ],
            sudo=True,
        )

    run(["firewall-cmd", "--reload"], sudo=True)

    if not direct_ports:
        return zone_created

    bridge_if = wait_for_bridge_interface(vm_ip)
    if bridge_if is None:
        return zone_created

    for port in direct_ports:
        insert_nft_forward_rule(bridge_if, port, vm_ip)

    return zone_created


def firewalld_zone_exists(zone):
    """Return whether a firewalld zone exists.

    Args:
        zone: Zone name.

    Returns:
        bool: ``True`` when the zone exists.
    """
    zones = capture_or_none(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    return bool(zones and zone in zones.split())


def firewalld_zone_for_cidr(cidr, preferred_zone=None):
    """Find the zone that owns a CIDR source.

    Args:
        cidr: Source CIDR to locate.
        preferred_zone: Zone to check first when provided.

    Returns:
        str | None: Matching zone name, or ``None`` when no zone contains the
        source.
    """
    zones = capture_or_none(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    if not zones:
        return None

    candidates = zones.split()
    if preferred_zone and preferred_zone in candidates:
        candidates = [preferred_zone] + [zone for zone in candidates if zone != preferred_zone]

    for zone in candidates:
        sources = capture_or_none(
            ["firewall-cmd", "--permanent", "--zone", zone, "--list-sources"],
            sudo=True,
        )
        if sources and cidr in sources.split():
            return zone

    return None


def list_zone_forward_ports(zone=None):
    """List forward-port rules for a zone.

    Args:
        zone: Optional zone name. When omitted, list top-level permanent rules.

    Returns:
        list[str]: Forward-port specifications.
    """
    cmd = ["firewall-cmd", "--permanent"]
    if zone is not None:
        cmd.extend(["--zone", zone])
    cmd.append("--list-forward-ports")

    output = capture_or_none(cmd, sudo=True)
    return output.split() if output else []


def find_forward_port_rules_for_vm(vm_ip):
    """Find forward-port rules that target a specific VM IP.

    Args:
        vm_ip: VM IP address.

    Returns:
        list[tuple[str | None, str]]: Zone/spec pairs for matching rules.
    """
    rules = []
    seen = set()

    zones = capture_or_none(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    zone_names = zones.split() if zones else []

    for zone in [None] + zone_names:
        for spec in list_zone_forward_ports(zone):
            if f"toaddr={vm_ip}" not in spec:
                continue

            key = (zone, spec)
            if key in seen:
                continue

            seen.add(key)
            rules.append(key)

    return rules


def remove_forward_port_rule(spec, zone=None):
    """Remove a forward-port rule from firewalld.

    Args:
        spec: Forward-port specification.
        zone: Optional zone name.
    """
    cmd = ["firewall-cmd", "--permanent"]
    if zone is not None:
        cmd.extend(["--zone", zone])
    cmd.append(f"--remove-forward-port={spec}")
    run(cmd, sudo=True, check=False)


def list_direct_rules():
    """List permanent firewalld direct rules.

    Returns:
        list[list[str]]: Direct rules split into argument lists.
    """
    output = capture_or_none(
        ["firewall-cmd", "--permanent", "--direct", "--get-all-rules"],
        sudo=True,
    )
    if not output:
        return []

    return [line.split() for line in output.splitlines() if line.strip()]


def find_direct_forward_rules_for_vm(vm_ip):
    """Find firewalld direct FORWARD accept rules that target a VM IP.

    Args:
        vm_ip: VM IP address.

    Returns:
        list[list[str]]: Matching firewalld direct rule argument lists.
    """
    rules = []
    for rule in list_direct_rules():
        if len(rule) < 4:
            continue
        if rule[:4] != ["ipv4", "filter", "FORWARD", "-1000"]:
            continue
        if "-d" not in rule:
            continue
        dest_index = rule.index("-d") + 1
        if dest_index >= len(rule) or rule[dest_index] != vm_ip:
            continue
        rules.append(rule)

    return rules


def remove_direct_rule(rule_args):
    """Remove a permanent firewalld direct rule.

    Args:
        rule_args: Firewalld direct rule argument list.
    """
    run(
        ["firewall-cmd", "--permanent", "--direct", "--remove-rule", *rule_args],
        sudo=True,
        check=False,
    )


def list_nft_forward_rules():
    """List nft rules from ``LIBVIRT_FWI``.

    Returns:
        list[str]: Raw nft rule lines.
    """
    chain_location = nft_chain_location("LIBVIRT_FWI")
    if chain_location is None:
        return []

    return list_nft_chain_rules(chain_location)


def find_nft_forward_rule_handles_for_vm(vm_ip):
    """Find nft rule handles in ``LIBVIRT_FWI`` that target a VM IP.

    Args:
        vm_ip: VM IP address.

    Returns:
        list[str]: Matching nft rule handles.
    """
    handles = []
    for line in list_nft_forward_rules():
        if f"ip daddr {vm_ip}" not in line:
            continue
        handle = nft_rule_handle(line)
        if handle:
            handles.append(handle)

    return handles


def remove_nft_forward_rule(handle):
    """Remove an nft ``LIBVIRT_FWI`` rule by handle.

    Args:
        handle: nft rule handle.
    """
    chain_location = nft_chain_location("LIBVIRT_FWI")
    if chain_location is None:
        return

    run(
        [
            "nft",
            "delete",
            "rule",
            chain_location["family"],
            chain_location["table"],
            chain_location["chain"],
            "handle",
            handle,
        ],
        sudo=True,
        check=False,
    )


def firewalld_zone_is_empty(zone):
    """Return whether a firewalld zone has no remaining configured rules.

    Args:
        zone: Zone name.

    Returns:
        bool: ``True`` when the zone is empty.
    """
    checks = [
        "--list-sources",
        "--list-interfaces",
        "--list-services",
        "--list-ports",
        "--list-protocols",
        "--list-forward-ports",
        "--list-source-ports",
        "--list-icmp-blocks",
        "--list-rich-rules",
    ]

    for check in checks:
        value = capture_or_none(["firewall-cmd", "--permanent", "--zone", zone, check], sudo=True)
        if value is None or value.strip():
            return False

    return True


def cleanup_firewalld_vm_policy(vm_name, network, ports):
    """Remove VM-specific firewalld state.

    Args:
        vm_name: VM name.
        network: Stored or discovered network settings.
        ports: Stored port forwarding rules.
    """
    if not tool_exists("firewall-cmd"):
        return

    cleanup_attempted = False
    vm_ip = network.get("vm_ip")
    cidr = network.get("cidr")
    preferred_zone = network.get("zone") or f"{vm_name}-zone"

    zone = None
    if preferred_zone and firewalld_zone_exists(preferred_zone):
        zone = preferred_zone
    elif cidr:
        zone = firewalld_zone_for_cidr(cidr, preferred_zone=preferred_zone)

    direct_rules = find_direct_forward_rules_for_vm(vm_ip) if vm_ip else []
    for rule in direct_rules:
        remove_direct_rule(rule)
        cleanup_attempted = True

    if not direct_rules and vm_ip:
        for port in direct_forward_ports(ports):
            remove_direct_rule(direct_forward_rule_args(port, vm_ip))
            cleanup_attempted = True

    nft_handles = find_nft_forward_rule_handles_for_vm(vm_ip) if vm_ip else []
    for handle in nft_handles:
        remove_nft_forward_rule(handle)
        cleanup_attempted = True

    rules = find_forward_port_rules_for_vm(vm_ip) if vm_ip else []
    for rule_zone, spec in rules:
        remove_forward_port_rule(spec, zone=rule_zone)
        cleanup_attempted = True

    if not rules and vm_ip:
        for port in ports:
            remove_forward_port_rule(forward_port_spec(port, vm_ip))
            cleanup_attempted = True

    if zone:
        if cidr:
            run(
                ["firewall-cmd", "--permanent", "--zone", zone, "--remove-source", cidr],
                sudo=True,
                check=False,
            )
            cleanup_attempted = True

        for blocked_range in BLOCKED_PRIVATE_RANGES:
            run(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    zone,
                    "--remove-rich-rule",
                    f'rule family="ipv4" destination address="{blocked_range}" reject',
                ],
                sudo=True,
                check=False,
            )
            cleanup_attempted = True

        if firewalld_zone_is_empty(zone):
            run(["firewall-cmd", "--permanent", "--delete-zone", zone], sudo=True, check=False)
            cleanup_attempted = True

    if cleanup_attempted:
        run(["firewall-cmd", "--reload"], sudo=True, check=False)
