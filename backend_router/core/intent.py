"""
Intent schema — the strict contract the LLM must produce.

The router LLM acts purely as an intent + entity extractor. Its entire job is
to emit JSON matching `RouterPlan`: one or more steps, each naming an intent
from a fixed enum and providing parameters. Anything outside this schema is
rejected before any DB access, so a malformed or adversarial model response
cannot reach the query layer.

Multi-step support: a plan may contain up to N steps. A later step can
reference an earlier step's result via `from_previous` — e.g. step 1 looks up
an asset by code, step 2 uses that asset's model to find peers. The executor
resolves these references deterministically (not the LLM).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IntentName(str, Enum):
    """The only intents the LLM may choose. Mirrors QUERY_LIBRARY keys."""
    lookup_asset_by_code = "lookup_asset_by_code"
    assets_by_employee = "assets_by_employee"
    search_assets = "search_assets"
    assets_by_model = "assets_by_model"
    recommend_assets = "recommend_assets"
    count_by_location = "count_by_location"
    # Sentinel for questions the data cannot answer (manager/floor/availability)
    # or that aren't asset-related — handled gracefully, no query run.
    unsupported = "unsupported"


class IntentParams(BaseModel):
    """Entities the LLM may extract. All optional; each intent uses a subset."""
    asset_code: Optional[str] = None
    employee_name: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    asset_name: Optional[str] = None


class PlanStep(BaseModel):
    intent: IntentName
    params: IntentParams = Field(default_factory=IntentParams)
    # Optional deterministic chaining: pull a field from a previous step's first
    # result row into this step's params. Format handled by the executor.
    from_previous: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Map of {param_name: source_field}. e.g. "
            "{'asset_name': 'asset_name'} takes asset_name from the prior "
            "step's result and uses it as this step's asset_name param."
        ),
    )


class RouterPlan(BaseModel):
    """The full structured plan the LLM must return as JSON."""
    steps: list[PlanStep] = Field(..., min_length=1)
    # A short natural-language restatement of what the user asked, used to guide
    # the final answer synthesis.
    intent_summary: str = ""
