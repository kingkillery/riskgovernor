"""riskgovernor - deterministic bankroll risk governance.

Hard gates, strategy rotation and loss-sized recovery, expressed as pure data
and a pure decision function. The governor recommends; a human approves.
"""

from .governor import Decision, Governor, Metrics, Verdict
from .ledger import Episode, Ledger, to_decimal
from .params import MissingConfigError, ParamStore
from .policy import Gates, RecoverySpec, RiskPolicy, Strategy

__version__ = "0.1.0"

__all__ = [
    "Decision",
    "Episode",
    "Gates",
    "Governor",
    "Ledger",
    "Metrics",
    "MissingConfigError",
    "ParamStore",
    "RecoverySpec",
    "RiskPolicy",
    "Strategy",
    "Verdict",
    "to_decimal",
    "__version__",
]