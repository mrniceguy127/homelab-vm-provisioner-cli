"""Service-mode VM lifecycle orchestration workflows.

These internal helpers execute VM create, clone, start, stop, and destroy
workflows. They are reusable building blocks, not CLI commands.
"""

from .config import (
    default_admin_key_dir,
    dns_settings_for_config,
    image_settings_for_config,
    load_config,
    load_global_config,
    load_vm_state,
    resolve_config_path,
    resolve_user_key_path,
    save_vm_state,
    vm_data_dir_for_config,
)
from .core import validate_vm_name_length
from .provision import (
    admin_keypair,
    bridge_interface_exists,
    cleanup_bridge_interface,
    cleanup_local_vm_artifacts,
    cleanup_vm_storage,
    copy_qcow2_image,
    create_nat_network,
    create_seed_iso,
    create_vm_disk,
    default_nat_bridge_name,
    ensure_base_image,
    legacy_nat_bridge_name,
    prepare_cloned_guest_disk,
    render_templates,
    validate_os_variant,
    virt_install,
    vm_disk_path,
    vm_exists,
)
from .reconciler import (
    reconcile_networking,
    reconcile_networking_records,
    validate_networking_changes,
)
from .runtime_observation import (
    merged_vm_network,
    start_vm_domain,
    stop_vm_domain,
)
from .system import host_lifecycle_lock, run

MAX_VM_NAME_LENGTH = 63


def validate_vm_name(vm_name):
    """Validate the VM name against the project VM name limit.

    Args:
        vm_name: VM name from config.

    Raises:
        ValueError: If the VM name is too long.
    """
    validate_vm_name_length(vm_name, MAX_VM_NAME_LENGTH)


def is_libvirt_nat_network(network):
    """Check whether the network config represents a libvirt NAT network."""
    return network.get("mode") in ("nat", "nat-custom")


def prepare_vm_definition_from_config(config_data, resolved_config_path):
    """Resolve an already loaded VM config into provisioning inputs."""
    from .cli import (
        build_network_config,
        build_render_context,
        build_vm_state,
        load_setup_script_content,
    )

    global_config = load_global_config()
    vm = config_data["vm"]
    net_cfg = config_data.get("network", {})
    packages = config_data.get("packages", [])
    ports = config_data.get("ports", [])

    vm_name = vm["name"]
    vm_user = vm["user"]
    vm_ssh_key_file = None
    inline_vm_public_key = vm.get("ssh_public_key")
    if vm.get("ssh_key_file"):
        vm_ssh_key_file = resolve_user_key_path(vm["ssh_key_file"], global_config=global_config)
    allow_sudo = bool(vm.get("allow_sudo", False))
    trust = vm.get("trust", "untrusted")
    template = vm.get("template", "base")

    if trust not in ("trusted", "untrusted"):
        raise ValueError("vm.trust must be trusted or untrusted")
    validate_vm_name(vm_name)
    if vm_ssh_key_file is not None and not vm_ssh_key_file.exists():
        raise FileNotFoundError(f"Missing VM SSH key file: {vm_ssh_key_file}")

    setup_script_content = load_setup_script_content(config_data, global_config)
    vm_data_dir = vm_data_dir_for_config(vm_name, config_data, global_config=global_config)
    image_settings = image_settings_for_config(config_data, global_config=global_config)
    dns_settings = dns_settings_for_config(config_data, global_config=global_config)
    validate_os_variant(image_settings["os_variant"])
    admin_private_key, admin_public_key = admin_keypair(
        vm_name,
        admin_key_dir=default_admin_key_dir(global_config),
    )
    vm_public_key = None
    if inline_vm_public_key is not None:
        vm_public_key = inline_vm_public_key.strip()
    elif vm_ssh_key_file is not None:
        vm_public_key = vm_ssh_key_file.read_text(encoding="utf-8").strip()

    network = build_network_config(vm_name, net_cfg)
    context = build_render_context(
        vm_name,
        admin_public_key,
        vm_user,
        vm_public_key,
        allow_sudo,
        packages,
        dns_settings["resolvers"],
        setup_script_content,
    )

    return {
        "resolved_config_path": resolved_config_path,
        "global_config": global_config,
        "config_data": config_data,
        "vm": vm,
        "vm_name": vm_name,
        "vm_user": vm_user,
        "trust": trust,
        "template": template,
        "ports": ports,
        "network": network,
        "image_settings": image_settings,
        "vm_data_dir": vm_data_dir,
        "admin_private_key": admin_private_key,
        "render_context": context,
        "state": build_vm_state(
            vm_name,
            resolved_config_path,
            trust,
            vm_data_dir,
            network,
            ports,
            admin_private_key,
        ),
    }


def render_seed_iso_for_definition(definition):
    """Render cloud-init artifacts and build the VM seed ISO."""
    user_data, meta_data = render_templates(
        definition["render_context"],
        definition["template"],
        definition["vm_data_dir"],
    )
    return create_seed_iso(definition["vm_name"], user_data, meta_data)


def build_network_arg(vm_name, network):
    """Build the virt-install network argument string."""
    from .cli import build_network_arg as cli_build_network_arg
    return cli_build_network_arg(vm_name, network)


def ensure_host_services():
    """Ensure host services required for VM operations."""
    from .cli import ensure_host_services as cli_ensure_host_services
    return cli_ensure_host_services()


def apply_runtime_networking(vm_name, network, trust, ports, state):
    """Apply runtime networking configuration."""
    from .cli import apply_runtime_networking as cli_apply_runtime_networking
    return cli_apply_runtime_networking(vm_name, network, trust, ports, state)


def create_from_definition(definition, reconcile_payload=None, persist_state=True):
    """Provision a VM from a prepared definition.

    This is the internal service-mode entrypoint used by orchestrators.
    """
    vm_name = definition["vm_name"]
    with host_lifecycle_lock("create", vm_name=vm_name):
        if reconcile_payload and definition["network"].get("network_group_id"):
            validate_networking_changes(
                vm_records=reconcile_payload.get("vm_records"),
                allow_destructive=reconcile_payload.get("allow_destructive", False),
            )

        if persist_state:
            save_vm_state(vm_name, definition["state"])

        ensure_host_services()
        if definition["network"].get("network_group_id") and reconcile_payload:
            reconcile_networking_records(
                reconcile_payload.get("vm_records", []),
                policy_only=reconcile_payload.get("policy_only", False),
                allow_destructive=reconcile_payload.get("allow_destructive", False),
                network_groups=reconcile_payload.get("network_groups"),
            )
        elif definition["network"].get("network_group_id"):
            reconcile_networking()

        base_img = ensure_base_image(definition["image_settings"])
        vm_disk = create_vm_disk(vm_name, definition["vm"]["disk_gb"], base_img)
        network_arg = build_network_arg(vm_name, definition["network"])
        seed_iso = render_seed_iso_for_definition(definition)

        if definition["network"]["mode"].startswith("nat"):
            create_nat_network(vm_name, definition["network"])

        virt_install(
            vm_name,
            definition["vm"],
            network_arg,
            vm_disk,
            seed_iso,
            definition["image_settings"]["os_variant"],
        )

        if persist_state:
            apply_runtime_networking(
                vm_name,
                definition["network"],
                definition["trust"],
                definition["ports"],
                definition["state"],
            )

    return definition


def clone_from_definition(source_vm_name, definition, reconcile_payload=None, persist_state=True):
    """Clone a VM using a prepared target definition."""
    target_vm_name = definition["vm_name"]
    if target_vm_name == source_vm_name:
        raise ValueError("Clone target must use a different vm.name than the source VM")
    if not vm_exists(source_vm_name):
        raise FileNotFoundError(f"Source VM not found: {source_vm_name}")
    if vm_exists(target_vm_name):
        raise RuntimeError(f"Target VM already exists: {target_vm_name}")

    source_disk = vm_disk_path(source_vm_name)
    target_disk = vm_disk_path(target_vm_name)
    if not source_disk.exists():
        raise FileNotFoundError(f"Source VM disk was not found: {source_disk}")
    if target_disk.exists():
        raise RuntimeError(f"Target VM disk already exists: {target_disk}")

    with host_lifecycle_lock("clone", vm_name=target_vm_name):
        if reconcile_payload and definition["network"].get("network_group_id"):
            validate_networking_changes(
                vm_records=reconcile_payload.get("vm_records"),
                allow_destructive=reconcile_payload.get("allow_destructive", False),
            )

        if persist_state:
            save_vm_state(target_vm_name, definition["state"])

        source_state = load_vm_state(source_vm_name)
        source_config_path = source_state.get("config_path")
        source_vm_user = None
        if source_config_path:
            try:
                resolved_source_config_path = resolve_config_path(source_config_path)
            except FileNotFoundError:
                resolved_source_config_path = None

            if resolved_source_config_path and resolved_source_config_path.exists():
                source_vm_user = load_config(resolved_source_config_path).get("vm", {}).get("user")

        source_was_running = False
        try:
            source_was_running = stop_vm_domain(source_vm_name)
            ensure_host_services()
            if definition["network"].get("network_group_id") and reconcile_payload:
                reconcile_networking_records(
                    reconcile_payload.get("vm_records", []),
                    policy_only=reconcile_payload.get("policy_only", False),
                    allow_destructive=reconcile_payload.get("allow_destructive", False),
                    network_groups=reconcile_payload.get("network_groups"),
                )
            elif definition["network"].get("network_group_id"):
                reconcile_networking()

            copy_qcow2_image(source_disk, target_disk)
            prepare_cloned_guest_disk(
                target_disk,
                target_vm_name,
                [source_vm_user, definition["vm_user"]],
            )

            if definition["network"]["mode"].startswith("nat"):
                create_nat_network(target_vm_name, definition["network"])

            seed_iso = render_seed_iso_for_definition(definition)
            virt_install(
                target_vm_name,
                definition["vm"],
                build_network_arg(target_vm_name, definition["network"]),
                target_disk,
                seed_iso,
                definition["image_settings"]["os_variant"],
            )
            if persist_state:
                apply_runtime_networking(
                    target_vm_name,
                    definition["network"],
                    definition["trust"],
                    definition["ports"],
                    definition["state"],
                )

        finally:
            if source_was_running:
                start_vm_domain(source_vm_name)

    return definition


def start_vm(vm_name):
    """Start an existing libvirt VM."""
    state = load_vm_state(vm_name)
    with host_lifecycle_lock("start", vm_name=vm_name):
        if state.get("network", {}).get("network_group_id"):
            reconcile_networking()
        elif is_libvirt_nat_network(state.get("network") or {}):
            reconcile_networking(policy_only=True)
        start_vm_domain(vm_name)


def stop_vm(vm_name):
    """Stop an existing libvirt VM."""
    with host_lifecycle_lock("stop", vm_name=vm_name):
        stop_vm_domain(vm_name)


def destroy_vm(vm_name):
    """Destroy a VM and remove its associated host artifacts."""
    from .reconciler import configured_vm_records

    def planned_managed_vm_records(vm_name, replacement_record=None):
        """Return managed VM records after optionally replacing one VM entry."""
        records = [record for record in configured_vm_records() if record["vm_name"] != vm_name]
        if replacement_record is not None:
            records.append(replacement_record)
        return records

    with host_lifecycle_lock("destroy", vm_name=vm_name):
        state = load_vm_state(vm_name)
        network = merged_vm_network(vm_name, state)
        ports = state.get("ports") or []
        if network.get("network_group_id"):
            validate_networking_changes(vm_records=planned_managed_vm_records(vm_name))

        cleanup_vm_runtime_definition(vm_name, network, ports, remove_storage=True)
        cleanup_local_vm_artifacts(
            vm_name,
            admin_private_key=state.get("admin_private_key"),
            vm_data_dir=state.get("vm_data_dir"),
        )
        if network.get("network_group_id"):
            reconcile_networking()
        elif is_libvirt_nat_network(network):
            reconcile_networking(policy_only=True)


def cleanup_vm_runtime_definition(vm_name, network, ports, remove_storage):
    """Remove the libvirt domain and network resources for a VM."""
    if vm_exists(vm_name):
        run(["virsh", "destroy", vm_name], sudo=True, check=False)
        undefine_cmd = ["virsh", "undefine", vm_name]
        if remove_storage:
            undefine_cmd.append("--remove-all-storage")
        run(undefine_cmd, sudo=True, check=False)

    if network.get("network_group_id"):
        if remove_storage:
            cleanup_vm_storage(vm_name)
        return

    if is_libvirt_nat_network(network):
        run(["virsh", "net-destroy", network["name"]], sudo=True, check=False)
        run(["virsh", "net-undefine", network["name"]], sudo=True, check=False)

        for bridge_name in {
            network.get("bridge_name"),
            default_nat_bridge_name(vm_name),
            legacy_nat_bridge_name(vm_name),
        }:
            if bridge_name and bridge_interface_exists(bridge_name):
                cleanup_bridge_interface(bridge_name)

    if remove_storage:
        cleanup_vm_storage(vm_name)
