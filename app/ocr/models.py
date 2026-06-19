"""OCR database models — OCRHistory และ OCRMapping."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import CompanyBase as Base


class OCRHistory(Base):
    __tablename__ = "ocr_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    extracted_json: Mapped[str | None] = mapped_column(Text)
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="extracted")
    journal_no: Mapped[str | None] = mapped_column(String(20))
    contact_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OCRMapping(Base):
    __tablename__ = "ocr_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    raw_vendor_name: Mapped[str] = mapped_column(String(500), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(Integer)
    account_code: Mapped[str | None] = mapped_column(String(10))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
