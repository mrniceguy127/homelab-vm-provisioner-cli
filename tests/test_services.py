"""Unit tests for service layer classes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from homelab_vm_provisioner.adapters import (
    FileSystemAdapter,
    NetworkQueryAdapter,
    SSHKeyGenerator,
    SubprocessAdapter,
)
from homelab_vm_provisioner.domain import SubnetAllocation
from homelab_vm_provisioner.services import (
    ImageService,
    NetworkAllocationService,
    SeedISOService,
    TemplateService,
    VMDiskService,
    VMProvisioningFacade,
)


class TemplateServiceTests(unittest.TestCase):
    """Tests for TemplateService."""

    def test_render_cloud_init_creates_user_and_meta_data(self):
        """Verify render_cloud_init() creates both user-data and meta-data files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(__file__).parent.parent / "homelab_vm_provisioner" / "templates"
            output_dir = Path(tmpdir) / "output"
            
            fs_adapter = FileSystemAdapter()
            service = TemplateService(templates_dir, fs_adapter)
            
            context = {
                "vm_name": "test-vm",
                "admin_user": "vmadmin",
                "admin_public_key": "ssh-ed25519 AAA admin",
                "vm_user": "tenant",
                "vm_public_key": "ssh-ed25519 BBB tenant",
                "vm_sudo": "false",
                "packages": ["htop", "vim"],
                "dns_resolvers": ("1.1.1.1", "8.8.8.8"),
                "setup_script_content": None,
            }
            
            user_data_path, meta_data_path = service.render_cloud_init(
                context, "base", output_dir
            )
            
            self.assertTrue(user_data_path.exists())
            self.assertTrue(meta_data_path.exists())
            self.assertEqual(user_data_path.name, "user-data")
            self.assertEqual(meta_data_path.name, "meta-data")
            
            # Verify content was rendered
            user_data = user_data_path.read_text()
            self.assertIn("test-vm", user_data)
            self.assertIn("tenant", user_data)


class ImageServiceTests(unittest.TestCase):
    """Tests for ImageService."""

    def test_ensure_base_image_downloads_if_missing(self):
        """Verify ensure_base_image() downloads image when it doesn't exist."""
        subprocess_adapter = SubprocessAdapter()
        fs_adapter = FileSystemAdapter()
        
        with patch.object(FileSystemAdapter, "exists", return_value=False):
            with patch.object(FileSystemAdapter, "mkdir"):
                with patch.object(SubprocessAdapter, "run") as mock_run:
                    service = ImageService(subprocess_adapter, fs_adapter)
                    _ = service.ensure_base_image("focal.img", "http://example.com/focal.img")
                    
                    # Verify wget was called
                    mock_run.assert_called_once()
                    call_args = mock_run.call_args[0][0]
                    self.assertEqual(call_args[0], "wget")
                    self.assertIn("http://example.com/focal.img", call_args)

    def test_ensure_base_image_skips_download_if_exists(self):
        """Verify ensure_base_image() skips download when image exists."""
        subprocess_adapter = SubprocessAdapter()
        fs_adapter = FileSystemAdapter()
        
        with patch.object(FileSystemAdapter, "exists", return_value=True):
            with patch.object(FileSystemAdapter, "mkdir"):
                with patch.object(SubprocessAdapter, "run") as mock_run:
                    service = ImageService(subprocess_adapter, fs_adapter)
                    _ = service.ensure_base_image("focal.img", "http://example.com/focal.img")
                    
                    # Verify wget was NOT called
                    mock_run.assert_not_called()


class VMDiskServiceTests(unittest.TestCase):
    """Tests for VMDiskService."""

    def test_create_backed_disk_creates_qcow2_with_backing_file(self):
        """Verify create_backed_disk() creates a qcow2 disk with backing file."""
        subprocess_adapter = SubprocessAdapter()
        fs_adapter = FileSystemAdapter()
        
        with patch.object(FileSystemAdapter, "exists", return_value=False):
            with patch.object(SubprocessAdapter, "run") as mock_run:
                service = VMDiskService(subprocess_adapter, fs_adapter)
                
                disk_path = Path("/tmp/test.qcow2")
                base_image = Path("/tmp/base.qcow2")
                
                _ = service.create_backed_disk(disk_path, base_image, 20)
                
                # Verify qemu-img create was called
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                self.assertEqual(call_args[0], "qemu-img")
                self.assertEqual(call_args[1], "create")
                self.assertIn("-b", call_args)
                self.assertIn("20G", call_args)

    def test_create_backed_disk_skips_if_exists(self):
        """Verify create_backed_disk() skips creation if disk exists."""
        subprocess_adapter = SubprocessAdapter()
        fs_adapter = FileSystemAdapter()
        
        with patch.object(FileSystemAdapter, "exists", return_value=True):
            with patch.object(SubprocessAdapter, "run") as mock_run:
                service = VMDiskService(subprocess_adapter, fs_adapter)
                
                disk_path = Path("/tmp/test.qcow2")
                base_image = Path("/tmp/base.qcow2")
                
                _ = service.create_backed_disk(disk_path, base_image, 20)
                
                # Verify qemu-img was NOT called
                mock_run.assert_not_called()

    def test_copy_disk_converts_qcow2(self):
        """Verify copy_disk() converts qcow2 disk."""
        subprocess_adapter = SubprocessAdapter()
        fs_adapter = FileSystemAdapter()
        
        with patch.object(SubprocessAdapter, "run") as mock_run:
            service = VMDiskService(subprocess_adapter, fs_adapter)
            
            source = Path("/tmp/source.qcow2")
            dest = Path("/tmp/dest.qcow2")
            
            result = service.copy_disk(source, dest)
            
            # Verify qemu-img convert was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            self.assertEqual(call_args[0], "qemu-img")
            self.assertEqual(call_args[1], "convert")
            self.assertEqual(result, dest)


class SeedISOServiceTests(unittest.TestCase):
    """Tests for SeedISOService."""

    def test_create_generates_seed_iso(self):
        """Verify create() generates a seed ISO with genisoimage."""
        subprocess_adapter = SubprocessAdapter()
        
        with patch.object(SubprocessAdapter, "run") as mock_run:
            service = SeedISOService(subprocess_adapter)
            
            iso_path = Path("/tmp/seed.iso")
            user_data = Path("/tmp/user-data")
            meta_data = Path("/tmp/meta-data")
            
            result_path = service.create(iso_path, user_data, meta_data)
            
            # Verify genisoimage was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            self.assertEqual(call_args[0], "genisoimage")
            self.assertIn("-volid", call_args)
            self.assertIn("cidata", call_args)
            self.assertEqual(result_path, iso_path)


class NetworkAllocationServiceTests(unittest.TestCase):
    """Tests for NetworkAllocationService."""

    def test_allocate_nat_subnet_returns_subnet_allocation(self):
        """Verify allocate_nat_subnet() returns SubnetAllocation."""
        mock_network_query = Mock(spec=NetworkQueryAdapter)
        mock_network_query.get_routes.return_value = "default via 192.168.1.1\n"
        mock_network_query.get_libvirt_networks.return_value = "<network></network>"
        
        service = NetworkAllocationService(mock_network_query)
        
        result = service.allocate_nat_subnet()
        
        # Verify result is a SubnetAllocation
        self.assertIsInstance(result, SubnetAllocation)
        mock_network_query.get_routes.assert_called_once()
        mock_network_query.get_libvirt_networks.assert_called_once()


class VMProvisioningFacadeTests(unittest.TestCase):
    """Tests for VMProvisioningFacade."""

    def test_prepare_admin_keypair_generates_keypair(self):
        """Verify prepare_admin_keypair() generates SSH keypair."""
        mock_key_gen = Mock(spec=SSHKeyGenerator)
        mock_key_gen.ensure_keypair.return_value = (
            Path("/keys/test_admin_ed25519"),
            "ssh-ed25519 AAA admin"
        )
        
        facade = VMProvisioningFacade(
            template_service=Mock(),
            image_service=Mock(),
            disk_service=Mock(),
            seed_service=Mock(),
            network_service=Mock(),
            key_generator=mock_key_gen,
        )
        
        key_path, pub_key = facade.prepare_admin_keypair("test", Path("/keys"))
        
        self.assertEqual(key_path, Path("/keys/test_admin_ed25519"))
        self.assertEqual(pub_key, "ssh-ed25519 AAA admin")
        mock_key_gen.ensure_keypair.assert_called_once()

    def test_prepare_vm_artifacts_orchestrates_all_services(self):
        """Verify prepare_vm_artifacts() coordinates all provisioning services."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vm_data_dir = Path(tmpdir) / "vm"
            
            # Mock all services
            mock_template = Mock(spec=TemplateService)
            mock_template.render_cloud_init.return_value = (
                vm_data_dir / "user-data",
                vm_data_dir / "meta-data"
            )
            
            mock_image = Mock(spec=ImageService)
            mock_image.ensure_base_image.return_value = Path("/images/base.qcow2")
            
            mock_disk = Mock(spec=VMDiskService)
            mock_disk.create_backed_disk.return_value = vm_data_dir / "test.qcow2"
            
            mock_seed = Mock(spec=SeedISOService)
            mock_seed.create.return_value = vm_data_dir / "test-seed.iso"
            
            facade = VMProvisioningFacade(
                template_service=mock_template,
                image_service=mock_image,
                disk_service=mock_disk,
                seed_service=mock_seed,
                network_service=Mock(),
                key_generator=Mock(),
            )
            
            vm_disk, seed_iso, base_img = facade.prepare_vm_artifacts(
                vm_name="test",
                vm_user="tenant",
                user_public_key="ssh-ed25519 BBB tenant",
                admin_public_key="ssh-ed25519 AAA admin",
                allow_sudo=False,
                packages=("htop",),
                dns_resolvers=("1.1.1.1",),
                setup_script_content=None,
                image_name="focal.img",
                image_url="http://example.com/focal.img",
                disk_gb=20,
                vm_data_dir=vm_data_dir,
            )
            
            # Verify all services were called
            mock_image.ensure_base_image.assert_called_once_with("focal.img", "http://example.com/focal.img")
            mock_disk.create_backed_disk.assert_called_once()
            mock_template.render_cloud_init.assert_called_once()
            mock_seed.create.assert_called_once()
            
            # Verify return values
            self.assertEqual(vm_disk, vm_data_dir / "test.qcow2")
            self.assertEqual(seed_iso, vm_data_dir / "test-seed.iso")
            self.assertEqual(base_img, Path("/images/base.qcow2"))


if __name__ == "__main__":
    unittest.main()
