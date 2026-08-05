"""Admin API routes: view / lookup / add / delete / upload. JWT-protected.
Writes go through the read-write db_admin layer. After writes, clears Backend 3's
DuckDB cache so it reflects changes without a restart."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from shared.auth.security import require_auth
from backend_admin.core import db_admin
from backend_admin.core.upload import parse_upload, UploadError

router = APIRouter(prefix="/admin", tags=["admin"])


def _refresh_duckdb() -> None:
    try:
        from backend_router.core.duckdb_engine import get_connection
        get_connection.cache_clear()
    except Exception:
        pass


class AssetIn(BaseModel):
    asset_code: str = Field(..., min_length=1)
    asset_name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    employee_name: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    purchase_date: str = Field(..., min_length=1)


@router.get("/assets")
async def list_assets(limit: int = 500, offset: int = 0, _: str = Depends(require_auth)):
    total = await db_admin.count_assets()
    rows = await db_admin.list_assets(limit=limit, offset=offset)
    return {"total": total, "count": len(rows), "assets": rows}


@router.get("/assets/{asset_code}")
async def get_asset(asset_code: str, _: str = Depends(require_auth)):
    row = await db_admin.get_asset(asset_code)
    if not row:
        raise HTTPException(status_code=404, detail=f"No asset found with code {asset_code}.")
    return row


@router.post("/assets")
async def add_asset(asset: AssetIn, _: str = Depends(require_auth)):
    result = await db_admin.add_asset(asset.model_dump())
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    _refresh_duckdb()
    return result


@router.delete("/assets/{asset_code}")
async def delete_asset(asset_code: str, _: str = Depends(require_auth)):
    result = await db_admin.delete_asset(asset_code)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["message"])
    _refresh_duckdb()
    return result


@router.post("/upload")
async def upload(file: UploadFile = File(...), _: str = Depends(require_auth)):
    content = await file.read()
    try:
        rows = parse_upload(file.filename or "", content)
    except UploadError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result = await db_admin.append_rows(rows)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    _refresh_duckdb()
    return result
