"""Detector version — the cohort key for grading the paper track record.

The scorecard (``scorecard.py``) grades closed trades **per behavior cohort**,
not pooled across all history, because a change to the detector's trading logic
makes earlier trades evidence about a bot that no longer exists. The version
string is how a session's logs self-describe which bot produced them:
``SignalLog`` stamps it on every fire row (``persist.py``).

Bump rule (the whole scheme):

- **minor** (``0.3`` → ``0.4``): the change alters what/when/how the detector
  trades — arming rules, verdict-mode logic, calibration constants, gates,
  bracket placement. Starts a NEW cohort; the go-live gate's sample count
  restarts for the affected modes.
- **patch** (``0.3.0`` → ``0.3.1``): observer-only or infra — telemetry,
  logging, persistence, this versioning itself. Same cohort; samples keep
  accumulating.

The cohort key is ``major.minor`` (see ``cohort_of``): trades whose versions
share a cohort key pool together in the scorecard. Bump in the same commit as
the behavior change so the stamp can never drift from the code.

Live promotion pins a passing cohort by git tag (``scalper-vX.Y.Z``); the live
runner deploys from the tag while paper keeps running the workspace head, and
the stamp is what keeps the two track records attributable.

History note: the ``0.3`` cohort began 2026-06-23 with the verdict modes + re-fire
cooldown (the 2026-06-29 shadow-telemetry ship was observer-only, so it stayed
``0.3.1``). The ``0.4`` cohort begins 2026-07-12 with the **futures migration**: the
detector now trades /MES with an absolute-price, direction-aware bracket and
~10×-rescaled point geometry — a wholesale change to what/when/how it trades, so it
opens a fresh cohort. The prior QQQ-options track record stays attributable to
``0.3`` and never pools with /MES results.
"""

__version__ = "0.4.0"


def cohort_of(version: str) -> str:
    """``major.minor`` of a version string — trades with equal cohorts pool together."""
    return ".".join(version.split(".")[:2])
