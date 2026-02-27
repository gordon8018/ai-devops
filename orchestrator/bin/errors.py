class PlannerError(Exception):
    """Base class for planner-related errors."""


class OpenClawDown(PlannerError):
    """Raised when OpenClaw cannot be reached or returns unusable output."""


class InvalidPlan(PlannerError):
    """Raised when a generated plan fails schema validation."""


class DispatchError(PlannerError):
    """Raised when a plan cannot be dispatched safely."""


class PolicyViolation(PlannerError):
    """Raised when a user task violates planner safety policy."""
