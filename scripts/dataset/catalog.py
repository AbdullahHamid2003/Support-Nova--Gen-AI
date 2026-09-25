"""Product catalogue (from config/products.yaml) plus natural ways customers mention each product."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

# Curated customer-written mentions. Every mention contains an alias from config/products.yaml
# so that a product extractor can resolve it; the scenario author picks among them at random.
MENTIONS: dict[str, tuple[str, ...]] = {
    "LUM-TH-100": ("Aura thermostat", "Aura Smart Thermostat", "Lumora Aura Smart Thermostat", "smart thermostat"),
    "LUM-CAM-200": ("Sentinel Indoor Camera", "Sentinel indoor cam", "indoor camera", "Lumora Sentinel Indoor Camera"),
    "LUM-CAM-210": ("Sentinel Outdoor Camera", "Sentinel outdoor cam", "outdoor camera", "Lumora Sentinel Outdoor Camera"),
    "LUM-VAC-300": ("Glide Robot Vacuum", "Glide vacuum", "robot vacuum", "Lumora Glide Robot Vacuum"),
    "LUM-PWR-400": ("PowerCell Portable Power Station", "PowerCell", "PowerCell power station", "portable power station"),
    "LUM-SPK-500": ("Halo Smart Speaker", "Halo speaker", "smart speaker", "Lumora Halo speaker"),
    "LUM-PLG-600": ("Spark Smart Plug", "Spark smart plug", "smart plug", "Spark Smart Plug 2-pack"),
    "LUM-BLB-610": ("Beam Smart Bulbs", "Beam bulbs", "smart bulbs", "Beam Smart Bulb 4-pack"),
    "LUM-LCK-700": ("Keystone Smart Lock", "Keystone lock", "smart lock", "Lumora Keystone Smart Lock"),
    "LUM-HUB-800": ("Nexus Home Hub", "Nexus hub", "home hub", "Lumora Nexus Home Hub"),
    "LUM-AIR-900": ("Breeze Air Purifier", "Breeze purifier", "air purifier", "Lumora Breeze Air Purifier"),
    "SVC-CLOUD": ("Cloud Vault", "Cloud Vault subscription", "Lumora Cloud Vault", "Cloud Vault plan"),
    "SVC-CARE": ("Care+", "Care+ plan", "Care+ protection plan", "Lumora Care+"),
    "SVC-INSTALL": ("Pro Install", "Pro Install service", "Lumora Pro Install", "Pro Install appointment"),
    "SVC-APP": ("Lumora Home app", "Lumora app", "Lumora Home app", "Home app"),
}

# Short follow-up mentions ("the thermostat") used by the {product:short} token.
SHORT: dict[str, tuple[str, ...]] = {
    "LUM-TH-100": ("thermostat",),
    "LUM-CAM-200": ("indoor camera", "indoor cam"),
    "LUM-CAM-210": ("outdoor camera", "outdoor cam"),
    "LUM-VAC-300": ("vacuum", "robot vacuum"),
    "LUM-PWR-400": ("PowerCell", "power station"),
    "LUM-SPK-500": ("speaker", "Halo"),
    "LUM-PLG-600": ("plug", "smart plug"),
    "LUM-BLB-610": ("bulbs",),
    "LUM-LCK-700": ("lock", "smart lock"),
    "LUM-HUB-800": ("hub",),
    "LUM-AIR-900": ("purifier",),
    "SVC-CLOUD": ("Cloud Vault", "vault"),
    "SVC-CARE": ("Care+",),
    "SVC-INSTALL": ("installation",),
    "SVC-APP": ("the app",),
}


# Aliases too generic (or too often verbs) to be treated as product entities by the text scan.
SCAN_STOPLIST = frozenset({
    "the app", "mobile app", "installation", "installer", "technician visit", "vault", "aura", "beam", "spark",
    "halo", "glide", "breeze", "nexus", "keystone", "lock", "plug", "bulb", "bulbs", "speaker", "hub", "vacuum",
    "purifier", "thermostat", "powercell", "power bank", "battery pack", "cloud storage", "protection plan",
})


@dataclass(frozen=True)
class ProductInfo:
    """One catalogue entry."""

    sku: str
    name: str
    line: str
    type: str
    price: float
    warranty_months: int | None
    hazard_class: str | None

    @property
    def entity_type(self) -> str:
        """``product`` for physical devices, ``service`` for subscriptions, services and the app."""
        return "product" if self.type == "device" else "service"

    @property
    def is_device(self) -> bool:
        return self.type == "device"


class Catalog:
    """Read-only view over the product catalogue of the loaded Rule Matrix."""

    def __init__(self, matrix: Any) -> None:
        self.products: dict[str, ProductInfo] = {
            sku: ProductInfo(sku=p.sku, name=p.name, line=p.line, type=p.type, price=float(p.price),
                             warranty_months=p.warranty_months, hazard_class=p.hazard_class)
            for sku, p in matrix.products.items()
        }
        missing = set(self.products) - set(MENTIONS)
        if missing:
            raise ValueError(f"No customer mentions defined for SKUs: {sorted(missing)}")
        names: set[tuple[str, str]] = set()
        for sku, p in matrix.products.items():
            candidates = {p.name, p.name.replace("Lumora ", ""), *p.aliases, *MENTIONS[sku]}
            for name in candidates:
                if name.lower() not in SCAN_STOPLIST and len(name) > 3:
                    names.add((name.lower(), sku))
        # longest first so "Sentinel Outdoor Camera" wins over "outdoor camera"
        self.scan_names: list[tuple[str, str]] = sorted(names, key=lambda n: (-len(n[0]), n[0]))

    def scan_mentions(self, text: str, covered: list[tuple[int, int]]) -> list[tuple[str, str, int, int]]:
        """Product/service mentions written in ``text`` outside the ``covered`` spans.

        Returns ``(sku, mention as written, start, end)`` for non-overlapping, word-bounded matches.
        """
        lower = text.lower()
        spans = list(covered)
        found: list[tuple[str, str, int, int]] = []
        for name, sku in self.scan_names:
            start = 0
            while True:
                idx = lower.find(name, start)
                if idx < 0:
                    break
                end = idx + len(name)
                start = end
                before = lower[idx - 1] if idx > 0 else " "
                after = lower[end] if end < len(lower) else " "
                if before.isalnum() or after.isalnum() or (after == "+" and not name.endswith("+")):
                    continue
                if any(idx < e and end > s for s, e in spans):
                    continue
                spans.append((idx, end))
                found.append((sku, text[idx:end], idx, end))
        return sorted(found, key=lambda f: f[2])

    def get(self, sku: str) -> ProductInfo:
        if sku not in self.products:
            raise KeyError(f"Unknown SKU {sku!r}")
        return self.products[sku]

    def price(self, sku: str) -> float:
        return self.get(sku).price

    def mention(self, sku: str, rng: random.Random) -> str:
        return rng.choice(MENTIONS[sku])

    def short(self, sku: str, rng: random.Random) -> str:
        return rng.choice(SHORT[sku])

    def device_skus(self) -> list[str]:
        return sorted(s for s, p in self.products.items() if p.is_device)
