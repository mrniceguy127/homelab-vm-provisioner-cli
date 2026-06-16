---
name: coverage-runner
description: Run and analyze Python test coverage
---

# Python Coverage Runner

Analyze test coverage with 85% enforcement.

## Commands

```bash
./scripts/coverage  # Run tests with 85% minimum enforcement
./scripts/test      # Run tests only
```

## Coverage Analysis

1. Run `./scripts/coverage`
2. Check output for uncovered lines
3. Identify missing tests
4. Write tests for gaps

Build fails if coverage < 85%.
