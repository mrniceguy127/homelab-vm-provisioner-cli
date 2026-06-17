"""Provisioning helpers for libvirt resources and local artifacts.

This module provides backward-compatible functions that delegate to the new
service layer (services.py) and pure functions (core.py). It maintains existing
API surface for compatibility while using the refactored architecture internally.
"""

import shutil
import subprocess
from pathlib import Path

from .adapters import FileSystemAdapter, SSHKeyGenerator, SubprocessAdapter
from .config import default_admin_key_dir, default_vm_data_dir, delete_vm_state
from .constants import (
    ADMIN_USER,
    IMG_DIR,
    TEMPLATES_DIR,
)
from .core import compute_bridge_name, compute_legacy_bridge_name
from .services import TemplateService
from .system import run


def default_nat_bridge_name(vm_name):
    """Return the default libvirt bridge name for a VM NAT network.

    Args:
        vm_name: VM name.

    Returns:
        str: Stable bridge name within Linux interface length limits.
    """
    return compute_bridge_name(vm_name)


def legacy_nat_bridge_name(vm_name):
    """Return the historical default bridge name for backward cleanup.

    Args:
        vm_name: VM name.

    Returns:
        str: Older bridge naming scheme based on a truncated VM name.
    """
    return compute_legacy_bridge_name(vm_name)


def admin_private_key_path(vm_name, admin_key_dir=None):
    """Return the admin private key path for a VM.

    Args:
        vm_name: VM name.
        admin_key_dir: Optional directory override for generated admin keys.

    Returns:
        Path: Private key path inside the admin key directory.
    """
    key_dir = Path(admin_key_dir) if admin_key_dir is not None else default_admin_key_dir()
    return key_dir / f"{vm_name}_admin_ed25519"


def admin_keypair(vm_name, admin_key_dir=None):
    """Ensure the per-VM admin SSH keypair exists.

    Args:
        vm_name: VM name.
        admin_key_dir: Optional directory override for generated admin keys.

    Returns:
        tuple[Path, str]: Private key path and public key contents.
    """
    # Delegate to service layer using adapters
    key_dir = Path(admin_key_dir) if admin_key_dir is not None else default_admin_key_dir()
    
    subprocess_adapter = SubprocessAdapter()
    fs_adapter = FileSystemAdapter()
    key_generator = SSHKeyGenerator(subprocess_adapter, fs_adapter)
    
    key_path = admin_private_key_path(vm_name, admin_key_dir=key_dir)
    return key_generator.ensure_keypair(key_path, f"admin-{vm_name}")


def render_templates(context, template_name, vm_data_dir):
    """Render cloud-init templates for a VM.

    Args:
        context: Template variables for the VM.
        template_name: Base template name without the ``-user-data`` suffix.
        vm_data_dir: Directory for rendered local VM artifacts.

    Returns:
        tuple[Path, Path]: Rendered ``user-data`` and ``meta-data`` file paths.
    """
    # Delegate to service layer
    fs_adapter = FileSystemAdapter()
    template_service = TemplateService(TEMPLATES_DIR, fs_adapter)
    return template_service.render_cloud_init(context, template_name, Path(vm_data_dir))


def ensure_base_image(image_settings):
    """Ensure the base cloud image exists locally.

    Args:
        image_settings: Effective image settings for the VM.

    Returns:
        Path: Base image path.
    """
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    base_img = IMG_DIR / image_settings["name"]
    if not base_img.exists():
        run(["wget", "-O", str(base_img), image_settings["url"]], sudo=True)
    return base_img


def create_vm_disk(vm_name, disk_gb, base_img):
    """Create a qcow2 VM disk backed by the base image.

    Args:
        vm_name: VM name.
        disk_gb: Disk size in gibibytes.
        base_img: Base image path.

    Returns:
        Path: Created or existing VM disk path.
    """
    vm_disk = vm_disk_path(vm_name)
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
    """Build the cloud-init seed ISO for a VM.

    Args:
        vm_name: VM name.
        user_data_path: Rendered cloud-init ``user-data`` path.
        meta_data_path: Rendered cloud-init ``meta-data`` path.

    Returns:
        Path: Seed ISO path.
    """
    seed_iso = seed_iso_path(vm_name)
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


def os_variant_supported(os_variant):
    """Return whether the host recognizes a libvirt OS variant.

    Args:
        os_variant: Libvirt OS variant identifier.

    Returns:
        bool: ``True`` when the variant is listed by ``virt-install --osinfo list``.
        If the host cannot be queried, validation is skipped and ``True`` is
        returned.
    """
    try:
        result = subprocess.run(
            ["virt-install", "--osinfo", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return True

    if result.returncode != 0:
        return True

    known_variants = {
        line.split("|", 1)[0].strip()
        for line in result.stdout.splitlines()
        if "|" in line and line.split("|", 1)[0].strip()
    }
    if not known_variants:
        return True

    return os_variant in known_variants


def validate_os_variant(os_variant):
    """Raise when a libvirt OS variant is not supported by the host.

    Args:
        os_variant: Libvirt OS variant identifier.

    Raises:
        ValueError: If the host does not list the supplied OS variant.
    """
    if os_variant_supported(os_variant):
        return

    raise ValueError(
        f"image.os_variant '{os_variant}' is not supported by this host. "
        "Run `virt-install --osinfo list` to see supported values, or use `generic`."
    )


def bridge_interface_exists(bridge_name):
    """Return whether a Linux bridge interface exists.

    Args:
        bridge_name: Bridge interface name.

    Returns:
        bool: ``True`` when the interface exists.
    """
    try:
        result = subprocess.run(
            ["ip", "link", "show", bridge_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False

    return result.returncode == 0


def cleanup_bridge_interface(bridge_name):
    """Remove a leftover Linux bridge interface.

    Args:
        bridge_name: Bridge interface name.
    """
    run(["ip", "link", "delete", bridge_name, "type", "bridge"], sudo=True, check=False)


def create_nat_network(vm_name, network):
    """Create and start a libvirt NAT network when needed.

    Args:
        vm_name: VM name.
        network: NAT network settings.
    """
    bridge_name = network.get("bridge_name", default_nat_bridge_name(vm_name))
    xml = f"""
<network>
  <name>{network['name']}</name>
  <forward mode='nat'/>
  <bridge name='{bridge_name}' stp='on' delay='0'/>
  <ip address='{network['gateway']}' netmask='255.255.255.0'>
    <dhcp>
      <host mac='{network['mac']}' name='{vm_name}' ip='{network['vm_ip']}'/>
      <range start='{network['dhcp_start']}' end='{network['dhcp_end']}'/>
    </dhcp>
  </ip>
</network>
""".strip()

    xml_path = Path("/tmp") / f"{network['name']}.xml"
    #xml_path.write_text(xml, encoding="utf-8")
    subprocess.run(
        ["sudo", "tee", str(xml_path)],
        input=xml,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    result = subprocess.run(
        ["sudo", "virsh", "net-info", network["name"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return

    if bridge_interface_exists(bridge_name):
        cleanup_bridge_interface(bridge_name)

    run(["virsh", "net-define", str(xml_path)], sudo=True)
    run(["virsh", "net-autostart", network["name"]], sudo=True)
    run(["virsh", "net-start", network["name"]], sudo=True)


def vm_exists(vm_name):
    """Return whether a libvirt domain already exists.

    Args:
        vm_name: VM name.

    Returns:
        bool: ``True`` when the domain exists.
    """
    result = subprocess.run(
        ["sudo", "virsh", "dominfo", vm_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def vm_disk_path(vm_name):
    """Return the libvirt disk image path for a VM."""
    return IMG_DIR / f"{vm_name}.qcow2"


def seed_iso_path(vm_name):
    """Return the libvirt cloud-init seed ISO path for a VM."""
    return IMG_DIR / f"{vm_name}-seed.iso"


def copy_qcow2_image(source_path, target_path):
    """Copy a qcow2 disk image to a new location via ``qemu-img convert``."""
    run(["rm", "-f", str(target_path)], sudo=True, check=False)
    run(
        [
            "qemu-img",
            "convert",
            "-f",
            "qcow2",
            "-O",
            "qcow2",
            str(source_path),
            str(target_path),
        ],
        sudo=True,
    )
    return target_path


def copy_image_artifact(source_path, target_path):
    """Copy a libvirt-managed artifact such as a seed ISO."""
    run(["rm", "-f", str(target_path)], sudo=True, check=False)
    run(["cp", "-f", str(source_path), str(target_path)], sudo=True)
    return target_path


def prepare_cloned_guest_disk(vm_disk, vm_name, vm_users):
    """Reset guest identity files so a cloned VM boots as a new instance."""
    unique_users = [user for user in dict.fromkeys([ADMIN_USER, *vm_users]) if user]
    command = ["virt-customize", "-a", str(vm_disk), "--hostname", vm_name]

    for user in unique_users:
        command.extend(
            [
                "--run-command",
                f"mkdir -p /home/{user}/.ssh && rm -f /home/{user}/.ssh/authorized_keys",
            ]
        )

    command.extend(
        [
            "--run-command",
            "rm -f /etc/ssh/ssh_host_*",
            "--run-command",
            "cloud-init clean --logs --machine-id || true",
            "--run-command",
            "rm -rf /var/lib/cloud/*",
            "--run-command",
            "truncate -s 0 /etc/machine-id || true",
            "--run-command",
            "rm -f /var/lib/dbus/machine-id",
        ]
    )

    run(command, sudo=True)


def virt_install(vm_name, vm, network_arg, vm_disk, seed_iso, os_variant):
    """Create a VM with ``virt-install``.

    Args:
        vm_name: VM name.
        vm: VM settings from the user config.
        network_arg: Rendered ``virt-install --network`` argument.
        vm_disk: VM disk path.
        seed_iso: Seed ISO path.
        os_variant: Libvirt OS variant identifier for the guest image.
    """
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
            os_variant,
            "--network",
            network_arg,
            "--graphics",
            "none",
            "--import",
            "--noautoconsole",
        ],
        sudo=True,
    )


def cleanup_local_vm_artifacts(vm_name, admin_private_key=None, vm_data_dir=None):
    """Remove generated local files for a VM.

    Args:
        vm_name: VM name.
        admin_private_key: Optional admin private key path override.
        vm_data_dir: Optional VM data directory override.
    """
    if vm_data_dir is None:
        vm_data_dir = default_vm_data_dir(vm_name)

    if admin_private_key is None:
        admin_private_key = admin_private_key_path(vm_name)

    key_path = Path(admin_private_key)
    pub_path = Path(str(key_path) + ".pub")
    for path in (key_path, pub_path):
        if path.exists():
            path.unlink()

    vm_data_path = Path(vm_data_dir)
    if vm_data_path.exists():
        shutil.rmtree(vm_data_path)

    delete_vm_state(vm_name)


def cleanup_vm_storage(vm_name):
    """Remove VM disk images left in the libvirt image directory.

    Args:
        vm_name: VM name.
    """
    for path in (vm_disk_path(vm_name), seed_iso_path(vm_name)):
        run(["rm", "-f", str(path)], sudo=True, check=False)
