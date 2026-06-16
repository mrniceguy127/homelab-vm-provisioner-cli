---
name: feature-developer
description: Implement new Python CLI features
---

# Python Feature Developer

Implement new VM provisioning features following project conventions.

## Discovery Process

1. Examine existing code in `homelab_vm_provisioner/*.py`
2. Understand libvirt usage, error handling, cloud-init patterns
3. Check how features integrate (provision → network → nftables)
4. Apply patterns to new feature

## Key Constraints

- Python 3.9+
- Google-style docstrings
- Mock libvirt in tests
- Close libvirt connections (use try/finally)
- Test new features (85% coverage enforced)

See [AGENTS.md](../AGENTS.md) for architecture and conventions.
