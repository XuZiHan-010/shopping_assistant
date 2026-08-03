"""演示商家 API Schema。"""

from uuid import UUID

from pydantic import BaseModel


class DemoMerchant(BaseModel):
    merchant_id: UUID
    display_name: str
    token: str


class DemoMerchantListResponse(BaseModel):
    merchants: list[DemoMerchant]
