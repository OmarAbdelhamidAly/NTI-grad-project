"""Pydantic schemas for System Policies."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class SystemPolicyBase(BaseModel):
    name: str
    rule_type: str  # cleaning, compliance, security
    description: str


class SystemPolicyCreate(SystemPolicyBase):
    pass


class SystemPolicyResponse(SystemPolicyBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemPolicyListResponse(BaseModel):
    policies: List[SystemPolicyResponse]
