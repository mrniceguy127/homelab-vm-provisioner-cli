"""Runtime VM state observation helpers.

These internal helpers query live VM runtime state from libvirt or the network layer.
They do not mutate state and are safe to call repeatedly for cache refresh.
"""

import time

from .network import discover_vm_network
from .provision import default_nat_bridge_name, vm_exists
from .system import capture_or_none, run


def is_libvirt_nat_network(network):
    """Check whether the network config represents a libvirt NAT network."""
    return network.get("mode") in ("nat", "nat-custom")


def merged_vm_network(vm_name, state):
    """Merge persisted VM network state with any live-discovered details."""
    network = dict(state.get("network") or {})
    network.update(discover_vm_network(vm_name) or {})
    if is_libvirt_nat_network(network):
        network.setdefault("name", f"{vm_name}-net")
        network.setdefault("libvirt_network_name", network.get("name"))
        network.setdefault("bridge_name", default_nat_bridge_name(vm_name))
    return network


def current_domain_state(vm_name):
    """Return the current libvirt domain state string when available."""
    return capture_or_none(["virsh", "domstate", vm_name], sudo=True)


def stop_vm_domain(vm_name, timeout_seconds=60):
    """Stop a VM, falling back to forceful shutdown if needed."""
    if not vm_exists(vm_name):
        raise FileNotFoundError(f"VM not found: {vm_name}")

    state = (current_domain_state(vm_name) or "").strip().lower()
    if state and state != "running":
        return False

    run(["virsh", "shutdown", vm_name], sudo=True, check=False)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = (current_domain_state(vm_name) or "").strip().lower()
        if state and state != "running":
            return True
        time.sleep(2)

    run(["virsh", "destroy", vm_name], sudo=True, check=False)
    return True


def start_vm_domain(vm_name):
    """Start a VM when it is not already running."""
    if not vm_exists(vm_name):
        raise FileNotFoundError(f"VM not found: {vm_name}")

    state = (current_domain_state(vm_name) or "").strip().lower()
    if state == "running":
        return False

    run(["virsh", "start", vm_name], sudo=True)
    return True
