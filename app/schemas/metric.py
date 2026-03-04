"""Pydantic schemas for business metrics."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BusinessMetricBase(BaseModel):
    name: str = Field(..., description="Name of the metric (e.g., 'Weekly Active Users')")
    definition: str = Field(..., description="Human-readable definition of the metric")
    formula: Optional[str] = Field(None, description="Mathematical formula or logic for the metric")


class BusinessMetricCreate(BusinessMetricBase):
    pass


class BusinessMetricUpdate(BaseModel):
    name: Optional[str] = None
    definition: Optional[str] = None
    formula: Optional[str] = None


class BusinessMetricResponse(BusinessMetricBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessMetricListResponse(BaseModel):
    metrics: List[BusinessMetricResponse]
