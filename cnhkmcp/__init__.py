"""Local shim for cnhkmcp package imports used by research scripts."""

try:
    from .untracked.platform_functions import (
        BrainApiClient,
        authenticate,
        brain_client,
        create_multi_simulation,
    )
except ImportError:
    BrainApiClient = None
    authenticate = None
    brain_client = None
    create_multi_simulation = None


