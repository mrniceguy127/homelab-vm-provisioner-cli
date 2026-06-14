"""Helpers for the application-owned managed nftables backend."""

from __future__ import annotations

import os
import subprocess

from .system import capture_or_none, run, tool_exists

FILTER_TABLE = {"family": "inet", "name": "hvp_filter"}
NAT_TABLE = {"family": "ip", "name": "hvp_nat"}
BRIDGE_FILTER_TABLE = {"family": "bridge", "name": "hvp_bridge_filter"}


class ManagedNftablesApplyError(RuntimeError):
    """Raised when the managed nftables batch fails to apply."""

    def __init__(self, command, stderr_text="", stdout_text="", ruleset_text=""):
        self.details = {
            "code": "managed_nftables_apply_failed",
            "command": command,
            "stderr": stderr_text or None,
            "stdout": stdout_text or None,
            "ruleset_text": ruleset_text or None,
        }
        summary = stderr_text or stdout_text or "nft apply failed"
        super().__init__(summary)


def list_table(table_spec):
    """Return the current nft table text when present."""

    return capture_or_none(
        ["nft", "list", "table", table_spec["family"], table_spec["name"]],
        sudo=True,
    )


def current_tables():
    """Return the current managed nft table text keyed by logical table name."""

    return {
        "filter": list_table(FILTER_TABLE),
        "nat": list_table(NAT_TABLE),
        "bridge_filter": list_table(BRIDGE_FILTER_TABLE),
    }


def render_ruleset(plan, previous_tables=None):
    """Render one atomic nft batch script for the managed tables."""

    if previous_tables is None:
        previous_tables = current_tables()

    lines = []
    if previous_tables.get("filter") is not None:
        lines.append(f"delete table {FILTER_TABLE['family']} {FILTER_TABLE['name']}")
    if previous_tables.get("nat") is not None:
        lines.append(f"delete table {NAT_TABLE['family']} {NAT_TABLE['name']}")
    if previous_tables.get("bridge_filter") is not None:
        lines.append(
            f"delete table {BRIDGE_FILTER_TABLE['family']} {BRIDGE_FILTER_TABLE['name']}"
        )

    lines.extend(
        [
            f"table {FILTER_TABLE['family']} {FILTER_TABLE['name']} {{",
            "    chain forward {",
            "        type filter hook forward priority -10; policy accept;",
            *[f"        {rule}" for rule in plan["filter_rules"]["forward"]],
            "    }",
            "",
            "    chain input {",
            "        type filter hook input priority -10; policy accept;",
            *[f"        {rule}" for rule in plan["filter_rules"]["input"]],
            "    }",
            "}",
            "",
            f"table {NAT_TABLE['family']} {NAT_TABLE['name']} {{",
            "    chain prerouting {",
            "        type nat hook prerouting priority dstnat; policy accept;",
            *[f"        {rule}" for rule in plan["nat_rules"]["prerouting"]],
            "    }",
            "",
            "    chain postrouting {",
            "        type nat hook postrouting priority srcnat; policy accept;",
            *[f"        {rule}" for rule in plan["nat_rules"]["postrouting"]],
            "    }",
            "}",
            "",
            f"table {BRIDGE_FILTER_TABLE['family']} {BRIDGE_FILTER_TABLE['name']} {{",
            "    chain forward {",
            "        type filter hook forward priority -10; policy accept;",
            *[f"        {rule}" for rule in plan["bridge_filter_rules"]["forward"]],
            "    }",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _raise_on_failed_batch(command, ruleset_text, result):
    raise ManagedNftablesApplyError(
        command,
        stderr_text=(result.stderr or "").strip(),
        stdout_text=(result.stdout or "").strip(),
        ruleset_text=ruleset_text,
    )


def _prime_bridge_filtering_support(plan):
    """Best-effort kernel module prep for bridge-family nftables filtering."""

    if not plan.get("bridge_filter_rules", {}).get("forward"):
        return
    if not tool_exists("modprobe"):
        return

    for module_name in ("bridge", "br_netfilter", "nf_tables_bridge"):
        if os.geteuid() == 0:
            run(["modprobe", module_name], check=False)
        else:
            run(["modprobe", module_name], sudo=True, check=False)


def apply_ruleset(plan):
    """Replace the managed nft tables atomically."""

    previous_tables = current_tables()
    ruleset_text = render_ruleset(plan, previous_tables=previous_tables)
    _prime_bridge_filtering_support(plan)
    command = ["sudo", "nft", "-f", "-"]
    print("+", " ".join(command))
    result = subprocess.run(
        command,
        input=ruleset_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if result.returncode != 0:
        _raise_on_failed_batch(command, ruleset_text, result)

    return {
        "previous_tables": {
            name: value is not None for name, value in previous_tables.items()
        },
        "ruleset_text": ruleset_text,
    }


def verify_tables():
    """Return a lightweight verification snapshot for the managed tables."""

    filter_table = list_table(FILTER_TABLE)
    nat_table = list_table(NAT_TABLE)
    bridge_filter_table = list_table(BRIDGE_FILTER_TABLE)
    if filter_table is None or nat_table is None or bridge_filter_table is None:
        raise RuntimeError("Managed nftables tables were not present after apply")

    missing = []
    for chain_name in ("forward", "input"):
        if f"chain {chain_name}" not in filter_table:
            missing.append(f"{FILTER_TABLE['name']}.{chain_name}")
    for chain_name in ("prerouting", "postrouting"):
        if f"chain {chain_name}" not in nat_table:
            missing.append(f"{NAT_TABLE['name']}.{chain_name}")
    if "chain forward" not in bridge_filter_table:
        missing.append(f"{BRIDGE_FILTER_TABLE['name']}.forward")
    if missing:
        raise RuntimeError(f"Managed nftables chains missing after apply: {', '.join(missing)}")

    return {
        "filter": FILTER_TABLE,
        "nat": NAT_TABLE,
        "bridge_filter": BRIDGE_FILTER_TABLE,
        "filter_rules": filter_table.count("\n") + 1,
        "nat_rules": nat_table.count("\n") + 1,
        "bridge_filter_rules": bridge_filter_table.count("\n") + 1,
    }
