---
name: test-writer
description: Write unittest tests for Python CLI with libvirt mocking
---

# Python Test Writer

Write unittest tests following project patterns.

## Discovery Process

1. Find test examples: `grep_search("class Test", "tests/test_*.py")`
2. Read 2-3 test files to understand unittest structure
3. Apply patterns to new tests

## Key Constraints

- Framework: unittest (NOT pytest)
- Use `self.assertEqual()` not `assert`
- Mock all `libvirt.*` and `subprocess.*` calls
- Coverage: 85% minimum enforced via `./scripts/coverage`
- Location: `tests/test_<module>.py`

## Patterns to Discover

- `from unittest.mock import MagicMock, patch`
- `@patch('homelab_vm_provisioner.<module>.libvirt')`
- `class Test<ClassName>(unittest.TestCase):`
- Test names: `test_<function>_<scenario>()`

See [AGENTS.md](../AGENTS.md) for Python CLI testing conventions.
