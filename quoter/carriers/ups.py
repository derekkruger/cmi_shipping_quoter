"""UPS Rating API (REST / OAuth 2.0).

Docs: https://developer.ups.com/api/reference?loc=en_US#tag/Rating
Create an app at https://developer.ups.com/ (add the "Rating" product) to get
a Client ID and Client Secret. The account number is your 6-character UPS
shipper number.
"""

from __future__ import annotations

import uuid

from ..models import QuoteRequest, Rate
from .base import Carrier, CarrierError

HOSTS = {
    False: "https://wwwcie.ups.com",        # Customer Integration Environment (sandbox)
    True: "https://onlinetools.ups.com",    # production
}
RATING_VERSION = "v2409"

SERVICE_NAMES = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "07": "UPS Worldwide Express",
    "08": "UPS Worldwide Expedited",
    "11": "UPS Standard",
    "12": "UPS 3 Day Select",
    "13": "UPS Next Day Air Saver",
    "14": "UPS Next Day Air Early",
    "17": "UPS Worldwide Economy DDU",
    "54": "UPS Worldwide Express Plus",
    "59": "UPS 2nd Day Air A.M.",
    "65": "UPS Worldwide Saver",
    "72": "UPS Worldwide Economy DDP",
    "75": "UPS Heavy Goods",
    "93": "UPS Ground Saver",
    "96": "UPS Worldwide Express Freight",
}


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _money(node) -> float | None:
    try:
        return float(node["MonetaryValue"])
    except (TypeError, KeyError, ValueError):
        return None


class UPS(Carrier):
    name = "ups"
    display_name = "UPS"

    @property
    def host(self) -> str:
        return HOSTS[self.production]

    def _fetch_token(self) -> tuple[str, int]:
        body = self._post(
            f"{self.host}/security/v1/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=(self.config["client_id"], self.config["client_secret"]),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "x-merchant-id": self.config["account_number"],
            },
        )
        token = body.get("access_token")
        if not token:
            raise CarrierError("UPS: authentication succeeded but no token was returned.")
        return token, int(body.get("expires_in", 3600))

    def _error_message(self, body: dict) -> str:
        errors = (body.get("response") or {}).get("errors") or []
        return "; ".join(e.get("message", "") for e in errors if e.get("message"))

    @staticmethod
    def _address(addr) -> dict:
        out = {
            "PostalCode": addr.postal_code,
            "CountryCode": addr.country_code,
        }
        if addr.address_line:
            out["AddressLine"] = [addr.address_line]
        if addr.city:
            out["City"] = addr.city
        if addr.state:
            out["StateProvinceCode"] = addr.state
        return out

    def build_request(self, req: QuoteRequest) -> dict:
        account = self.config["account_number"]
        shipper_addr = self._address(req.origin)
        ship_to_addr = self._address(req.destination)
        if req.destination.residential:
            ship_to_addr["ResidentialAddressIndicator"] = "Y"

        packages = []
        for pkg in req.packages:
            p = {
                "PackagingType": {"Code": "02", "Description": "Customer Supplied Package"},
                "PackageWeight": {
                    "UnitOfMeasurement": {"Code": "LBS"},
                    "Weight": f"{pkg.weight_lb:g}",
                },
            }
            if pkg.has_dimensions:
                p["Dimensions"] = {
                    "UnitOfMeasurement": {"Code": "IN"},
                    "Length": f"{pkg.length_in:g}",
                    "Width": f"{pkg.width_in:g}",
                    "Height": f"{pkg.height_in:g}",
                }
            packages.append(p)

        shipment = {
            "Shipper": {"Name": "Shipper", "ShipperNumber": account, "Address": shipper_addr},
            "ShipFrom": {"Name": "Ship From", "Address": shipper_addr},
            "ShipTo": {"Name": "Ship To", "Address": ship_to_addr},
            "PaymentDetails": {
                "ShipmentCharge": [{"Type": "01", "BillShipper": {"AccountNumber": account}}]
            },
            "NumOfPieces": str(len(packages)),
            "Package": packages,
            # Ask for transit times alongside the rates.
            "DeliveryTimeInformation": {"PackageBillType": "03"},
            "ShipmentTotalWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": f"{sum(p.weight_lb for p in req.packages):g}",
            },
        }
        if self.config.get("negotiated_rates", True):
            shipment["ShipmentRatingOptions"] = {"NegotiatedRatesIndicator": "Y"}

        return {
            "RateRequest": {
                "Request": {"TransactionReference": {"CustomerContext": "CMI Shipping Quoter"}},
                "Shipment": shipment,
            }
        }

    def get_rates(self, req: QuoteRequest) -> list[Rate]:
        token = self.get_token()
        # "Shoptimeintransit" = all services + transit times.
        body = self._post(
            f"{self.host}/api/rating/{RATING_VERSION}/Shoptimeintransit",
            json=self.build_request(req),
            headers={
                "Authorization": f"Bearer {token}",
                "transId": uuid.uuid4().hex[:32],
                "transactionSrc": "cmi-quoter",
            },
        )
        return self.parse_response(body)

    def parse_response(self, body: dict) -> list[Rate]:
        rated = _as_list((body.get("RateResponse") or {}).get("RatedShipment"))
        rates: list[Rate] = []
        for shipment in rated:
            code = str((shipment.get("Service") or {}).get("Code", ""))
            list_total = _money(shipment.get("TotalCharges"))
            negotiated = _money(
                ((shipment.get("NegotiatedRateCharges") or {}).get("TotalCharge"))
            )
            total = negotiated if negotiated is not None else list_total
            if total is None:
                continue
            currency = (shipment.get("TotalCharges") or {}).get("CurrencyCode", "USD")

            transit_days = None
            delivery_date = None
            summary = (shipment.get("TimeInTransit") or {}).get("ServiceSummary") or {}
            est = summary.get("EstimatedArrival") or {}
            if est.get("BusinessDaysInTransit"):
                transit_days = _int(est.get("BusinessDaysInTransit"))
            arrival_date = (est.get("Arrival") or {}).get("Date")
            if arrival_date and len(arrival_date) == 8:
                delivery_date = f"{arrival_date[:4]}-{arrival_date[4:6]}-{arrival_date[6:]}"
            if transit_days is None:
                transit_days = _int((shipment.get("GuaranteedDelivery") or {}).get("BusinessDaysInTransit"))

            notes = [
                a.get("Description") for a in _as_list(shipment.get("RatedShipmentAlert"))
                if a.get("Description")
            ]
            rates.append(Rate(
                carrier="UPS",
                service_code=code,
                service_name=SERVICE_NAMES.get(code, f"UPS service {code}"),
                total=total,
                currency=currency,
                list_total=list_total if negotiated is not None else None,
                transit_days=transit_days,
                delivery_date=delivery_date,
                notes=notes,
            ))
        return rates


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
