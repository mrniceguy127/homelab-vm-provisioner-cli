#!/usr/bin/env python3

import argparse
import ipaddress
import random
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader


PROJECT_DIR = Path(__file__).resolve().parent

PROVIDER_USER = "vmadmin"
PROVIDER_KEY_DIR = PROJECT_DIR / "provider-keys"
BUILD_DIR = PROJECT_DIR / ".build"

IMG_DIR = Path("/var/lib/libvirt/images")
BASE_IMG_NAME = "debian-12-generic-amd64.qcow2"
BASE_IMG_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
OS_VARIANT = "debian12"

BLOCKED_PRIVATE_RANGES = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "169.254.0.0/16",
]


def tool_exists(tool):
    result = subprocess.run(
        ["which", tool],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def run(cmd, sudo=False, check=True):
    if sudo:
        cmd = ["sudo"] + cmd

    print("+", " ".join(str(x) for x in cmd))
    return subprocess.run(cmd, check=check, text=True)


def capture(cmd, sudo=False):
    if sudo:
        cmd = ["sudo"] + cmd

    return subprocess.check_output(cmd, text=True).strip()


def capture_or_none(cmd, sudo=False):
    try:
        return capture(cmd, sudo=sudo)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def require_tools(tools=None):
    if tools is None:
        tools = [
            "virsh",
            "virt-install",
            "qemu-img",
            "cloud-localds",
            "firewall-cmd",
            "ssh-keygen",
            "wget",
        ]

    missing = []

    for tool in tools:
        if not tool_exists(tool):
            missing.append(tool)

    if missing:
        print("Missing tools:", ", ".join(missing))
        print("Install with:")
        print(
            "sudo apt install -y libvirt-daemon-system virtinst qemu-utils "
            "cloud-image-utils firewalld wget openssh-client python3-yaml python3-jinja2"
        )
        sys.exit(1)


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_dir_for_vm(vm_name):
    return BUILD_DIR / vm_name


def state_file_for_vm(vm_name):
    return build_dir_for_vm(vm_name) / "state.yaml"


def save_vm_state(vm_name, state):
    build_dir = build_dir_for_vm(vm_name)
    build_dir.mkdir(parents=True, exist_ok=True)

    with open(state_file_for_vm(vm_name), "w", encoding="utf-8") as f:
        yaml.safe_dump(state, f, sort_keys=False)


def load_vm_state(vm_name):
    state_path = state_file_for_vm(vm_name)
    if not state_path.exists():
        return {}

    with open(state_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_config_path(config_path):
    raw_path = Path(config_path).expanduser()

    candidates = [raw_path]

    if not raw_path.suffix:
        candidates.append(raw_path.with_suffix(".yaml"))
        candidates.append(raw_path.with_suffix(".yml"))

    if raw_path.parts and raw_path.parts[0] == "config":
        alt_path = Path("configs", *raw_path.parts[1:])
        candidates.append(alt_path)
        if not alt_path.suffix:
            candidates.append(alt_path.with_suffix(".yaml"))
            candidates.append(alt_path.with_suffix(".yml"))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Missing config file: {config_path}")


def random_mac():
    return "52:54:00:%02x:%02x:%02x" % (
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )


def get_existing_routes_text():
    result = subprocess.run(
        ["ip", "route"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout


def get_existing_virsh_networks_text():
    result = subprocess.run(
        ["sudo", "virsh", "net-list", "--all", "--name"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    xml = ""

    for net in result.stdout.splitlines():
        net = net.strip()
        if not net:
            continue

        xml_result = subprocess.run(
            ["sudo", "virsh", "net-dumpxml", net],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        xml += xml_result.stdout + "\n"

    return xml


def list_virsh_network_names():
    result = subprocess.run(
        ["sudo", "virsh", "net-list", "--all", "--name"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def subnet_appears_used(prefix):
    haystack = get_existing_routes_text() + "\n" + get_existing_virsh_networks_text()
    return prefix in haystack


def pick_free_subnet():
    for third_octet in range(100, 251):
        prefix = f"192.168.{third_octet}"
        if not subnet_appears_used(prefix + "."):
            return {
                "prefix": prefix,
                "cidr": f"{prefix}.0/24",
                "gateway": f"{prefix}.1",
                "vm_ip": f"{prefix}.50",
                "dhcp_start": f"{prefix}.50",
                "dhcp_end": f"{prefix}.99",
            }

    raise RuntimeError("Could not find free 192.168.X.0/24 subnet")


def parse_network_from_xml(xml_text, vm_name):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    host = root.find(f".//dhcp/host[@name='{vm_name}']")
    if host is None:
        return None

    name = root.findtext("name")
    ip_node = root.find("ip")
    if ip_node is None:
        return None

    gateway = ip_node.get("address")
    netmask = ip_node.get("netmask")
    vm_ip = host.get("ip")
    mac = host.get("mac")

    if not (name and gateway and netmask and vm_ip):
        return None

    cidr = str(ipaddress.ip_network(f"{gateway}/{netmask}", strict=False))

    return {
        "mode": "nat",
        "name": name,
        "gateway": gateway,
        "cidr": cidr,
        "vm_ip": vm_ip,
        "mac": mac,
    }


def discover_vm_network(vm_name):
    for net_name in list_virsh_network_names():
        xml_text = capture_or_none(["virsh", "net-dumpxml", net_name], sudo=True)
        if not xml_text:
            continue

        network = parse_network_from_xml(xml_text, vm_name)
        if network:
            return network

    return None


def provider_private_key_path(vm_name):
    return PROVIDER_KEY_DIR / f"{vm_name}_provider_ed25519"


def provider_keypair(vm_name):
    PROVIDER_KEY_DIR.mkdir(mode=0o700, exist_ok=True)

    key_path = provider_private_key_path(vm_name)
    pub_path = Path(str(key_path) + ".pub")

    if not key_path.exists():
        run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(key_path),
                "-N",
                "",
                "-C",
                f"provider-{vm_name}",
            ]
        )

    key_path.chmod(0o600)
    pub_path.chmod(0o644)

    return key_path, pub_path.read_text(encoding="utf-8").strip()


def parse_ipv4_from_domifaddr(text):
    for line in text.splitlines():
        if "ipv4" not in line.lower():
            continue

        fields = line.split()
        if len(fields) < 4:
            continue

        try:
            address = ipaddress.ip_interface(fields[3]).ip
        except ValueError:
            continue

        if address.version == 4:
            return str(address)

    return None


def resolve_vm_ipv4(vm_name):
    for source in ("lease", "agent", "arp"):
        result = subprocess.run(
            ["sudo", "virsh", "domifaddr", vm_name, "--source", source],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        if result.returncode != 0:
            continue

        address = parse_ipv4_from_domifaddr(result.stdout)
        if address:
            return address, source

    return None, None


def render_templates(context, template_name):
    templates_dir = PROJECT_DIR / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    user_data = env.get_template(f"{template_name}-user-data.yaml.j2").render(**context)
    meta_data = env.get_template("meta-data.yaml.j2").render(**context)

    build_dir = build_dir_for_vm(context["vm_name"])
    build_dir.mkdir(parents=True, exist_ok=True)

    user_data_path = build_dir / "user-data"
    meta_data_path = build_dir / "meta-data"

    user_data_path.write_text(user_data, encoding="utf-8")
    meta_data_path.write_text(meta_data, encoding="utf-8")

    return user_data_path, meta_data_path


def ensure_base_image():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    base_img = IMG_DIR / BASE_IMG_NAME

    if not base_img.exists():
        run(["wget", "-O", str(base_img), BASE_IMG_URL], sudo=True)

    return base_img


def create_vm_disk(vm_name, disk_gb, base_img):
    vm_disk = IMG_DIR / f"{vm_name}.qcow2"

    if not vm_disk.exists():
        run(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-F",
                "qcow2",
                "-b",
                str(base_img),
                str(vm_disk),
                f"{disk_gb}G",
            ],
            sudo=True,
        )

    return vm_disk


def create_seed_iso(vm_name, user_data_path, meta_data_path):
    seed_iso = IMG_DIR / f"{vm_name}-seed.iso"

    run(
        [
            "cloud-localds",
            str(seed_iso),
            str(user_data_path),
            str(meta_data_path),
        ],
        sudo=True,
    )

    return seed_iso


def create_nat_network(vm_name, network):
    net_name = network["name"]

    bridge_name = network.get("bridge_name", f"virbr-{vm_name[:6]}")

    xml = f"""
<network>
  <name>{net_name}</name>
  <forward mode='nat'/>
  <bridge name='{bridge_name}' stp='on' delay='0'/>
  <ip address='{network["gateway"]}' netmask='255.255.255.0'>
    <dhcp>
      <host mac='{network["mac"]}' name='{vm_name}' ip='{network["vm_ip"]}'/>
      <range start='{network["dhcp_start"]}' end='{network["dhcp_end"]}'/>
    </dhcp>
  </ip>
</network>
""".strip()

    xml_path = Path("/tmp") / f"{net_name}.xml"
    xml_path.write_text(xml, encoding="utf-8")

    result = subprocess.run(
        ["sudo", "virsh", "net-info", net_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        run(["virsh", "net-define", str(xml_path)], sudo=True)
        run(["virsh", "net-autostart", net_name], sudo=True)
        run(["virsh", "net-start", net_name], sudo=True)


def vm_exists(vm_name):
    result = subprocess.run(
        ["sudo", "virsh", "dominfo", vm_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def virt_install(vm_name, vm, network_arg, vm_disk, seed_iso):
    if vm_exists(vm_name):
        print(f"VM already exists: {vm_name}")
        return

    run(
        [
            "virt-install",
            "--name",
            vm_name,
            "--memory",
            str(vm["ram_mb"]),
            "--vcpus",
            str(vm["vcpus"]),
            "--disk",
            f"path={vm_disk},format=qcow2,bus=virtio",
            "--disk",
            f"path={seed_iso},device=cdrom",
            "--os-variant",
            OS_VARIANT,
            "--network",
            network_arg,
            "--graphics",
            "none",
            "--import",
            "--noautoconsole",
        ],
        sudo=True,
    )


def apply_firewalld_nat_policy(network, trust, ports):
    zone = network["zone"]
    cidr = network["cidr"]
    vm_ip = network["vm_ip"]

    existing_zones = capture(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    zone_created = zone not in existing_zones.split()

    if zone_created:
        run(["firewall-cmd", "--permanent", "--new-zone", zone], sudo=True)

    run(["firewall-cmd", "--permanent", "--zone", zone, "--add-source", cidr], sudo=True)

    if trust == "untrusted":
        for rng in BLOCKED_PRIVATE_RANGES:
            run(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    zone,
                    "--add-rich-rule",
                    f'rule family="ipv4" destination address="{rng}" reject',
                ],
                sudo=True,
                check=False,
            )

    for port in ports:
        host_port = str(port["host"])
        guest_port = str(port["guest"])
        proto = port.get("proto", "tcp")

        run(
            [
                "firewall-cmd",
                "--permanent",
                f"--add-forward-port=port={host_port}:proto={proto}:toaddr={vm_ip}:toport={guest_port}",
            ],
            sudo=True,
        )

    run(["firewall-cmd", "--reload"], sudo=True)
    return zone_created


def firewalld_zone_exists(zone):
    zones = capture_or_none(["firewall-cmd", "--permanent", "--get-zones"], sudo=True)
    if not zones:
        return False

    return zone in zones.split()


def firewalld_zone_for_cidr(cidr, preferred_zone=None):
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
        if not sources:
            continue

        if cidr in sources.split():
            return zone

    return None


def list_zone_forward_ports(zone=None):
    cmd = ["firewall-cmd", "--permanent"]
    if zone is not None:
        cmd.extend(["--zone", zone])
    cmd.append("--list-forward-ports")

    output = capture_or_none(cmd, sudo=True)
    if not output:
        return []

    return output.split()


def find_forward_port_rules_for_vm(vm_ip):
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
    cmd = ["firewall-cmd", "--permanent"]
    if zone is not None:
        cmd.extend(["--zone", zone])
    cmd.append(f"--remove-forward-port={spec}")
    run(cmd, sudo=True, check=False)


def firewalld_zone_is_empty(zone):
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
        if value is None:
            return False
        if value.strip():
            return False

    return True


def cleanup_firewalld_vm_policy(vm_name, network, ports):
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

    rules = find_forward_port_rules_for_vm(vm_ip) if vm_ip else []
    for rule_zone, spec in rules:
        remove_forward_port_rule(spec, zone=rule_zone)
        cleanup_attempted = True

    if not rules and vm_ip:
        for port in ports:
            spec = (
                f"port={port['host']}:proto={port.get('proto', 'tcp')}:"
                f"toaddr={vm_ip}:toport={port['guest']}"
            )
            remove_forward_port_rule(spec)
            cleanup_attempted = True

    if zone:
        if cidr:
            run(
                ["firewall-cmd", "--permanent", "--zone", zone, "--remove-source", cidr],
                sudo=True,
                check=False,
            )
            cleanup_attempted = True

        for rng in BLOCKED_PRIVATE_RANGES:
            run(
                [
                    "firewall-cmd",
                    "--permanent",
                    "--zone",
                    zone,
                    "--remove-rich-rule",
                    f'rule family="ipv4" destination address="{rng}" reject',
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


def cleanup_local_vm_artifacts(vm_name, provider_private_key=None):
    if provider_private_key is None:
        provider_private_key = provider_private_key_path(vm_name)

    key_path = Path(provider_private_key)
    pub_path = Path(str(key_path) + ".pub")

    for path in (key_path, pub_path):
        if path.exists():
            path.unlink()

    build_dir = build_dir_for_vm(vm_name)
    if build_dir.exists():
        shutil.rmtree(build_dir)


def cleanup_vm_storage(vm_name):
    for path in (IMG_DIR / f"{vm_name}.qcow2", IMG_DIR / f"{vm_name}-seed.iso"):
        run(["rm", "-f", str(path)], sudo=True, check=False)


def create(config_path):
    require_tools()

    config = load_config(resolve_config_path(config_path))

    vm = config["vm"]
    net_cfg = config.get("network", {})
    packages = config.get("packages", [])
    ports = config.get("ports", [])

    vm_name = vm["name"]
    vm_user = vm["user"]
    vm_ssh_key_file = Path(vm["ssh_key_file"]).expanduser()
    allow_sudo = bool(vm.get("allow_sudo", False))
    trust = vm.get("trust", "untrusted")
    template = vm.get("template", "base")

    if trust not in ("trusted", "untrusted"):
        raise ValueError("vm.trust must be trusted or untrusted")

    if not vm_ssh_key_file.exists():
        raise FileNotFoundError(f"Missing VM SSH key file: {vm_ssh_key_file}")

    provider_private_key, provider_public_key = provider_keypair(vm_name)
    vm_public_key = vm_ssh_key_file.read_text(encoding="utf-8").strip()

    mode = net_cfg.get("mode", "nat-auto")
    mac = net_cfg.get("mac", random_mac())

    network = {
        "mode": mode,
        "mac": mac,
    }

    if mode == "nat-auto":
        auto = pick_free_subnet()
        network.update(auto)
        network["name"] = net_cfg.get("name", f"{vm_name}-net")
        network["zone"] = net_cfg.get("zone", f"{vm_name}-zone")

    elif mode == "nat-custom":
        prefix = net_cfg.get("subnet_prefix")

        if prefix:
            network["prefix"] = prefix
            network["cidr"] = net_cfg.get("cidr", f"{prefix}.0/24")
            network["gateway"] = net_cfg.get("gateway", f"{prefix}.1")
            network["vm_ip"] = net_cfg.get("vm_ip", f"{prefix}.50")
            network["dhcp_start"] = net_cfg.get("dhcp_start", f"{prefix}.50")
            network["dhcp_end"] = net_cfg.get("dhcp_end", f"{prefix}.99")
        else:
            required = ["cidr", "gateway", "vm_ip", "dhcp_start", "dhcp_end"]
            missing = [x for x in required if x not in net_cfg]
            if missing:
                raise ValueError(f"Missing nat-custom network fields: {missing}")

            network["cidr"] = net_cfg["cidr"]
            network["gateway"] = net_cfg["gateway"]
            network["vm_ip"] = net_cfg["vm_ip"]
            network["dhcp_start"] = net_cfg["dhcp_start"]
            network["dhcp_end"] = net_cfg["dhcp_end"]

        network["name"] = net_cfg.get("name", f"{vm_name}-net")
        network["zone"] = net_cfg.get("zone", f"{vm_name}-zone")

    elif mode == "bridge":
        network["bridge_name"] = net_cfg.get("bridge_name", "br0")
        network["vm_ip"] = net_cfg.get("vm_ip", "dhcp-from-router")
        network["cidr"] = net_cfg.get("cidr", "main-lan")

    else:
        raise ValueError("network.mode must be nat-auto, nat-custom, or bridge")

    if allow_sudo:
        vm_sudo = "ALL=(ALL) NOPASSWD:ALL"
    else:
        vm_sudo = "false"

    context = {
        "vm_name": vm_name,
        "provider_user": PROVIDER_USER,
        "provider_public_key": provider_public_key,
        "vm_user": vm_user,
        "vm_public_key": vm_public_key,
        "vm_sudo": vm_sudo,
        "packages": packages,
    }

    state = {
        "vm_name": vm_name,
        "trust": trust,
        "network": network,
        "ports": ports,
        "provider_private_key": str(provider_private_key),
    }
    save_vm_state(vm_name, state)

    run(["systemctl", "enable", "--now", "libvirtd"], sudo=True)
    run(["systemctl", "enable", "--now", "firewalld"], sudo=True)

    base_img = ensure_base_image()
    vm_disk = create_vm_disk(vm_name, vm["disk_gb"], base_img)

    if mode.startswith("nat"):
        create_nat_network(vm_name, network)
        network_arg = f'network={network["name"]},model=virtio,mac={network["mac"]}'
    else:
        network_arg = f'bridge={network["bridge_name"]},model=virtio,mac={network["mac"]}'

    user_data, meta_data = render_templates(context, template)
    seed_iso = create_seed_iso(vm_name, user_data, meta_data)

    virt_install(vm_name, vm, network_arg, vm_disk, seed_iso)

    if mode.startswith("nat"):
        zone_created = apply_firewalld_nat_policy(network, trust, ports)
        state["firewalld"] = {"zone_created": zone_created}
        save_vm_state(vm_name, state)
    else:
        print("Bridge mode selected: skipping host NAT firewall/port-forward rules.")
        print("Use your router/VLAN firewall for isolation.")

    print()
    print("Created VM")
    print("==========")
    print(f"Name:          {vm_name}")
    print(f"Tenant user:   {vm_user}")
    print(f"Provider user: {PROVIDER_USER}")
    print(f"Trust:         {trust}")
    print(f"Network mode:  {mode}")
    print(f"VM IP:         {network.get('vm_ip')}")
    print(f"MAC:           {network.get('mac')}")
    print()
    print("Provider/admin key:")
    print(f"  {provider_private_key}")
    print()
    print("Provider/admin SSH helper:")
    print(f"  ./vmssh-admin {vm_name}")
    print()

    ssh_port = None
    for port in ports:
        if int(port["guest"]) == 22:
            ssh_port = port["host"]

    if mode.startswith("nat") and ssh_port:
        print("Provider/admin SSH:")
        print(f"  ssh -i {provider_private_key} {PROVIDER_USER}@HOST_IP -p {ssh_port}")
        print()
        print("Tenant SSH:")
        print(f"  ssh {vm_user}@HOST_IP -p {ssh_port}")
    elif mode == "bridge":
        print("Provider/admin SSH:")
        print(f"  ssh -i {provider_private_key} {PROVIDER_USER}@VM_LAN_IP")
        print()
        print("Tenant SSH:")
        print(f"  ssh {vm_user}@VM_LAN_IP")


def ssh_admin(vm_name, vm_ip=None):
    require_tools(["virsh", "ssh"])

    if not vm_exists(vm_name):
        raise RuntimeError(f"VM not found: {vm_name}")

    provider_private_key = provider_private_key_path(vm_name)
    if not provider_private_key.exists():
        raise FileNotFoundError(
            f"Missing provider SSH key for {vm_name}: {provider_private_key}"
        )

    source = None
    if vm_ip is None:
        vm_ip, source = resolve_vm_ipv4(vm_name)

    if vm_ip is None:
        raise RuntimeError(
            "Could not determine the VM IP automatically. Retry with --ip <address>."
        )

    if source is not None:
        print(f"Resolved {vm_name} to {vm_ip} via libvirt {source}.")
    else:
        print(f"Using provided IP for {vm_name}: {vm_ip}")

    cmd = [
        "ssh",
        "-i",
        str(provider_private_key),
        "-o",
        "IdentitiesOnly=yes",
        f"{PROVIDER_USER}@{vm_ip}",
    ]

    print("+", " ".join(str(x) for x in cmd))
    result = subprocess.run(cmd)
    raise SystemExit(result.returncode)


def destroy(vm_name):
    state = load_vm_state(vm_name)
    network = dict(state.get("network") or {})
    network.update(discover_vm_network(vm_name) or {})
    ports = state.get("ports") or []

    if not network.get("name"):
        network["name"] = f"{vm_name}-net"

    if not network.get("zone"):
        network["zone"] = f"{vm_name}-zone"

    if vm_exists(vm_name):
        run(["virsh", "destroy", vm_name], sudo=True, check=False)
        run(["virsh", "undefine", vm_name, "--remove-all-storage"], sudo=True, check=False)

    cleanup_firewalld_vm_policy(vm_name, network, ports)

    run(["virsh", "net-destroy", network["name"]], sudo=True, check=False)
    run(["virsh", "net-undefine", network["name"]], sudo=True, check=False)

    cleanup_vm_storage(vm_name)
    cleanup_local_vm_artifacts(
        vm_name,
        provider_private_key=state.get("provider_private_key"),
    )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create")
    create_p.add_argument("config")

    destroy_p = sub.add_parser("destroy")
    destroy_p.add_argument("name")

    ssh_admin_p = sub.add_parser("ssh-admin")
    ssh_admin_p.add_argument("name")
    ssh_admin_p.add_argument("--ip")

    args = parser.parse_args()

    if args.command == "create":
        create(args.config)
    elif args.command == "destroy":
        destroy(args.name)
    elif args.command == "ssh-admin":
        ssh_admin(args.name, args.ip)


if __name__ == "__main__":
    main()
