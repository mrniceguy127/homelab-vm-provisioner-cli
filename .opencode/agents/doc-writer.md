---
name: doc-writer
description: Write Sphinx documentation for Python CLI
---

# Python Documentation Writer

Write Sphinx RST documentation with Google-style docstrings.

## Discovery Process

1. Find examples: `grep_search("Args:|Returns:|Raises:", "homelab_vm_provisioner/*.py")`
2. Understand Google-style docstring format
3. Apply to undocumented functions

## Documentation Standards

- Google-style docstrings (Args, Returns, Raises)
- Sphinx RST for architecture docs
- Build docs: `./scripts/docs-build`

See [AGENTS.md](../AGENTS.md) for documentation standards.
