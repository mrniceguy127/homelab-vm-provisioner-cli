"""Service-mode snapshot orchestration.

These internal helpers create, restore, and delete VM snapshots for service mode.
They handle DB-backed snapshot metadata and host-local snapshot artifacts.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    default_snapshot_root,
    load_global_config,
    load_vm_state,
    resolve_state_artifact_path,
)
from .provision import (
    copy_image_artifact,
    copy_qcow2_image,
    seed_iso_path,
    vm_disk_path,
    vm_exists,
)
from .runtime_observation import (
    merged_vm_network,
    start_vm_domain,
    stop_vm_domain,
)
from .system import host_lifecycle_lock


def current_snapshot_id():
    """Generate a unique snapshot ID."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def snapshot_root_for_vm(vm_name, global_config=None):
    """Return the restore point directory for a VM."""
    return default_snapshot_root(global_config) / vm_name


def snapshot_path_for_vm(vm_name, snapshot_id, global_config=None):
    """Return the restore point directory for one snapshot."""
    return snapshot_root_for_vm(vm_name, global_config) / snapshot_id


def copy_local_file(src, dst):
    """Copy a file preserving mode but not ownership."""
    from .cli import copy_local_file as cli_copy_local_file
    return cli_copy_local_file(src, dst)


def copy_local_tree(src, dst):
    """Copy a directory tree."""
    from .cli import copy_local_tree as cli_copy_local_tree
    return cli_copy_local_tree(src, dst)


def chown_path_to_current_user(path):
    """Change ownership of a path to the current user."""
    from .cli import chown_path_to_current_user as cli_chown
    return cli_chown(path)


def snapshot_create_record_data(vm_name, payload):
    """Create snapshot artifacts and return DB-ready metadata."""
    from .system import require_tools

    require_tools()

    config_snapshot = payload.get("config_snapshot") or payload.get("config")
    if not isinstance(config_snapshot, dict):
        raise ValueError("snapshot_create_record_data requires config_snapshot mapping")

    runtime_state_snapshot = dict(payload.get("runtime_state_snapshot") or payload.get("runtime_state") or {})
    snapshot_id = payload.get("snapshot_id") or current_snapshot_id()
    global_config = load_global_config()
    snapshot_path = snapshot_path_for_vm(vm_name, snapshot_id, global_config=global_config)
    disk_path = vm_disk_path(vm_name)
    seed_path = seed_iso_path(vm_name)
    source_was_running = False

    if not disk_path.exists():
        raise FileNotFoundError(f"VM disk was not found for snapshotting: {disk_path}")

    with host_lifecycle_lock("snapshot-create", vm_name=vm_name):
        snapshot_path.mkdir(parents=True, exist_ok=False)

        try:
            source_was_running = stop_vm_domain(vm_name) if vm_exists(vm_name) else False

            snapshot_disk = snapshot_path / f"{vm_name}.qcow2"
            copy_qcow2_image(disk_path, snapshot_disk)

            snapshot_seed = None
            if seed_path.exists():
                snapshot_seed = snapshot_path / f"{vm_name}-seed.iso"
                copy_image_artifact(seed_path, snapshot_seed)

            vm_data_dir = runtime_state_snapshot.get("vm_data_dir")
            resolved_vm_data_dir = resolve_state_artifact_path(vm_data_dir) if vm_data_dir else None
            snapshot_vm_data_dir = None
            if resolved_vm_data_dir and resolved_vm_data_dir.exists():
                snapshot_vm_data_dir = snapshot_path / "vm-data"
                copy_local_tree(resolved_vm_data_dir, snapshot_vm_data_dir)

            current_state = load_vm_state(vm_name)
            admin_private_key = current_state.get("admin_private_key")
            snapshot_keys_dir = None
            if admin_private_key:
                admin_key_path = resolve_state_artifact_path(admin_private_key)
                if admin_key_path.exists():
                    snapshot_keys_dir = snapshot_path / "keys"
                    copy_local_file(admin_key_path, snapshot_keys_dir / admin_key_path.name)
                admin_pub_path = Path(str(admin_key_path) + ".pub")
                if admin_pub_path.exists():
                    snapshot_keys_dir = snapshot_path / "keys"
                    copy_local_file(admin_pub_path, snapshot_keys_dir / admin_pub_path.name)

            metadata = {
                "snapshot_id": snapshot_id,
                "vm_name": vm_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_was_running": source_was_running,
                "config_snapshot": config_snapshot,
                "runtime_state_snapshot": runtime_state_snapshot,
                "artifact_manifest": {
                    "snapshot_path": str(snapshot_path),
                    "disk": str(snapshot_disk),
                    "seed_iso": str(snapshot_seed) if snapshot_seed is not None else None,
                    "vm_data_dir_snapshot": str(snapshot_vm_data_dir) if snapshot_vm_data_dir else None,
                    "keys_dir": str(snapshot_keys_dir) if snapshot_keys_dir else None,
                },
                "local_artifacts": {
                    "vm_data_dir": vm_data_dir,
                    "admin_private_key": admin_private_key,
                },
            }
            chown_path_to_current_user(snapshot_path)
        except Exception:
            if snapshot_path.exists():
                shutil.rmtree(snapshot_path, ignore_errors=True)
            raise
        finally:
            if source_was_running:
                start_vm_domain(vm_name)

    return metadata


def restored_network_config(vm_name, runtime_state_snapshot, config_snapshot):
    """Rebuild a restored network config."""
    from .cli import restored_network_config as cli_restored_network_config
    return cli_restored_network_config(vm_name, runtime_state_snapshot, config_snapshot)


def cleanup_vm_runtime_definition(vm_name, network, ports, remove_storage):
    """Remove the libvirt domain and network resources for a VM."""
    from .service_workflows import cleanup_vm_runtime_definition as workflows_cleanup
    return workflows_cleanup(vm_name, network, ports, remove_storage)


def apply_runtime_networking(vm_name, network, trust, ports, state):
    """Apply runtime networking configuration."""
    from .cli import apply_runtime_networking as cli_apply_runtime_networking
    return cli_apply_runtime_networking(vm_name, network, trust, ports, state)


def ensure_host_services():
    """Ensure host services required for VM operations."""
    from .cli import ensure_host_services as cli_ensure_host_services
    return cli_ensure_host_services()


def snapshot_restore_record_data(vm_name, snapshot_id, metadata, vm_records=None, network_groups=None):
    """Restore a VM from externally supplied snapshot metadata."""
    from .reconciler import reconcile_networking, reconcile_networking_records
    from .system import require_tools

    require_tools()

    if not isinstance(metadata, dict):
        raise ValueError("snapshot_restore_record_data requires snapshot metadata mapping")

    config_snapshot = metadata.get("config_snapshot")
    runtime_state_snapshot = dict(metadata.get("runtime_state_snapshot") or {})
    artifact_manifest = metadata.get("artifact_manifest") or {}
    if not isinstance(config_snapshot, dict):
        raise ValueError("snapshot_restore_record_data requires config_snapshot mapping")

    snapshot_disk = Path(artifact_manifest.get("disk") or "")
    snapshot_seed_value = artifact_manifest.get("seed_iso")
    snapshot_seed = Path(snapshot_seed_value) if snapshot_seed_value else None
    snapshot_vm_data_dir_value = artifact_manifest.get("vm_data_dir_snapshot")
    snapshot_vm_data_dir = Path(snapshot_vm_data_dir_value) if snapshot_vm_data_dir_value else None
    snapshot_keys_dir_value = artifact_manifest.get("keys_dir")
    snapshot_keys_dir = Path(snapshot_keys_dir_value) if snapshot_keys_dir_value else None

    if not snapshot_disk.exists():
        raise FileNotFoundError(f"Snapshot disk was not found for {vm_name}: {snapshot_disk}")
    if snapshot_seed is not None and not snapshot_seed.exists():
        raise FileNotFoundError(f"Snapshot seed ISO was not found for {vm_name}: {snapshot_seed}")

    with host_lifecycle_lock("snapshot-restore", vm_name=vm_name):
        current_state = load_vm_state(vm_name)
        current_network = merged_vm_network(vm_name, current_state)
        current_ports = current_state.get("ports") or []
        cleanup_vm_runtime_definition(vm_name, current_network, current_ports, remove_storage=False)

        copy_qcow2_image(snapshot_disk, vm_disk_path(vm_name))
        if snapshot_seed is not None:
            copy_image_artifact(snapshot_seed, seed_iso_path(vm_name))

        restored_vm_data_dir = runtime_state_snapshot.get("vm_data_dir")
        if restored_vm_data_dir and snapshot_vm_data_dir is not None and snapshot_vm_data_dir.exists():
            copy_local_tree(snapshot_vm_data_dir, resolve_state_artifact_path(restored_vm_data_dir))

        admin_private_key = (metadata.get("local_artifacts") or {}).get("admin_private_key")
        if admin_private_key and snapshot_keys_dir is not None:
            admin_key_path = resolve_state_artifact_path(admin_private_key)
            snapshot_key_path = snapshot_keys_dir / admin_key_path.name
            snapshot_pub_path = snapshot_keys_dir / f"{admin_key_path.name}.pub"
            if snapshot_key_path.exists():
                copy_local_file(snapshot_key_path, admin_key_path)
            if snapshot_pub_path.exists():
                copy_local_file(snapshot_pub_path, Path(str(admin_key_path) + ".pub"))

        restored_network = restored_network_config(vm_name, runtime_state_snapshot, config_snapshot)
        restored_ports = runtime_state_snapshot.get("ports") or config_snapshot.get("ports") or []
        restored_trust = runtime_state_snapshot.get("trust") or config_snapshot.get("vm", {}).get("trust", "untrusted")

        ensure_host_services()
        if restored_network.get("network_group_id") and vm_records is not None:
            reconcile_networking_records(
                vm_records,
                policy_only=False,
                allow_destructive=False,
                network_groups=network_groups,
            )
        elif restored_network.get("network_group_id"):
            reconcile_networking()

        from .provision import virt_install

        virt_install(
            vm_name,
            {"vcpus": runtime_state_snapshot.get("vcpus", 2), "memory_mb": runtime_state_snapshot.get("memory_mb", 2048)},
            "",
            vm_disk_path(vm_name),
            seed_iso_path(vm_name) if snapshot_seed is not None else None,
            runtime_state_snapshot.get("os_variant", "ubuntu22.04"),
        )

        apply_runtime_networking(vm_name, restored_network, restored_trust, restored_ports, runtime_state_snapshot)

        if metadata.get("source_was_running"):
            start_vm_domain(vm_name)

    return metadata


def snapshot_delete_record_data(vm_name, snapshot_id, metadata):
    """Delete snapshot artifacts from a DB-backed metadata record."""
    from .system import require_tools

    require_tools()

    if not isinstance(metadata, dict):
        raise ValueError("snapshot_delete_record_data requires snapshot metadata mapping")

    artifact_manifest = metadata.get("artifact_manifest") or {}
    snapshot_path_value = artifact_manifest.get("snapshot_path")
    if not snapshot_path_value:
        raise ValueError("snapshot metadata missing artifact_manifest.snapshot_path")

    snapshot_path = Path(snapshot_path_value)
    if snapshot_path.exists():
        shutil.rmtree(snapshot_path)

    return {"deleted": True, "snapshot_id": snapshot_id, "vm_name": vm_name}
