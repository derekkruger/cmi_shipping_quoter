"""Plain data types shared by the web layer and the carrier clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


class QuoteError(Exception):
    """Raised for user-facing problems (bad input, carrier rejected the request, ...)."""


@dataclass
class Address:
    postal_code: str
    country_code: str = "US"
    city: str = ""
    state: str = ""
    address_line: str = ""
    residential: bool = False

    @classmethod
    def from_dict(cls, data: dict | None, *, label: str) -> "Address":
        data = data or {}
        postal = str(data.get("postal_code", "")).strip()
        if not postal:
            raise QuoteError(f"{label}: postal/ZIP code is required.")
        return cls(
            postal_code=postal,
            country_code=(str(data.get("country_code") or "US").strip().upper())[:2],
            city=str(data.get("city", "")).strip(),
            state=str(data.get("state", "")).strip().upper(),
            address_line=str(data.get("address_line", "")).strip(),
            residential=bool(data.get("residential", False)),
        )


@dataclass
class Package:
    weight_lb: float
    length_in: float = 0
    width_in: float = 0
    height_in: float = 0

    @property
    def has_dimensions(self) -> bool:
        return self.length_in > 0 and self.width_in > 0 and self.height_in > 0

    @classmethod
    def from_dict(cls, data: dict, *, index: int) -> "Package":
        def num(key: str) -> float:
            raw = data.get(key, 0)
            if raw in ("", None):
                return 0.0
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise QuoteError(f"Package {index}: '{key}' must be a number.") from None
            if value < 0:
                raise QuoteError(f"Package {index}: '{key}' cannot be negative.")
            return value

        pkg = cls(
            weight_lb=num("weight_lb"),
            length_in=num("length_in"),
            width_in=num("width_in"),
            height_in=num("height_in"),
        )
        if pkg.weight_lb <= 0:
            raise QuoteError(f"Package {index}: weight must be greater than 0.")
        return pkg


@dataclass
class QuoteRequest:
    origin: Address
    destination: Address
    packages: list[Package]

    @classmethod
    def from_dict(cls, data: dict) -> "QuoteRequest":
        packages_raw = data.get("packages") or []
        if not packages_raw:
            raise QuoteError("Add at least one package.")
        return cls(
            origin=Address.from_dict(data.get("origin"), label="Ship from"),
            destination=Address.from_dict(data.get("destination"), label="Ship to"),
            packages=[Package.from_dict(p, index=i + 1) for i, p in enumerate(packages_raw)],
        )


@dataclass
class Rate:
    carrier: str
    service_code: str
    service_name: str
    total: float  # the rate the clerk should use (account/negotiated if available)
    currency: str = "USD"
    list_total: float | None = None  # published/retail rate, when returned
    transit_days: int | None = None
    delivery_date: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
