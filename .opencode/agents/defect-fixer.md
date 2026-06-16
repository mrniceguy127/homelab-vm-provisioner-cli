---
name: defect-fixer
description: Debug and fix Python CLI bugs
---

# Python Defect Fixer

Debug and fix bugs in the Python CLI.

## Debugging Process

1. Reproduce the issue with `./vmctl`
2. Check error messages and tracebacks
3. Examine relevant code in `homelab_vm_provisioner/`
4. Check libvirt interactions and mocking
5. Fix and write regression test

## Common Issues

- Libvirt connection failures
- Cloud-init template errors
- Network/nftables configuration problems
- Config parsing issues
- Resource cleanup (unclosed connections)

See [AGENTS.md](../AGENTS.md) for troubleshooting.
