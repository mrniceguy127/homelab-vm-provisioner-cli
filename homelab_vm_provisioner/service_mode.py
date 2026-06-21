"""Internal service-mode entrypoints for orchestrated execution.

These helpers are not exposed as standalone CLI commands. They let other Python
services drive the provisioner directly without going through ``vmctl``.
"""

from .cli import (
    clone_from_definition,
    create_from_definition,
    current_domain_state,
    destroy,
    load_vm_state,
    merged_vm_network,
    prepare_vm_definition_from_config,
    reconcile_networking_records,
    snapshot_create_record_data,
    snapshot_delete_record_data,
    snapshot_restore_record_data,
    start,
    stop,
)


def create_vm(config_data, resolved_config_path="<service>", reconcile_payload=None):
    """Provision a VM directly from config data."""
    definition = prepare_vm_definition_from_config(config_data, resolved_config_path)
    return create_from_definition(definition, reconcile_payload=reconcile_payload)


def clone_vm(source_vm_name, config_data, resolved_config_path="<service>", reconcile_payload=None):
    """Clone a VM directly from config data."""
    definition = prepare_vm_definition_from_config(config_data, resolved_config_path)
    return clone_from_definition(source_vm_name, definition, reconcile_payload=reconcile_payload)


def reconcile_vm_records(vm_records, network_groups=None, policy_only=False, allow_destructive=False):
    """Reconcile networking directly from desired records."""
    return reconcile_networking_records(
        vm_records,
        policy_only=policy_only,
        allow_destructive=allow_destructive,
        network_groups=network_groups,
    )


def start_vm(vm_name):
    """Start a VM directly through the Python module."""
    return start(vm_name)


def stop_vm(vm_name):
    """Stop a VM directly through the Python module."""
    return stop(vm_name)


def destroy_vm(vm_name):
    """Destroy a VM directly through the Python module."""
    return destroy(vm_name)


def refresh_vm_runtime_state(vm_name):
    """Return a refreshed runtime state view for a VM."""
    state = load_vm_state(vm_name)
    network = merged_vm_network(vm_name, state)
    status = (current_domain_state(vm_name) or "unknown").strip().lower() or "unknown"
    refreshed = dict(state)
    refreshed["status"] = status
    refreshed["network"] = network
    refreshed["ports"] = state.get("ports") or []
    refreshed["mac_address"] = network.get("mac") or state.get("mac_address")
    refreshed["ip_address"] = network.get("vm_ip") or state.get("ip_address")
    return refreshed


def create_snapshot_record(vm_name, payload):
    """Create snapshot artifacts and return metadata."""
    return snapshot_create_record_data(vm_name, payload)


def restore_snapshot_record(vm_name, snapshot_id, metadata, vm_records=None, network_groups=None):
    """Restore snapshot artifacts from a DB-backed metadata record."""
    return snapshot_restore_record_data(
        vm_name,
        snapshot_id,
        metadata,
        vm_records=vm_records,
        network_groups=network_groups,
    )


def delete_snapshot_record(vm_name, snapshot_id, metadata):
    """Delete snapshot artifacts from a DB-backed metadata record."""
    return snapshot_delete_record_data(vm_name, snapshot_id, metadata)
