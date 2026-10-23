"""eSupport SEO audit engine — implementation of SEO-AUDIT-ENGINE-SPEC v1.0 (ruleset 1.0.0).

Single authoritative scoring path: evidence -> checks (checks.py) -> scores (scoring.py) -> issues (issues.py)
-> verified payload (engine.py + gate.py). The AI narrative layer (narrative.py) adds prose only.
"""
from .engine import ENGINE_VERSION, INTEGRITY_STATEMENT, run_engine  # noqa: F401
from .scoring import RULESET_VERSION, WEIGHTS, band, maturity, round_half_up  # noqa: F401
