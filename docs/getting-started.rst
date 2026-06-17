Getting Started
===============

User Setup
----------

.. code-block:: bash

   ./setup

Common Commands
---------------

Create from a file:

.. code-block:: bash

   ./vmctl create configs/devbox.yaml

Create from stdin (useful for database-driven configs):

.. code-block:: bash

   cat configs/devbox.yaml | ./vmctl create
   
   # Or from heredoc
   ./vmctl create <<EOF
   vm:
     name: demo
     user: testuser
     ram_mb: 2048
     vcpus: 2
     disk_gb: 20
   
   network:
     mode: nat-auto
   EOF
   
   # Or from database/API
   python generate_config.py --id=123 | ./vmctl create

Clone a VM:

.. code-block:: bash

   ./vmctl clone source-vm configs/new-vm.yaml
   
   # Or from stdin (requires vm.name and vm.user in config)
   cat configs/new-vm.yaml | ./vmctl clone source-vm

Destroy a VM:

.. code-block:: bash

   ./vmctl destroy devbox

SSH as admin:

.. code-block:: bash

   ./vmssh-admin devbox

Developer Setup
---------------

.. code-block:: bash

   ./setup --dev
   ./test

``./test`` runs lint, the Python test suite, and coverage.

Project-wide default data paths live in ``vmctl.yaml``.

By default:

- local VM artifacts are written under ``vm/data/<vm>/``
- persisted state is tracked in ``vm/state/<vm>.yaml``
- user public keys are resolved from ``vm/keys/users/``
- generated admin keys are written under ``vm/keys/admin/``
- guest ``/etc/resolv.conf`` defaults to ``1.1.1.1`` and ``1.0.0.1``
- the guest image defaults to the Debian 12 cloud image with libvirt
  ``os_variant`` set to ``generic``

Tenant public keys are recommended when available before provisioning, but they
are optional. If ``vm.ssh_key_file`` is omitted, the tenant account is still
created and an administrator can add the key later.

Global image defaults live in ``vmctl.yaml`` under ``image:``, and a VM config
can override them with its own ``image:`` block.

Guest DNS defaults live in ``vmctl.yaml`` under ``dns:``, and a VM config can
override them with its own ``dns:`` block.

Use ``virt-install --osinfo list`` on the host if you want to override
``image.os_variant`` with a distro-specific value.

Set ``paths.vm_data_dir`` in a VM config to override the local artifact
directory for one VM.

Run the pieces individually when needed:

.. code-block:: bash

   ./scripts/test
   ./scripts/coverage
   ./scripts/docs-build
