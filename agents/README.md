# Python CLI Specialist Agents

This directory contains specialist agents for the homelab-vm-provisioner Python CLI project.

## Agents

- **test-writer.agent.md** - Write unittest tests with libvirt mocking
- **coverage-runner.agent.md** - Run coverage analysis (85% minimum enforced)
- **feature-developer.agent.md** - Implement CLI commands and modules
- **defect-fixer.agent.md** - Debug and fix Python bugs
- **doc-writer.agent.md** - Write Google-style docstrings and Sphinx docs

## Technology Stack

- **Language**: Python 3.9+
- **Testing**: unittest (NOT pytest)
- **Coverage**: coverage.py with 85% minimum enforced
- **Documentation**: Sphinx + RST + Google-style docstrings
- **Linting**: ruff (E, F, I rules)
- **Main Dependencies**: libvirt-python, Jinja2, PyYAML

## Usage

**OpenCode**:
```
@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/test-writer.agent.md
@homelab-vm-provisioner-api/homelab-vm-provisioner/agents/coverage-runner.agent.md
```

These agents work independently or can be invoked by orchestrators in the root `agents/` directory.
