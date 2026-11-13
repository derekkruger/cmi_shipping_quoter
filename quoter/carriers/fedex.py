"""FedEx Rate API (REST / OAuth 2.0).

Docs: https://developer.fedex.com/api/en-us/catalog/rate/v1/docs.html
Create a project at https://developer.fedex.com/ (enable "Rates and Transit
Times API") to get an API Key (client ID) and Secret Key (client secret). The
account number is your 9-digit FedEx shipping account.
"""

from __future__ import annotations

from ..models import QuoteRequest, Rate
from .base import Carrier, CarrierError

HOSTS = {
    False: "https://apis-sandbox.fedex.com",
    True: "https://apis.fedex.com",
}

TRANSIT_DAYS = {
    "ONE_DAY": 1, "TWO_DAYS": 2, "THREE_DAYS": 3, "FOUR_DAYS": 4, "FIVE_DAYS": 5,
    "SIX_DAYS": 6, "SEVEN_DAYS": 7, "EIGHT_DAYS": 8, "NINE_DAYS": 9, "TEN_DAYS": 10,
}


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FedEx(Carrier):
    name = "fedex"
    display_name = "FedEx"

    @property
    def host(self) -> str:
        return HOSTS[self.production]

    def _fetch_token(self) -> tuple[str, int]:
        body = self._post(
            f"{self.host}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = body.get("access_token")
        if not token:
            raise CarrierError("FedEx: authentication succeeded but no token was returned.")
        return token, int(body.get("expires_in", 3600))

    def _error_message(self, body: dict) -> str:
        errors = body.get("errors") or []
        return "; ".join(e.get("message", "") or e.get("code", "") for e in errors)

    @staticmethod
    def _address(addr) -> dict:
        out = {"postalCode": addr.postal_code, "countryCode": addr.country_code}
        if addr.address_line:
            out["streetLines"] = [addr.address_line]
        if addr.city:
            out["city"] = addr.city
        if addr.state:
            out["stateOrProvinceCode"] = addr.state
        return out

    def build_request(self, req: QuoteRequest) -> dict:
        recipient = self._address(req.destination)
        recipient["residential"] = bool(req.destination.residential)

        items = []
        for pkg in req.packages:
            item = {"weight": {"units": "LB", "value": round(pkg.weight_lb, 1)}}
            if pkg.has_dimensions:
                item["dimensions"] = {
                    "length": max(1, round(pkg.length_in)),
                    "width": max(1, round(pkg.width_in)),
                    "height": max(1, round(pkg.height_in)),
                    "units": "IN",
                }
            items.append(item)

        return {
            "accountNumber": {"value": self.config["account_number"]},
            "rateRequestControlParameters": {"returnTransitTimes": True},
            "requestedShipment": {
                "shipper": {"address": self._address(req.origin)},
                "recipient": {"address": recipient},
                "pickupType": self.config.get("pickup_type") or "DROPOFF_AT_FEDEX_LOCATION",
                "rateRequestType": ["ACCOUNT", "LIST"],
                "packagingType": "YOUR_PACKAGING",
                "totalPackageCount": len(items),
                "requestedPackageLineItems": items,
            },
        }

    def get_rates(self, req: QuoteRequest) -> list[Rate]:
        token = self.get_token()
        body = self._post(
            f"{self.host}/rate/v1/rates/quotes",
            json=self.build_request(req),
            headers={
                "Authorization": f"Bearer {token}",
                "X-locale": "en_US",
                "Content-Type": "application/json",
            },
        )
        return self.parse_response(body)

    def parse_response(self, body: dict) -> list[Rate]:
        details = (body.get("output") or {}).get("rateReplyDetails") or []
        rates: list[Rate] = []
        for d in details:
            by_type: dict[str, dict] = {}
            for rsd in d.get("ratedShipmentDetails") or []:
                by_type[str(rsd.get("rateType", "")).upper()] = rsd

            chosen = by_type.get("ACCOUNT") or by_type.get("PREFERRED_CURRENCY") or by_type.get("LIST")
            if not chosen:
                if not by_type:
                    continue
                chosen = next(iter(by_type.values()))
            total = _float(chosen.get("totalNetCharge"))
            if total is None:
                continue
            list_rsd = by_type.get("LIST")
            list_total = _float(list_rsd.get("totalNetCharge")) if list_rsd and list_rsd is not chosen else None

            commit = d.get("commit") or {}
            op = d.get("operationalDetail") or {}
            transit_key = op.get("transitTime") or commit.get("transitDays", {}).get("minimumTransitTime")
            delivery = (commit.get("dateDetail") or {}).get("dayFormat") or op.get("deliveryDate")

            rates.append(Rate(
                carrier="FedEx",
                service_code=d.get("serviceType", ""),
                service_name=d.get("serviceName") or d.get("serviceType", "FedEx"),
                total=total,
                currency=chosen.get("currency", "USD"),
                list_total=list_total,
                transit_days=TRANSIT_DAYS.get(str(transit_key or "").upper()),
                delivery_date=(delivery or "")[:10] or None,
                notes=[a.get("message") for a in d.get("customerMessages") or [] if a.get("message")],
            ))
        return rates
