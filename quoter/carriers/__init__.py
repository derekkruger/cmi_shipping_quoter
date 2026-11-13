"""Carrier registry. To add a carrier (e.g. USPS), subclass ``Carrier``,
add it here, and add its default settings in ``quoter/settings.py``."""

from .base import Carrier, CarrierError
from .fedex import FedEx
from .ups import UPS

CARRIERS: dict[str, type[Carrier]] = {
    UPS.name: UPS,
    FedEx.name: FedEx,
}

__all__ = ["CARRIERS", "Carrier", "CarrierError", "FedEx", "UPS"]
