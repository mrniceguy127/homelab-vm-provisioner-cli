# Homelab VM Provisioner - Python CLI

Python CLI tool for provisioning and managing libvirt VMs with cloud-init and nftables firewall configuration.

## Architecture

### Core Components

- **CLI** (`cli.py`): Command-line interface using argparse
- **Provisioning** (`provision.py`): VM lifecycle management via libvirt
- **Configuration** (`config.py`): YAML configuration parsing
- **Networking** (`network.py`): Network bridge and interface management
- **Firewall** (`managed_nftables.py`): nftables rule generation and management
- **Reconciliation** (`reconciler.py`): State reconciliation and drift detection

### Technology Stack

- **Language**: Python 3.9+
- **Testing**: unittest (NOT pytest)
- **Coverage**: coverage.py with 85% minimum enforced
- **Documentation**: Sphinx + RST + Google-style docstrings
- **Linting**: ruff (E, F, I rules)
- **Dependencies**: libvirt-python, Jinja2, PyYAML

## Build and Test

### Commands

```bash
./vmctl provision <name>          # Provision a VM
./vmctl list                      # List all VMs
./vmctl stop <name>               # Stop a VM
./vmctl start <name>              # Start a VM
./vmctl destroy <name>            # Destroy a VM

./scripts/test                    # Run unittest suite
./scripts/coverage                # Run tests with coverage (85% enforced)
./scripts/lint                    # Run ruff linter
./scripts/docs-build              # Build Sphinx documentation
```

### Configuration

VMs are defined in `vmctl.yaml`:

```yaml
vms:
  - name: web-server
    memory: 2048
    cpu: 2
    networks:
      - default
    disk_size: 20G
```

Cloud-init templates are in `homelab_vm_provisioner/templates/`.

## Code Style

### Python Conventions

- Python 3.9+ compatible
- Google-style docstrings
- Type hints optional but encouraged
- 100 character line length
- Use `if __name__ == '__main__':` for entry points

### Testing Conventions

- **Framework**: unittest (NOT pytest)
- **Location**: `tests/test_<module>.py`
- **Coverage**: 85% minimum (enforced by build)
- **Mocking**: Mock libvirt and subprocess calls
- **Structure**: One TestCase class per module function/class

### Example Test

```python
import unittest
from unittest.mock import MagicMock, patch
from homelab_vm_provisioner.provision import provision_vm

class TestProvisionVM(unittest.TestCase):
    @patch('homelab_vm_provisioner.provision.libvirt')
    def test_provision_vm_success(self, mock_libvirt):
        """Test successful VM provisioning."""
        mock_conn = MagicMock()
        mock_domain = MagicMock()
        
        mock_libvirt.open.return_value = mock_conn
        mock_conn.defineXML.return_value = mock_domain
        
        result = provision_vm('test-vm', 2048, 2, ['default'])
        
        self.assertEqual(result['name'], 'test-vm')
        mock_domain.create.assert_called_once()
```

## Documentation

### Docstring Format (Google Style)

```python
def provision_vm(name, memory, cpu, networks):
    """Provision a new virtual machine.
    
    Creates a new VM with the specified configuration using libvirt.
    
    Args:
        name: VM hostname (alphanumeric, hyphens allowed)
        memory: Memory in MB (minimum 512)
        cpu: Number of vCPUs (1-16)
        networks: List of network names
    
    Returns:
        Dict with VM details (name, uuid, status)
    
    Raises:
        ValueError: If parameters are invalid
        RuntimeError: If libvirt operation fails
    
    Example:
        >>> result = provision_vm('web-01', 2048, 2, ['default'])
        >>> print(result['status'])
        running
    """
```

### Sphinx Documentation

- **Location**: `docs/`
- **Build**: `./scripts/docs-build`
- **Output**: `docs/_build/html/index.html`
- **Format**: RST files with code-block examples

## Common Patterns

### Error Handling

```python
def validate_config(config):
    """Validate VM configuration."""
    if not config.get('name'):
        raise ValueError("VM name is required")
    
    if config.get('memory', 0) < 512:
        raise ValueError("Memory must be at least 512 MB")
```

### libvirt Operations

```python
conn = libvirt.open('qemu:///system')
try:
    domain = conn.lookupByName(vm_name)
    domain.create()  # Start VM
finally:
    conn.close()  # Always close connection
```

### Cloud-init Templates

Uses Jinja2 templates in `homelab_vm_provisioner/templates/`:
- `base-user-data.yaml.j2` - Cloud-init user-data
- `meta-data.yaml.j2` - Cloud-init meta-data

## Specialized Agents

This project uses specialized agents for common development tasks:

### Available Agents

| Agent | Purpose | Usage |
|-------|---------|-------|
| test-writer | Write unittest tests | OpenCode: `@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/test-writer.agent.md` |
| coverage-runner | Analyze test coverage | OpenCode: `@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/coverage-runner.agent.md` |
| feature-developer | Implement new features | OpenCode: `@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/feature-developer.agent.md` |
| defect-fixer | Debug and fix bugs | OpenCode: `@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/defect-fixer.agent.md` |
| doc-writer | Write documentation | OpenCode: `@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/doc-writer.agent.md` |

### Platform Support

> **Platform Support**: OpenCode • GitHub Copilot • Cursor • Windsurf • Aider • Continue.dev

All agents work across major AI coding platforms. See [agents/README.md](agents/README.md) for details.

### How to Use

**OpenCode** (Most efficient):
```
@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/test-writer.agent.md Write tests for network.py
```

**GitHub Copilot**:
```
@test-writer Write tests for the provisioning module
```

**Cursor / Windsurf / Aider**:
Load the agent file and describe what you need.

## Key Gotchas

### Python

- **Virtual environment**: Scripts handle activation automatically
- **unittest not pytest**: Use `self.assertEqual()` not `assert`
- **libvirt mocking**: Always mock `libvirt.open()` in tests
- **Cloud-init templates**: YAML structure must be exact
- **Connection cleanup**: Always close libvirt connections in finally blocks

### Testing

- **Coverage enforcement**: Build fails if < 85%
- **Mock everything external**: libvirt, subprocess, file operations
- **Test class structure**: One TestCase per function/class
- **Descriptive names**: Use `test_<function>_<scenario>` pattern

### Documentation

- **Google-style docstrings**: Required for all public functions
- **RST for guides**: Use code-block directives with language
- **Sphinx autodoc**: Automatically generates API docs from docstrings
- **Build before commit**: Verify docs build without errors

## Integration with Other Projects

This Python CLI is used by:
- **homelab-vm-provisioner-api**: Node.js Express API wraps this CLI via subprocess
- **homelab-vm-provisioner-client**: React frontend calls API which calls this CLI

Communication flow:
```
React Client → Express API → Python CLI → libvirt
```

## Development Workflow

1. **Feature Development**: TDD approach (tests first, then implementation)
2. **Bug Fixes**: Add regression test, fix bug, verify test passes
3. **Documentation**: Update docstrings and RST docs before commit
4. **Coverage**: Always run `./scripts/coverage` before submitting
5. **Linting**: Run `./scripts/lint` to catch style issues
