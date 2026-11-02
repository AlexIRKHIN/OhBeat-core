"""Bodies of the payment endpoints (REST API §2.5)."""

from pydantic import BaseModel


class PaymentCreated(BaseModel):
    payment_id: str
    confirmation_url: str
