"""tollgate-lab pytest plugin.

Provides fixtures when tollgate-lab is installed as a pytest plugin.
Import this in your conftest.py:

    pytest_plugins = ["tollgate_lab.conftest"]
"""

import os
import pytest


@pytest.fixture(scope="session")
def router_host():
    """Router SSH host (from env or default)."""
    return os.environ.get("ROUTER_SSH_HOST", "192.168.13.112")


@pytest.fixture(scope="session")
def router_user():
    """Router SSH user."""
    return os.environ.get("ROUTER_SSH_USER", "root")


@pytest.fixture(scope="session")
def cloud_provider():
    """Auto-detected cloud provider name."""
    from tollgate_lab.cloud import list_providers
    providers = list_providers()
    return providers[0] if providers else "qemu"
