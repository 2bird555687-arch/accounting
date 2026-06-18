"""Standard response wrappers และ error schemas."""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class OK(BaseModel, Generic[T]):
    """Envelope สำหรับ successful response."""

    success: bool = True
    data: T
    message: Optional[str] = None


class Paginated(BaseModel, Generic[T]):
    """Envelope สำหรับ paginated list response."""

    success: bool = True
    data: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool


class ErrorDetail(BaseModel):
    """รายละเอียด error."""

    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    """Envelope สำหรับ error response."""

    success: bool = False
    error: ErrorDetail


def ok(data: Any, message: Optional[str] = None) -> dict[str, Any]:
    """สร้าง success response dict."""
    resp: dict[str, Any] = {"success": True, "data": data}
    if message:
        resp["message"] = message
    return resp


def paginated(
    data: list[Any],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """สร้าง paginated response dict."""
    return {
        "success": True,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": (page * page_size) < total,
    }
