"""Pure functions for network calculations and transformations.

This module contains deterministic, side-effect-free functions for network
operations like MAC generation, subnet selection, IP address validation, and
configuration building.
"""

import hashlib
import ipaddress
import random
from typing import Optional

from .domain import SubnetAllocation


def generate_random_mac() -> str:
    """Generate a libvirt-friendly random MAC address.
    
    Returns:
        Random MAC address in the 52:54:00:xx:xx:xx range.
    """
    return "52:54:00:%02x:%02x:%02x" % (
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )


def compute_bridge_name(vm_name: str) -> str:
    """Compute a stable bridge name for a VM's NAT network.
    
    Args:
        vm_name: VM name.
        
    Returns:
        Stable bridge name within Linux interface length limits.
    """
    suffix = hashlib.sha1(vm_name.encode("utf-8")).hexdigest()[:8]
    return f"virbr-{suffix}"


def compute_legacy_bridge_name(vm_name: str) -> str:
    """Compute the historical default bridge name for backward cleanup.
    
    Args:
        vm_name: VM name.
        
    Returns:
        Older bridge naming scheme based on truncated VM name.
    """
    return f"virbr-{vm_name[:6]}"


def validate_vm_name_length(vm_name: str, max_length: int = 63) -> None:
    """Validate VM name length constraint.
    
    Args:
        vm_name: VM name to validate.
        max_length: Maximum allowed length.
        
    Raises:
        ValueError: If the VM name exceeds the maximum length.
    """
    if len(vm_name) > max_length:
        raise ValueError(f"vm.name must be {max_length} characters or fewer")


def validate_ipv4_network(cidr_text: str, required_prefix: Optional[int] = None) -> ipaddress.IPv4Network:
    """Validate and parse an IPv4 network CIDR.
    
    Args:
        cidr_text: CIDR notation string (e.g., "192.168.1.0/24").
        required_prefix: If provided, enforce this prefix length.
        
    Returns:
        Parsed IPv4Network object.
        
    Raises:
        ValueError: If the CIDR is invalid or doesn't meet requirements.
    """
    try:
        network = ipaddress.ip_network(cidr_text, strict=True)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 network: {cidr_text}") from exc
    
    if network.version != 4:
        raise ValueError(f"Must be an IPv4 network: {cidr_text}")
    
    if required_prefix is not None and network.prefixlen != required_prefix:
        raise ValueError(f"Must be /{required_prefix} network: {cidr_text}")
    
    return network


def validate_ipv4_address(address_text: str) -> ipaddress.IPv4Address:
    """Validate and parse an IPv4 address.
    
    Args:
        address_text: IP address string.
        
    Returns:
        Parsed IPv4Address object.
        
    Raises:
        ValueError: If the address is invalid.
    """
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {address_text}") from exc
    
    if address.version != 4:
        raise ValueError(f"Must be an IPv4 address: {address_text}")
    
    return address


def validate_address_in_network(address: ipaddress.IPv4Address, network: ipaddress.IPv4Network, field_name: str) -> None:
    """Validate that an address belongs to a network.
    
    Args:
        address: IP address to check.
        network: Network containing the address.
        field_name: Field name for error messages.
        
    Raises:
        ValueError: If the address is not in the network.
    """
    if address not in network:
        raise ValueError(f"{field_name} must be inside network {network}: {address}")


def validate_nat_custom_network(network_config: dict) -> None:
    """Validate explicit NAT custom network configuration.
    
    Args:
        network_config: Network configuration dictionary with CIDR and addresses.
        
    Raises:
        ValueError: If any network setting is invalid.
    """
    cidr_text = network_config["cidr"]
    cidr = validate_ipv4_network(cidr_text, required_prefix=24)
    
    # Validate each address field
    for field in ("gateway", "vm_ip", "dhcp_start", "dhcp_end"):
        address_text = network_config[field]
        address = validate_ipv4_address(address_text)
        validate_address_in_network(address, cidr, f"network.{field}")
    
    # Validate DHCP range ordering
    dhcp_start = ipaddress.ip_address(network_config["dhcp_start"])
    dhcp_end = ipaddress.ip_address(network_config["dhcp_end"])
    if dhcp_start > dhcp_end:
        raise ValueError(
            f"network.dhcp_start must not be greater than network.dhcp_end: "
            f"{dhcp_start} > {dhcp_end}"
        )


def check_subnet_prefix_used(prefix: str, existing_routes: str, existing_networks: str) -> bool:
    """Check if a subnet prefix appears in existing network state.
    
    Args:
        prefix: Prefix string like "192.168.240.".
        existing_routes: Text output from routing table.
        existing_networks: Text output from network configurations.
        
    Returns:
        True if the prefix appears in either input.
    """
    haystack = existing_routes + "\n" + existing_networks
    return prefix in haystack


def find_free_subnet(existing_routes: str, existing_networks: str) -> SubnetAllocation:
    """Find an unused 192.168.X.0/24 subnet for NAT networking.
    
    This is a pure function that selects a subnet based on the provided
    existing network state strings.
    
    Args:
        existing_routes: Text from host routing table.
        existing_networks: Text from libvirt network definitions.
        
    Returns:
        SubnetAllocation with generated network settings.
        
    Raises:
        RuntimeError: If no free subnet can be found in the range.
    """
    for third_octet in range(100, 251):
        prefix = f"192.168.{third_octet}"
        if check_subnet_prefix_used(prefix + ".", existing_routes, existing_networks):
            continue
        
        return SubnetAllocation(
            prefix=prefix,
            cidr=f"{prefix}.0/24",
            gateway=f"{prefix}.1",
            vm_ip=f"{prefix}.50",
            dhcp_start=f"{prefix}.50",
            dhcp_end=f"{prefix}.99",
        )
    
    raise RuntimeError("Could not find free 192.168.X.0/24 subnet")


def normalize_network_profile(network_config: Optional[dict]) -> str:
    """Normalize network profile/mode identifiers to canonical form.
    
    Args:
        network_config: Network configuration dictionary.
        
    Returns:
        Canonical profile string: "bridged", "private", or "isolated_nat".
    """
    config = network_config or {}
    profile = str(config.get("profile") or config.get("mode") or "isolated_nat")
    profile = profile.strip().lower()
    
    if profile in ("bridge", "bridged"):
        return "bridged"
    if profile == "private":
        return "private"
    if profile in ("nat-auto", "nat-custom", "nat", "isolated_nat"):
        return "isolated_nat"
    
    return "isolated_nat"


def build_cloud_init_context(
    vm_name: str,
    admin_user: str,
    admin_public_key: str,
    vm_user: str,
    vm_public_key: Optional[str],
    allow_sudo: bool,
    packages: tuple[str, ...],
    dns_resolvers: tuple[str, ...],
    setup_script_content: Optional[str],
) -> dict:
    """Build cloud-init template context from VM settings.
    
    Pure function that transforms VM configuration into template variables.
    
    Args:
        vm_name: VM name.
        admin_user: Admin username.
        admin_public_key: Admin SSH public key.
        vm_user: Tenant username.
        vm_public_key: Tenant SSH public key (optional).
        allow_sudo: Whether tenant has sudo access.
        packages: Additional packages to install.
        dns_resolvers: DNS server addresses.
        setup_script_content: Optional setup script contents.
        
    Returns:
        Dictionary of template variables for cloud-init.
    """
    return {
        "vm_name": vm_name,
        "admin_user": admin_user,
        "admin_public_key": admin_public_key,
        "vm_user": vm_user,
        "vm_public_key": vm_public_key,
        "vm_sudo": "ALL=(ALL) NOPASSWD:ALL" if allow_sudo else "false",
        "packages": packages,
        "dns_resolvers": dns_resolvers,
        "setup_script_content": setup_script_content,
    }
