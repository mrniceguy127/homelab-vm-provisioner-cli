"""Adapter services for external system interactions.

This module provides explicit boundaries between the functional core and
side-effectful operations. Each adapter encapsulates interactions with
external systems (filesystem, subprocess, libvirt, etc.).

These adapters follow the Adapter pattern, providing a stable interface
for side effects that can be easily tested with mocks or test doubles.
"""

import subprocess
from pathlib import Path
from typing import Optional

from .system import capture_or_none, run


class FileSystemAdapter:
    """Adapter for filesystem operations.
    
    Encapsulates all file I/O, providing a clear boundary for testing
    and a single place to inject file system mocks.
    """
    
    def __init__(self, base_path: Optional[Path] = None):
        """Initialize filesystem adapter.
        
        Args:
            base_path: Optional base path for relative operations.
        """
        self.base_path = base_path or Path.cwd()
    
    def read_text(self, path: Path) -> str:
        """Read text file contents.
        
        Args:
            path: File path to read.
            
        Returns:
            File contents as string.
        """
        return path.read_text(encoding="utf-8")
    
    def write_text(self, path: Path, content: str, mode: Optional[int] = None) -> None:
        """Write text content to file.
        
        Args:
            path: File path to write.
            content: Text content to write.
            mode: Optional file permissions.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if mode is not None:
            path.chmod(mode)
    
    def exists(self, path: Path) -> bool:
        """Check if path exists.
        
        Args:
            path: Path to check.
            
        Returns:
            True if path exists.
        """
        return path.exists()
    
    def mkdir(self, path: Path, mode: int = 0o755, parents: bool = True) -> None:
        """Create directory.
        
        Args:
            path: Directory path to create.
            mode: Directory permissions.
            parents: Create parent directories if needed.
        """
        path.mkdir(mode=mode, parents=parents, exist_ok=True)
    
    def remove(self, path: Path) -> None:
        """Remove file.
        
        Args:
            path: File path to remove.
        """
        if path.exists():
            path.unlink()
    
    def chmod(self, path: Path, mode: int) -> None:
        """Change file permissions.
        
        Args:
            path: File path.
            mode: Permission mode.
        """
        path.chmod(mode)


class SubprocessAdapter:
    """Adapter for subprocess execution.
    
    Wraps subprocess calls to provide a testable boundary and standardized
    error handling. All command execution should go through this adapter.
    """
    
    def run(self, cmd: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess:
        """Execute a command and wait for completion.
        
        Args:
            cmd: Command and arguments.
            sudo: Run with sudo.
            check: Raise on non-zero exit.
            
        Returns:
            CompletedProcess result.
            
        Raises:
            subprocess.CalledProcessError: If check=True and command fails.
        """
        return run(cmd, sudo=sudo, check=check)
    
    def capture(self, cmd: list[str], sudo: bool = False) -> Optional[str]:
        """Execute command and capture stdout, returning None on failure.
        
        Args:
            cmd: Command and arguments.
            sudo: Run with sudo.
            
        Returns:
            Stdout text or None if command failed.
        """
        return capture_or_none(cmd, sudo=sudo)
    
    def run_with_output(
        self, 
        cmd: list[str], 
        input_text: Optional[str] = None,
        sudo: bool = False
    ) -> subprocess.CompletedProcess:
        """Execute command with input and capture output.
        
        Args:
            cmd: Command and arguments.
            input_text: Text to send to stdin.
            sudo: Run with sudo.
            
        Returns:
            CompletedProcess with stdout and stderr.
        """
        if sudo and not cmd[0].startswith("sudo"):
            cmd = ["sudo"] + cmd
        
        print("+", " ".join(cmd))
        return subprocess.run(
            cmd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )


class NetworkQueryAdapter:
    """Adapter for querying host network state.
    
    Encapsulates interactions with the host network stack and libvirt
    networking. Pure functions can consume the text output from these
    queries without needing to execute subprocess calls themselves.
    """
    
    def __init__(self, subprocess_adapter: SubprocessAdapter):
        """Initialize network query adapter.
        
        Args:
            subprocess_adapter: Subprocess adapter for command execution.
        """
        self.subprocess = subprocess_adapter
    
    def get_routes(self) -> str:
        """Get host routing table as text.
        
        Returns:
            Output from 'ip route' command.
        """
        result = subprocess.run(
            ["ip", "route"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout
    
    def get_libvirt_networks(self) -> str:
        """Get all libvirt network definitions as XML.
        
        Returns:
            Concatenated XML from all networks.
        """
        result = subprocess.run(
            ["sudo", "virsh", "net-list", "--all", "--name"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        
        xml_parts = []
        for net_name in result.stdout.splitlines():
            net_name = net_name.strip()
            if not net_name:
                continue
            
            xml_result = subprocess.run(
                ["sudo", "virsh", "net-dumpxml", net_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            xml_parts.append(xml_result.stdout)
        
        return "\n".join(xml_parts)
    
    def list_network_names(self) -> list[str]:
        """List all libvirt network names.
        
        Returns:
            List of network names.
        """
        result = subprocess.run(
            ["sudo", "virsh", "net-list", "--all", "--name"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode != 0:
            return []
        
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class SSHKeyGenerator:
    """Service for SSH key generation.
    
    Encapsulates SSH key pair creation as a focused service with
    a clear responsibility.
    """
    
    def __init__(self, subprocess_adapter: SubprocessAdapter, fs_adapter: FileSystemAdapter):
        """Initialize SSH key generator.
        
        Args:
            subprocess_adapter: For executing ssh-keygen.
            fs_adapter: For reading generated public keys.
        """
        self.subprocess = subprocess_adapter
        self.fs = fs_adapter
    
    def ensure_keypair(self, key_path: Path, comment: str) -> tuple[Path, str]:
        """Ensure SSH keypair exists, creating if needed.
        
        Args:
            key_path: Path for private key.
            comment: SSH key comment.
            
        Returns:
            Tuple of (private_key_path, public_key_content).
        """
        pub_path = Path(str(key_path) + ".pub")
        
        if not self.fs.exists(key_path):
            # Ensure parent directory exists with secure permissions
            self.fs.mkdir(key_path.parent, mode=0o700, parents=True)
            
            # Generate key
            self.subprocess.run(
                [
                    "ssh-keygen",
                    "-t", "ed25519",
                    "-f", str(key_path),
                    "-N", "",
                    "-C", comment,
                ]
            )
            
            # Fail fast if ssh-keygen didn't create the expected files
            if not self.fs.exists(key_path):
                raise FileNotFoundError(f"ssh-keygen failed to create private key: {key_path}")
            if not self.fs.exists(pub_path):
                raise FileNotFoundError(f"ssh-keygen failed to create public key: {pub_path}")
        
        # Set secure permissions
        self.fs.chmod(key_path, 0o600)
        self.fs.chmod(pub_path, 0o644)
        
        public_key = self.fs.read_text(pub_path).strip()
        return key_path, public_key
