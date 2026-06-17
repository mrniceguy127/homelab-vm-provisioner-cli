"""Service layer for VM provisioning workflows.

This module contains service classes that orchestrate provisioning operations
by combining pure functions (from core.py) with side effects (from adapters.py).

Services follow these principles:
- Accept injected dependencies (adapters, config)
- Delegate calculations to pure functions
- Use adapters for all side effects
- Return simple values or raise explicit exceptions
"""

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .adapters import FileSystemAdapter, NetworkQueryAdapter, SSHKeyGenerator, SubprocessAdapter
from .constants import ADMIN_USER, IMG_DIR
from .core import (
    build_cloud_init_context,
    find_free_subnet,
)
from .domain import SubnetAllocation


class TemplateService:
    """Service for rendering cloud-init templates.
    
    Uses the Strategy pattern - the template engine (Jinja2) is the
    interchangeable strategy, and this service provides the stable interface.
    """
    
    def __init__(self, template_dir: Path, fs_adapter: FileSystemAdapter):
        """Initialize template service.
        
        Args:
            template_dir: Directory containing Jinja2 templates.
            fs_adapter: Filesystem adapter for writing rendered output.
        """
        self.template_dir = template_dir
        self.fs = fs_adapter
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))
    
    def render_cloud_init(
        self, 
        context: dict, 
        template_name: str, 
        output_dir: Path
    ) -> tuple[Path, Path]:
        """Render cloud-init user-data and meta-data templates.
        
        Args:
            context: Template variables.
            template_name: Base template name (without suffix).
            output_dir: Directory for rendered files.
            
        Returns:
            Tuple of (user_data_path, meta_data_path).
        """
        user_data = self.env.get_template(f"{template_name}-user-data.yaml.j2").render(**context)
        meta_data = self.env.get_template("meta-data.yaml.j2").render(**context)
        
        self.fs.mkdir(output_dir)
        
        user_data_path = output_dir / "user-data"
        meta_data_path = output_dir / "meta-data"
        
        self.fs.write_text(user_data_path, user_data)
        self.fs.write_text(meta_data_path, meta_data)
        
        return user_data_path, meta_data_path


class ImageService:
    """Service for managing cloud images.
    
    Handles downloading and preparing base cloud images for VM provisioning.
    """
    
    def __init__(self, subprocess_adapter: SubprocessAdapter, fs_adapter: FileSystemAdapter):
        """Initialize image service.
        
        Args:
            subprocess_adapter: For executing image downloads.
            fs_adapter: For checking image existence.
        """
        self.subprocess = subprocess_adapter
        self.fs = fs_adapter
    
    def ensure_base_image(self, image_name: str, image_url: str) -> Path:
        """Ensure base cloud image exists locally.
        
        Args:
            image_name: Local filename for the image.
            image_url: Download URL.
            
        Returns:
            Path to the local base image.
        """
        self.fs.mkdir(IMG_DIR)
        base_img = IMG_DIR / image_name
        
        if not self.fs.exists(base_img):
            self.subprocess.run(
                ["wget", "-O", str(base_img), image_url],
                sudo=True
            )
        
        return base_img


class VMDiskService:
    """Service for VM disk operations.
    
    Handles qcow2 disk creation, copying, and manipulation using qemu-img.
    """
    
    def __init__(self, subprocess_adapter: SubprocessAdapter, fs_adapter: FileSystemAdapter):
        """Initialize VM disk service.
        
        Args:
            subprocess_adapter: For executing qemu-img commands.
            fs_adapter: For checking disk existence.
        """
        self.subprocess = subprocess_adapter
        self.fs = fs_adapter
    
    def create_backed_disk(
        self, 
        disk_path: Path, 
        base_image: Path, 
        size_gb: int
    ) -> Path:
        """Create a qcow2 VM disk backed by a base image.
        
        Args:
            disk_path: Path for the new VM disk.
            base_image: Base image to use as backing file.
            size_gb: Disk size in gibibytes.
            
        Returns:
            Path to the created disk.
        """
        if not self.fs.exists(disk_path):
            self.subprocess.run([
                "qemu-img", "create",
                "-f", "qcow2",
                "-F", "qcow2",
                "-b", str(base_image),
                str(disk_path),
                f"{size_gb}G"
            ])
        
        return disk_path
    
    def copy_disk(self, source: Path, destination: Path) -> Path:
        """Copy a qcow2 disk image.
        
        Args:
            source: Source disk path.
            destination: Destination disk path.
            
        Returns:
            Path to the copied disk.
        """
        self.subprocess.run([
            "qemu-img", "convert",
            "-f", "qcow2",
            "-O", "qcow2",
            str(source),
            str(destination)
        ])
        return destination


class SeedISOService:
    """Service for creating cloud-init seed ISOs.
    
    Wraps genisoimage/mkisofs to create NoCloud seed media.
    """
    
    def __init__(self, subprocess_adapter: SubprocessAdapter):
        """Initialize seed ISO service.
        
        Args:
            subprocess_adapter: For executing ISO creation tools.
        """
        self.subprocess = subprocess_adapter
    
    def create(
        self, 
        iso_path: Path, 
        user_data_path: Path, 
        meta_data_path: Path
    ) -> Path:
        """Create a cloud-init seed ISO.
        
        Args:
            iso_path: Output ISO path.
            user_data_path: cloud-init user-data file.
            meta_data_path: cloud-init meta-data file.
            
        Returns:
            Path to the created ISO.
        """
        self.subprocess.run([
            "genisoimage",
            "-output", str(iso_path),
            "-volid", "cidata",
            "-joliet",
            "-rock",
            str(user_data_path),
            str(meta_data_path),
        ])
        return iso_path


class NetworkAllocationService:
    """Service for allocating network configurations.
    
    Combines network query adapter (for side effects) with pure allocation
    logic (from core.py) to select available subnets.
    """
    
    def __init__(self, network_query: NetworkQueryAdapter):
        """Initialize network allocation service.
        
        Args:
            network_query: Adapter for querying network state.
        """
        self.network_query = network_query
    
    def allocate_nat_subnet(self) -> SubnetAllocation:
        """Allocate an unused NAT subnet.
        
        Returns:
            SubnetAllocation with selected network parameters.
            
        Raises:
            RuntimeError: If no free subnet is available.
        """
        routes = self.network_query.get_routes()
        networks = self.network_query.get_libvirt_networks()
        return find_free_subnet(routes, networks)


class VMProvisioningFacade:
    """Facade for complete VM provisioning workflows.
    
    This facade provides a simplified, high-level interface for VM provisioning
    by coordinating multiple services. It follows the Facade pattern to hide
    the complexity of individual services and their interactions.
    
    This is the main interface that CLI commands should use.
    """
    
    def __init__(
        self,
        template_service: TemplateService,
        image_service: ImageService,
        disk_service: VMDiskService,
        seed_service: SeedISOService,
        network_service: NetworkAllocationService,
        key_generator: SSHKeyGenerator,
    ):
        """Initialize provisioning facade.
        
        Args:
            template_service: For rendering cloud-init templates.
            image_service: For managing base images.
            disk_service: For VM disk operations.
            seed_service: For creating seed ISOs.
            network_service: For network allocation.
            key_generator: For SSH key generation.
        """
        self.templates = template_service
        self.images = image_service
        self.disks = disk_service
        self.seeds = seed_service
        self.networks = network_service
        self.keys = key_generator
    
    def prepare_admin_keypair(self, vm_name: str, admin_key_dir: Path) -> tuple[Path, str]:
        """Prepare admin SSH keypair for VM.
        
        Args:
            vm_name: VM name for key identification.
            admin_key_dir: Directory for admin keys.
            
        Returns:
            Tuple of (private_key_path, public_key_content).
        """
        key_path = admin_key_dir / f"{vm_name}_admin_ed25519"
        return self.keys.ensure_keypair(key_path, f"admin-{vm_name}")
    
    def prepare_vm_artifacts(
        self,
        vm_name: str,
        vm_user: str,
        user_public_key: Optional[str],
        admin_public_key: str,
        allow_sudo: bool,
        packages: tuple[str, ...],
        dns_resolvers: tuple[str, ...],
        setup_script_content: Optional[str],
        image_name: str,
        image_url: str,
        disk_gb: int,
        vm_data_dir: Path,
    ) -> tuple[Path, Path, Path]:
        """Prepare all local artifacts for VM provisioning.
        
        This method orchestrates the preparation of base image, VM disk,
        cloud-init templates, and seed ISO.
        
        Args:
            vm_name: VM name.
            vm_user: Tenant username.
            user_public_key: Tenant SSH public key.
            admin_public_key: Admin SSH public key.
            allow_sudo: Grant sudo to tenant.
            packages: Packages to install.
            dns_resolvers: DNS servers.
            setup_script_content: Optional setup script.
            image_name: Base image filename.
            image_url: Base image download URL.
            disk_gb: VM disk size.
            vm_data_dir: Directory for VM artifacts.
            
        Returns:
            Tuple of (vm_disk_path, seed_iso_path, base_image_path).
        """
        # Ensure base image
        base_img = self.images.ensure_base_image(image_name, image_url)
        
        # Create VM disk
        vm_disk = vm_data_dir / f"{vm_name}.qcow2"
        self.disks.create_backed_disk(vm_disk, base_img, disk_gb)
        
        # Build cloud-init context
        context = build_cloud_init_context(
            vm_name=vm_name,
            admin_user=ADMIN_USER,
            admin_public_key=admin_public_key,
            vm_user=vm_user,
            vm_public_key=user_public_key,
            allow_sudo=allow_sudo,
            packages=packages,
            dns_resolvers=dns_resolvers,
            setup_script_content=setup_script_content,
        )
        
        # Render templates
        user_data_path, meta_data_path = self.templates.render_cloud_init(
            context, "default", vm_data_dir
        )
        
        # Create seed ISO
        seed_iso = vm_data_dir / f"{vm_name}-seed.iso"
        self.seeds.create(seed_iso, user_data_path, meta_data_path)
        
        return vm_disk, seed_iso, base_img
