import json

import pytest

import app as app_module
from quoter import settings as settings_store
from quoter.carriers import FedEx, UPS
from quoter.carriers.base import Carrier
from quoter.models import QuoteRequest


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    """Records POSTs and answers from a {url_suffix: (status, body)} map."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for suffix, (status, body) in self.routes.items():
            if url.endswith(suffix):
                return FakeResponse(status, body)
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTER_SETTINGS_FILE", str(tmp_path / "settings.json"))
    Carrier._token_cache.clear()


@pytest.fixture
def client():
    return app_module.create_app().test_client()


SAMPLE_REQ = {
    "origin": {"postal_code": "30301", "state": "GA", "city": "Atlanta"},
    "destination": {"postal_code": "90210", "state": "CA", "residential": True},
    "packages": [{"weight_lb": "5", "length_in": "10", "width_in": "8", "height_in": "6"}],
}

CREDS = {"enabled": True, "client_id": "id", "client_secret": "shh", "account_number": "A1B2C3"}

UPS_RATE_BODY = {
    "RateResponse": {
        "RatedShipment": [
            {
                "Service": {"Code": "03"},
                "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "15.20"},
                "NegotiatedRateCharges": {"TotalCharge": {"CurrencyCode": "USD", "MonetaryValue": "11.05"}},
                "TimeInTransit": {"ServiceSummary": {"EstimatedArrival": {
                    "BusinessDaysInTransit": "4", "Arrival": {"Date": "20261120"}}}},
            },
            {
                "Service": {"Code": "01"},
                "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "80.00"},
                "GuaranteedDelivery": {"BusinessDaysInTransit": "1"},
            },
        ]
    }
}

FEDEX_RATE_BODY = {
    "output": {
        "rateReplyDetails": [
            {
                "serviceType": "FEDEX_GROUND",
                "serviceName": "FedEx Ground®",
                "ratedShipmentDetails": [
                    {"rateType": "ACCOUNT", "totalNetCharge": 12.5, "currency": "USD"},
                    {"rateType": "LIST", "totalNetCharge": 16.0, "currency": "USD"},
                ],
                "operationalDetail": {"transitTime": "FOUR_DAYS"},
                "commit": {"dateDetail": {"dayFormat": "2026-11-20T23:59:00"}},
            }
        ]
    }
}


# ----- settings -----------------------------------------------------------

def test_settings_secret_is_masked_and_preserved(client):
    resp = client.put("/api/settings", json={"carriers": {"ups": CREDS}})
    assert resp.status_code == 200
    view = client.get("/api/settings").get_json()
    assert view["carriers"]["ups"]["client_secret"] == settings_store.MASK
    assert view["status"]["ups"]["missing"] == []
    assert view["status"]["fedex"]["missing"] == ["client_id", "client_secret", "account_number"]

    # Re-saving the form with the mask / blank must not wipe the secret.
    client.put("/api/settings", json={"carriers": {"ups": {"client_secret": settings_store.MASK}}})
    client.put("/api/settings", json={"carriers": {"ups": {"client_secret": ""}}})
    assert settings_store.load()["carriers"]["ups"]["client_secret"] == "shh"


def test_settings_rejects_bad_environment(client):
    client.put("/api/settings", json={"carriers": {"fedex": {"environment": "evil"}}})
    assert settings_store.load()["carriers"]["fedex"]["environment"] == "sandbox"


def test_foreign_host_blocked(client):
    resp = client.get("/api/settings", headers={"Host": "attacker.example:5050"})
    assert resp.status_code == 403


# ----- UPS ----------------------------------------------------------------

def test_ups_request_and_parse():
    session = FakeSession({
        "/security/v1/oauth/token": (200, {"access_token": "tok", "expires_in": "14399"}),
        "/Shoptimeintransit": (200, UPS_RATE_BODY),
    })
    ups = UPS({**CREDS, "environment": "sandbox", "negotiated_rates": True}, session=session)
    rates = ups.get_rates(QuoteRequest.from_dict(SAMPLE_REQ))

    token_url, token_kwargs = session.calls[0]
    assert token_url.startswith("https://wwwcie.ups.com")
    assert token_kwargs["auth"] == ("id", "shh")

    _, rate_kwargs = session.calls[1]
    shipment = rate_kwargs["json"]["RateRequest"]["Shipment"]
    assert rate_kwargs["headers"]["Authorization"] == "Bearer tok"
    assert shipment["ShipTo"]["Address"]["ResidentialAddressIndicator"] == "Y"
    assert shipment["Package"][0]["PackageWeight"]["Weight"] == "5"
    assert shipment["ShipmentRatingOptions"] == {"NegotiatedRatesIndicator": "Y"}

    ground = next(r for r in rates if r.service_code == "03")
    assert ground.total == 11.05 and ground.list_total == 15.20
    assert ground.transit_days == 4 and ground.delivery_date == "2026-11-20"
    nda = next(r for r in rates if r.service_code == "01")
    assert nda.service_name == "UPS Next Day Air" and nda.transit_days == 1


def test_ups_token_is_cached():
    session = FakeSession({
        "/security/v1/oauth/token": (200, {"access_token": "tok", "expires_in": 3600}),
        "/Shoptimeintransit": (200, UPS_RATE_BODY),
    })
    ups = UPS(CREDS, session=session)
    req = QuoteRequest.from_dict(SAMPLE_REQ)
    ups.get_rates(req)
    ups.get_rates(req)
    assert sum(1 for url, _ in session.calls if "oauth" in url) == 1


def test_ups_single_rated_shipment_dict():
    body = {"RateResponse": {"RatedShipment": UPS_RATE_BODY["RateResponse"]["RatedShipment"][1]}}
    assert len(UPS(CREDS).parse_response(body)) == 1


def test_ups_error_message_surfaces():
    session = FakeSession({"/security/v1/oauth/token": (
        401, {"response": {"errors": [{"code": "250003", "message": "Invalid Authentication Information."}]}})})
    with pytest.raises(Exception, match="Invalid Authentication Information"):
        UPS(CREDS, session=session).test_connection()


# ----- FedEx --------------------------------------------------------------

def test_fedex_request_and_parse():
    session = FakeSession({
        "/oauth/token": (200, {"access_token": "ftok", "expires_in": 3599}),
        "/rate/v1/rates/quotes": (200, FEDEX_RATE_BODY),
    })
    fedex = FedEx({**CREDS, "environment": "production"}, session=session)
    rates = fedex.get_rates(QuoteRequest.from_dict(SAMPLE_REQ))

    assert session.calls[0][0] == "https://apis.fedex.com/oauth/token"
    body = session.calls[1][1]["json"]
    assert body["accountNumber"] == {"value": "A1B2C3"}
    assert body["requestedShipment"]["recipient"]["address"]["residential"] is True
    assert body["requestedShipment"]["requestedPackageLineItems"][0]["dimensions"]["length"] == 10

    [r] = rates
    assert r.total == 12.5 and r.list_total == 16.0
    assert r.transit_days == 4 and r.delivery_date == "2026-11-20"


# ----- /api/quote ---------------------------------------------------------

def test_quote_endpoint_merges_and_reports_errors(client, monkeypatch):
    client.put("/api/settings", json={"carriers": {"ups": CREDS, "fedex": CREDS}})

    def fake_ups(self, req):
        return UPS(CREDS).parse_response(UPS_RATE_BODY)

    def fake_fedex(self, req):
        from quoter.carriers import CarrierError
        raise CarrierError("FedEx: account not authorized")

    monkeypatch.setattr(UPS, "get_rates", fake_ups)
    monkeypatch.setattr(FedEx, "get_rates", fake_fedex)

    data = client.post("/api/quote", json=SAMPLE_REQ).get_json()
    totals = [r["total"] for r in data["rates"]]
    assert totals == sorted(totals)
    assert data["errors"] == {"fedex": "FedEx: account not authorized"}


def test_quote_validation(client):
    client.put("/api/settings", json={"carriers": {"ups": CREDS}})
    bad = json.loads(json.dumps(SAMPLE_REQ))
    bad["packages"][0]["weight_lb"] = "0"
    resp = client.post("/api/quote", json=bad)
    assert resp.status_code == 400 and "weight" in resp.get_json()["error"]


def test_quote_without_enabled_carriers(client):
    resp = client.post("/api/quote", json=SAMPLE_REQ)
    assert resp.status_code == 400
    assert "No carriers" in resp.get_json()["error"]


def test_quote_uses_default_origin(client, monkeypatch):
    client.put("/api/settings", json={"origin": {"postal_code": "44101"}, "carriers": {"ups": CREDS}})
    seen = {}

    def fake(self, req):
        seen["origin"] = req.origin.postal_code
        return []

    monkeypatch.setattr(UPS, "get_rates", fake)
    req = dict(SAMPLE_REQ, origin={})
    client.post("/api/quote", json=req)
    assert seen["origin"] == "44101"
