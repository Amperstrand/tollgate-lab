"""Scenario layer — one tollgate story, every rig.

Implements the design in docs/SCENARIO-LAYER.md: the same tollgate lifecycle
(fund → connect → gate-closed → pay → gate-open → session → renew → expire →
fallback → evidence) expressed once against driver contracts, so the Omarchy
VM, the Debian container, and the phones run the same story with different
adapters.

The package is additive: nothing here is imported by existing tollgate_lab
modules.
"""

from tollgate_lab.scenarios.contract import (
    CaptureDriver as CaptureDriver,
)
from tollgate_lab.scenarios.contract import (
    CaptureResult as CaptureResult,
)
from tollgate_lab.scenarios.contract import (
    ClientDriver as ClientDriver,
)
from tollgate_lab.scenarios.contract import (
    GatewayDriver as GatewayDriver,
)
from tollgate_lab.scenarios.contract import (
    PaymentActor as PaymentActor,
)
from tollgate_lab.scenarios.contract import (
    PayReceipt as PayReceipt,
)
from tollgate_lab.scenarios.contract import (
    ScenarioRoles as ScenarioRoles,
)
from tollgate_lab.scenarios.contract import (
    SessionState as SessionState,
)
from tollgate_lab.scenarios.contract import (
    Usage as Usage,
)
from tollgate_lab.scenarios.evidence import (
    EvidencePaths as EvidencePaths,
)
from tollgate_lab.scenarios.evidence import (
    LifecycleResult as LifecycleResult,
)
from tollgate_lab.scenarios.evidence import (
    StepRecord as StepRecord,
)
from tollgate_lab.scenarios.evidence import (
    StepStatus as StepStatus,
)
from tollgate_lab.scenarios.evidence import (
    write_evidence as write_evidence,
)
from tollgate_lab.scenarios.lifecycle import (
    CANONICAL_STEPS as CANONICAL_STEPS,
)
from tollgate_lab.scenarios.lifecycle import (
    StepFailureError as StepFailureError,
)
from tollgate_lab.scenarios.lifecycle import (
    run_lifecycle as run_lifecycle,
)
from tollgate_lab.scenarios.profile import (
    PhaseFlags as PhaseFlags,
)
from tollgate_lab.scenarios.profile import (
    ScenarioProfile as ScenarioProfile,
)
from tollgate_lab.scenarios.profile import (
    WalletFreshness as WalletFreshness,
)
from tollgate_lab.scenarios.profile import (
    load_profile as load_profile,
)
from tollgate_lab.scenarios.profile import (
    profile_from_dict as profile_from_dict,
)
