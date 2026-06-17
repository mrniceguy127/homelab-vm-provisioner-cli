"""Domain value objects and data structures for VM provisioning.

This module contains immutable value objects representing core domain state.
These objects are simple, serializable, and contain no side effects or business logic.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NetworkSettings:
    """Immutable network configuration for a VM.
    
    Represents the complete network settings after all defaults and
    transformations have been applied.
    """
    
    mode: str
    profile: str
    mac: str
    bridge_name: Optional[str] = None
    name: Optional[str] = None
    libvirt_network_name: Optional[str] = None
    cidr: Optional[str] = None
    subnet_cidr: Optional[str] = None
    gateway: Optional[str] = None
    gateway_ip: Optional[str] = None
    vm_ip: Optional[str] = None
    dhcp_start: Optional[str] = None
    dhcp_end: Optional[str] = None
    prefix: Optional[str] = None
    network_group_id: Optional[str] = None
    group_name: Optional[str] = None
    owner_user_id: Optional[str] = None


@dataclass(frozen=True)
class ImageSettings:
    """Immutable image configuration for VM provisioning."""
    
    name: str
    url: str
    os_variant: str


@dataclass(frozen=True)
class DNSSettings:
    """Immutable DNS configuration for VM guests."""
    
    resolvers: tuple[str, ...]


@dataclass(frozen=True)
class VMConfig:
    """Immutable VM configuration parsed from user input."""
    
    name: str
    user: str
    disk_gb: int
    memory_mb: int
    vcpus: int
    network: dict
    allow_sudo: bool = True
    packages: tuple[str, ...] = field(default_factory=tuple)
    ports: tuple[dict, ...] = field(default_factory=tuple)
    trust: str = "untrusted"
    image: Optional[dict] = None
    dns: Optional[dict] = None
    setup_script: Optional[str] = None
    user_key: Optional[str] = None


@dataclass(frozen=True)
class CloudInitContext:
    """Immutable context for cloud-init template rendering."""
    
    vm_name: str
    admin_user: str
    admin_public_key: str
    vm_user: str
    vm_public_key: Optional[str]
    vm_sudo: str
    packages: tuple[str, ...]
    dns_resolvers: tuple[str, ...]
    setup_script_content: Optional[str]


@dataclass(frozen=True)
class SubnetAllocation:
    """Immutable subnet allocation result for NAT networking."""
    
    prefix: str
    cidr: str
    gateway: str
    vm_ip: str
    dhcp_start: str
    dhcp_end: str


@dataclass(frozen=True)
class PathSettings:
    """Immutable project-level path configuration."""
    
    vm_data_dir: str
    vm_state_dir: str
    user_key_dir: str
    admin_key_dir: str
    script_dir: str
    snapshot_dir: str
