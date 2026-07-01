Architecture
============

Package Layout
--------------

The Python package is split by responsibility:

+--------------------------------+---------------------------------------------+
| Module                         | Responsibility                              |
+================================+=============================================+
| ``homelab_vm_provisioner.cli`` | CLI parsing and high-level orchestration    |
+--------------------------------+---------------------------------------------+
| ``config``                     | Config loading and saved VM state           |
+--------------------------------+---------------------------------------------+
| ``managed_nftables``           | Managed nftables table rendering and apply  |
+--------------------------------+---------------------------------------------+
| ``network``                    | Network selection and libvirt discovery     |
+--------------------------------+---------------------------------------------+
| ``provision``                  | Template rendering and libvirt provisioning |
+--------------------------------+---------------------------------------------+
| ``reconciler``                 | Libvirt network and nftables reconciliation |
+--------------------------------+---------------------------------------------+
| ``system``                     | Shared subprocess helpers                   |
+--------------------------------+---------------------------------------------+

Testing
-------

- ``tests/`` contains both unit and integration coverage.
- ``tests/test_integration.py`` drives ``cli.main()`` through ``create``, ``destroy``, and ``ssh-admin`` while faking only the host-side commands.

Generated Artifacts
-------------------

- ``vm/data/<vm>/`` stores rendered cloud-init files by default.
- ``vm/state/<vm>.yaml`` stores teardown metadata and the resolved local artifact path for each VM.
- ``vm/keys/admin/`` stores generated admin SSH keypairs by default.
- ``.build/coverage/`` stores coverage data, XML, and HTML reports.
- ``docs/_build/html/`` stores generated HTML documentation.

Configuration
-------------

- ``vmctl.yaml`` sets the default VM data, state, user key, and admin key directories.
- ``vmctl.yaml`` also sets the default guest image URL, cached filename, and libvirt OS variant.
- ``paths.vm_data_dir`` lets each VM config override its local artifact directory.
- ``image`` settings in a VM config override the global guest image settings.
- The default ``image.os_variant`` is ``generic`` to avoid host-specific libosinfo failures.
- Both ``create`` and ``clone`` commands support reading configs from stdin when the config path is omitted, enabling database-driven and API-driven provisioning workflows.
- VM networking policy is rendered into application-owned ``hvp_filter``, ``hvp_nat``, and ``hvp_bridge_filter`` nftables tables.
- Same-bridge VM-to-VM traffic is filtered in the bridge family so same-subnet isolation works even when guests share one Linux bridge.
- Relative ``paths.vm_data_dir`` values resolve from the project root.
