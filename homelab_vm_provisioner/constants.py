"""Project-wide constants used by the provisioner."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
DEFAULT_DATA_DIR_NAME = "data"


def _resolve_default_data_dir():
    configured_path = os.environ.get("PROVISIONER_DATA_DIR")
    if not configured_path:
        return PROJECT_DIR / DEFAULT_DATA_DIR_NAME

    resolved_path = Path(configured_path).expanduser()
    if resolved_path.is_absolute():
        return resolved_path

    return PROJECT_DIR / resolved_path


GLOBAL_CONFIG_PATH = _resolve_default_data_dir() / "vmctl.yaml"

ADMIN_USER = "vmadmin"
LEGACY_VM_BUILD_DIR = PROJECT_DIR / ".build"

IMG_DIR = Path("/var/lib/libvirt/images")
BASE_IMG_NAME = "debian-12-generic-amd64.qcow2"
BASE_IMG_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
OS_VARIANT = "generic"

DEFAULT_REQUIRED_TOOLS = (
    "virsh",
    "virt-install",
    "qemu-img",
    "cloud-localds",
    "nft",
    "ssh-keygen",
    "wget",
)

INSTALL_HINT = (
    "sudo apt install -y libvirt-daemon-system virtinst qemu-utils "
    "cloud-image-utils nftables wget openssh-client python3-yaml python3-jinja2"
)

BLOCKED_PRIVATE_RANGES = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "169.254.0.0/16",
]

DEFAULT_VM_DNS_RESOLVERS = ("1.1.1.1", "1.0.0.1")
