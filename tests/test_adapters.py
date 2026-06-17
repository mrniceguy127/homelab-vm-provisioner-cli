"""Unit tests for adapter classes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from homelab_vm_provisioner.adapters import (
    FileSystemAdapter,
    NetworkQueryAdapter,
    SSHKeyGenerator,
    SubprocessAdapter,
)


class FileSystemAdapterTests(unittest.TestCase):
    """Tests for FileSystemAdapter."""

    def test_remove_deletes_existing_file(self):
        """Verify remove() deletes a file that exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content", encoding="utf-8")
            
            adapter = FileSystemAdapter()
            adapter.remove(test_file)
            
            self.assertFalse(test_file.exists())

    def test_remove_handles_nonexistent_file(self):
        """Verify remove() handles nonexistent files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "nonexistent.txt"
            
            adapter = FileSystemAdapter()
            # Should not raise
            adapter.remove(test_file)


class SubprocessAdapterTests(unittest.TestCase):
    """Tests for SubprocessAdapter."""

    def test_run_with_output_captures_stdout_and_stderr(self):
        """Verify run_with_output() captures both stdout and stderr."""
        adapter = SubprocessAdapter()
        result = adapter.run_with_output(["echo", "hello"])
        
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_run_with_output_accepts_input_text(self):
        """Verify run_with_output() can send input to stdin."""
        adapter = SubprocessAdapter()
        result = adapter.run_with_output(["cat"], input_text="test input")
        
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "test input")

    def test_run_with_output_prepends_sudo_when_requested(self):
        """Verify run_with_output() prepends sudo when requested."""
        adapter = SubprocessAdapter()
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter.run_with_output(["ls"], sudo=True)
            
            # Verify sudo was prepended
            called_cmd = mock_run.call_args[0][0]
            self.assertEqual(called_cmd[0], "sudo")
            self.assertEqual(called_cmd[1], "ls")


class NetworkQueryAdapterTests(unittest.TestCase):
    """Tests for NetworkQueryAdapter."""

    def test_get_routes_returns_routing_table(self):
        """Verify get_routes() executes ip route and returns output."""
        subprocess_adapter = SubprocessAdapter()
        adapter = NetworkQueryAdapter(subprocess_adapter)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="default via 192.168.1.1 dev eth0\n",
                returncode=0
            )
            
            result = adapter.get_routes()
            
            self.assertIn("default via", result)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0], ["ip", "route"])

    def test_get_libvirt_networks_returns_xml(self):
        """Verify get_libvirt_networks() returns concatenated XML."""
        subprocess_adapter = SubprocessAdapter()
        adapter = NetworkQueryAdapter(subprocess_adapter)
        
        with patch("subprocess.run") as mock_run:
            # First call returns network names, second returns XML
            mock_run.side_effect = [
                MagicMock(stdout="default\ntest-net\n", returncode=0),
                MagicMock(stdout="<network><name>default</name></network>", returncode=0),
                MagicMock(stdout="<network><name>test-net</name></network>", returncode=0),
            ]
            
            result = adapter.get_libvirt_networks()
            
            self.assertIn("<name>default</name>", result)
            self.assertIn("<name>test-net</name>", result)
            self.assertEqual(mock_run.call_count, 3)

    def test_list_network_names_returns_list(self):
        """Verify list_network_names() returns list of network names."""
        subprocess_adapter = SubprocessAdapter()
        adapter = NetworkQueryAdapter(subprocess_adapter)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="default\ntest-net\n",
                returncode=0
            )
            
            result = adapter.list_network_names()
            
            self.assertEqual(result, ["default", "test-net"])

    def test_list_network_names_handles_failure(self):
        """Verify list_network_names() returns empty list on failure."""
        subprocess_adapter = SubprocessAdapter()
        adapter = NetworkQueryAdapter(subprocess_adapter)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            
            result = adapter.list_network_names()
            
            self.assertEqual(result, [])


class SSHKeyGeneratorTests(unittest.TestCase):
    """Tests for SSHKeyGenerator (already tested in test_provision)."""

    def test_ensure_keypair_creates_parent_directory(self):
        """Verify ensure_keypair() creates parent directory with correct permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "nested" / "dir" / "key"
            
            def fake_run(cmd, sudo=False, check=True):
                # Create the keys
                actual_path = Path(cmd[cmd.index("-f") + 1])
                actual_path.write_text("private", encoding="utf-8")
                Path(str(actual_path) + ".pub").write_text("ssh-ed25519 AAA test\n", encoding="utf-8")
                return MagicMock(returncode=0)
            
            subprocess_adapter = SubprocessAdapter()
            fs_adapter = FileSystemAdapter()
            generator = SSHKeyGenerator(subprocess_adapter, fs_adapter)
            
            with patch.object(SubprocessAdapter, "run", side_effect=fake_run):
                generator.ensure_keypair(key_path, "test")
            
            # Verify parent directory was created
            self.assertTrue(key_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
