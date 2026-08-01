"""
Backend 1 tool surface.

The actual tool implementations, Pydantic schemas, registry, dispatcher, and
JSON schemas now live in shared/tools/asset_tools.py so all three backends share
one tested data-access layer and differ ONLY in orchestration. This module
re-exports them to keep Backend 1's imports stable.
"""
from shared.tools.asset_tools import (  # noqa: F401
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    dispatch_tool,
    # argument models (occasionally handy to import directly)
    AssetCodeArgs,
    EmployeeArgs,
    SearchArgs,
    RelatedByModelArgs,
    RecommendArgs,
)
