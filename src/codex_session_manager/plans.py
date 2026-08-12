"""Private immutable plan persistence."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from codex_session_manager.config import AppPaths, private_atomic_write
from codex_session_manager.hashing import canonical_json_bytes
from codex_session_manager.models import ActionPlan, ImportPlan, TrimPlan

PlanModel = ActionPlan | ImportPlan | TrimPlan


class PlanStore:
    """Store sealed plans as mode-0600 JSON files."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    @staticmethod
    def _identifier(plan: PlanModel) -> str:
        return plan.plan_id

    @staticmethod
    def _seal(plan: PlanModel) -> str:
        return plan.plan_sha256

    def path_for(self, plan: PlanModel) -> Path:
        kind = plan.__class__.__name__.removesuffix("Plan").lower()
        return self.paths.plans_dir / f"{kind}-{self._identifier(plan)}.json"

    def save(self, plan: PlanModel) -> Path:
        plan.verify()
        data = canonical_json_bytes(plan)
        destination = self.path_for(plan)
        if destination.exists():
            existing = destination.read_bytes()
            if existing != data:
                raise ValueError(
                    f"immutable plan already exists with different bytes: {destination}"
                )
            return destination
        private_atomic_write(destination, data)
        return destination

    def load_action(self, path: Path) -> ActionPlan:
        plan = ActionPlan.model_validate_json(path.read_bytes())
        plan.verify()
        return plan

    def load_import(self, path: Path) -> ImportPlan:
        plan = ImportPlan.model_validate_json(path.read_bytes())
        plan.verify()
        return plan

    def load_trim(self, path: Path) -> TrimPlan:
        plan = TrimPlan.model_validate_json(path.read_bytes())
        plan.verify()
        return plan

    def find_by_id(self, plan_id: str) -> Path:
        matches = sorted(self.paths.plans_dir.glob(f"*-{plan_id}.json"))
        if len(matches) != 1:
            raise FileNotFoundError(f"expected one persisted plan for id {plan_id!r}")
        return matches[0]


def load_plan_as[P: BaseModel](path: Path, model: type[P]) -> P:
    """Load a specific sealed plan model for non-default storage paths."""

    value = model.model_validate_json(path.read_bytes())
    verify = getattr(value, "verify", None)
    if callable(verify):
        verify()
    return value
