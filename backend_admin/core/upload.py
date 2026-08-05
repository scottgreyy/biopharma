"""Upload parsing + column validation for CSV / Excel / JSON. If columns match
the six canonical columns (order-insensitive), return rows for append; otherwise
refuse with a clear message. The table is never altered on mismatch."""
from __future__ import annotations
import csv
import io
import json
from typing import Any
from backend_admin.core.db_admin import HEADER_TO_COLUMN

_EXPECTED_HEADERS = set(HEADER_TO_COLUMN.keys())
_INTERNAL = set(HEADER_TO_COLUMN.values())


class UploadError(ValueError):
    """Raised when a file's columns don't match, or it can't be parsed."""


def _normalize_headers(headers: list[str]) -> dict[str, str]:
    hset = {h.strip() for h in headers}
    if hset == _EXPECTED_HEADERS:
        return dict(HEADER_TO_COLUMN)
    if hset == _INTERNAL:
        return {c: c for c in _INTERNAL}
    missing = _EXPECTED_HEADERS - hset
    extra = hset - _EXPECTED_HEADERS
    raise UploadError(
        "Cannot append: columns are different. "
        f"Expected exactly {sorted(_EXPECTED_HEADERS)}. "
        + (f"Missing: {sorted(missing)}. " if missing else "")
        + (f"Unexpected: {sorted(extra)}." if extra else "")
    )


def _rows_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        raise UploadError("The file has no data rows.")
    header_map = _normalize_headers(list(records[0].keys()))
    out: list[dict[str, Any]] = []
    for rec in records:
        out.append({
            header_map[k]: ("" if rec.get(k) is None else str(rec.get(k)).strip())
            for k in header_map if k in rec
        })
    return out


def parse_upload(filename: str, content: bytes) -> list[dict[str, Any]]:
    name = filename.lower()
    if name.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception as e:
            raise UploadError(f"Invalid JSON: {e}")
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise UploadError("JSON must be a list of row objects (or a single object).")
        return _rows_from_records(data)
    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except Exception as e:
            raise UploadError(f"Could not read CSV text: {e}")
        reader = csv.DictReader(io.StringIO(text))
        return _rows_from_records(list(reader))
    if name.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
        except ImportError:
            raise UploadError("Excel support needs 'openpyxl' (pip install openpyxl).")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
        except Exception as e:
            raise UploadError(f"Could not read Excel file: {e}")
        if not rows:
            raise UploadError("The spreadsheet is empty.")
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        records = [
            {headers[i]: row[i] for i in range(len(headers))}
            for row in rows[1:]
            if any(c is not None for c in row)
        ]
        return _rows_from_records(records)
    raise UploadError("Unsupported file type. Use .csv, .xlsx, .xls, or .json.")
