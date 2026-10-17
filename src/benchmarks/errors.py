"""Fatal run conditions must escape upstream retry/default handlers."""


class CallLimitReached(BaseException):
    """Operational call ceiling; preserve the run as incomplete."""


class BudgetStop(CallLimitReached):
    """No approved allowance, insufficient reserve, or unresolved accounting."""


class GatewayFailure(BaseException):
    """Transport/provider failure; never fabricate a decision."""


class DecisionFailure(BaseException):
    """Invalid completion; never let an upstream default become a model result."""
