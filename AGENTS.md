# Homelab VM Provisioner - Python CLI

Python CLI for provisioning and managing libvirt VMs with cloud-init and nftables.

## Quick Start

```bash
./vmctl provision <name>       # Provision VM
./vmctl list                   # List VMs
./scripts/test                 # Run tests
./scripts/coverage             # Test with 85% enforcement
./scripts/lint                 # Ruff linting
./scripts/docs-build           # Build Sphinx docs
```

## Project Structure

```
homelab_vm_provisioner/
├── cli.py              # CLI commands (argparse)
├── provision.py        # VM lifecycle management
├── config.py           # YAML config parsing
├── network.py          # Network management
├── managed_nftables.py # Firewall rules
├── reconciler.py       # State reconciliation
└── templates/          # Cloud-init Jinja2 templates

tests/
├── test_cli.py         # CLI tests
├── test_provision.py   # Provisioning tests
└── ...                 # Other test modules
```

## Code Style

**Language**: Python 3.9+  
**Testing**: unittest (NOT pytest)  
**Coverage**: 85% minimum (ENFORCED - build fails if below)  
**Linting**: ruff (E, F, I rules)  
**Docs**: Google-style docstrings + Sphinx RST

**Key Patterns**:
- Google-style docstrings for all public functions
- Mock libvirt and subprocess calls in tests
- Use `unittest.TestCase` with `self.assertEqual()`
- Always close libvirt connections (use try/finally)

## Firewall / nftables Invariants

- Do not introduce firewalld.
- nftables is the managed firewall source of truth.
- Only modify owned/managed nftables tables and chains.
- Do not patch foreign-owned chains.
- Generated rules must be deterministic.
- Before changing packet filtering, identify packet path, hook, source, destination, NAT ordering, and earlier accept/drop rules.
- Prefer tests around rendered nftables output over tests that require root, real bridges, or live nftables state.

## AI Agents

Project-specific OpenCode agents live in `.opencode/agents/`.

### Usage

```bash
# Direct invocation (recommended)
@.opencode/agents/test-writer.md Write tests for provision.py
@.opencode/agents/coverage-runner.md Check coverage
```

### Available Agents

- **test-writer.md** - unittest + libvirt mocking
- **coverage-runner.md** - 85% enforcement
- **feature-developer.md** - CLI + libvirt patterns
- **defect-fixer.md** - Python debugging
- **doc-writer.md** - Sphinx + Google docstrings

## Testing Essentials

**Framework**: unittest (NOT pytest - critical!)  
**Coverage**: 85% enforced (build fails if below)  
**Mocking**: Mock all `libvirt.*` and `subprocess.*` calls  
**Pattern**: One `TestCase` class per function/class

**Pattern Discovery**: Before writing tests, inspect nearby existing tests and follow their style.

## Documentation Sources

Generated CLI/API docs and source doc comments are the source of truth for detailed command behavior and public function docs.

Before editing CLI docs or public behavior:
- Inspect the Python project's docs configuration and existing doc comments.
- Follow the repo's existing documentation layout.
- Update source docs/comments rather than only generated output.
- Run `./scripts/docs-build` to build Sphinx documentation.
- Do not duplicate full generated documentation in `AGENTS.md`.

## Common Issues

- Mutable default arguments (`def func(arg=[]):` is wrong)
- Broad exception handling
- Missing input validation
- libvirt connection leaks
- Using pytest patterns instead of unittest
