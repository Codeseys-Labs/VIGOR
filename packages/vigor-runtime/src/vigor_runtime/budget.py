"""Per-run budget tracking for cost-ceiling enforcement.

See ADR-0028. ``RunBudgetTracker`` is the orchestrator-side companion to
``AgentBackend.usage()``: at every iteration boundary the orchestrator
calls :meth:`RunBudgetTracker.check` and breaks the loop with
``stop_reason="cost_exceeded"`` when the ceiling is crossed.

The tracker has a single responsibility — read ``task.budgets.max_cost_usd``
once at run start and poll the backend's ``usage()`` accessor on demand.
"""

from __future__ import annotations

from vigor_core.interfaces import AgentBackend
from vigor_core.schemas import Budgets, Usage


class RunBudgetTracker:
    """Iteration-boundary cost ceiling enforcement.

    Backends that return ``Usage()`` zeros (the ABC default) cannot be
    enforced against — :meth:`check` returns ``False`` and the run
    proceeds. Operators who need guaranteed enforcement must use a
    backend whose ``usage()`` reports ``usd``.
    """

    def __init__(self, backend: AgentBackend, budgets: Budgets) -> None:
        self._backend = backend
        self._max_cost_usd = budgets.max_cost_usd
        self._latest = Usage()

    @property
    def latest(self) -> Usage:
        """Most recent usage snapshot polled from the backend."""
        return self._latest

    async def snapshot(self) -> Usage:
        """Refresh and return the current usage snapshot from the backend."""
        self._latest = await self._backend.usage()
        return self._latest

    async def check(self) -> bool:
        """Return ``True`` when the run should stop due to cost overrun.

        Falls open when ``max_cost_usd`` is unset or the backend reports
        ``usd=None`` (no self-pricing) — both are documented "exempt by
        construction" cases in ADR-0028. The orchestrator surfaces the
        snapshot on ``RunResult.usage`` either way.
        """
        if self._max_cost_usd is None:
            await self.snapshot()
            return False
        usage = await self.snapshot()
        if usage.usd is None:
            return False
        return usage.usd >= self._max_cost_usd
