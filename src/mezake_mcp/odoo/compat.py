"""Version-aware behavior flags and domain helpers.

Keeps Odoo-version divergences in one place so tools stay version-agnostic.
Used by `OdooClient.stockable_domain()` / `sellable_product_domain()` and
similar — the client resolves the server's version once, then delegates
here for the version-specific bits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VersionInfo:
    """Parsed response from Odoo's `common.version()`.

    The `server_version_info` tuple Odoo returns looks like:
        (19, 0, 0, "final", 0, "e")   Enterprise
        (18, 0, 0, "final", 0, "")    Community
    """

    major: int
    minor: int
    patch: int
    stage: str
    stage_num: int
    edition: str

    @classmethod
    def from_odoo(cls, version_response: dict) -> "VersionInfo":
        """Parse the dict returned by `common.version()`. Pads missing
        trailing fields so very old servers still produce a valid object.
        """
        info = list(version_response.get("server_version_info", []))
        defaults = [0, 0, 0, "final", 0, ""]
        while len(info) < 6:
            info.append(defaults[len(info)])
        return cls(
            major=int(info[0]) if isinstance(info[0], int) else 0,
            minor=int(info[1]) if isinstance(info[1], int) else 0,
            patch=int(info[2]) if isinstance(info[2], int) else 0,
            stage=str(info[3]),
            stage_num=int(info[4]) if isinstance(info[4], int) else 0,
            edition=str(info[5]),
        )

    @property
    def series(self) -> str:
        """Human-readable version like `"19.0"`."""
        return f"{self.major}.{self.minor}"

    @property
    def is_enterprise(self) -> bool:
        return self.edition == "e"


# ── Feature flags ─────────────────────────────────────────────────────────────

def uses_is_storable(v: VersionInfo) -> bool:
    """In Odoo 17+, product stockability moved off the `type` selection:
    stockables are now `type='consu'` + `is_storable=True`. Earlier
    versions used `type='product'` exclusively.
    """
    return v.major >= 17


# ── Cross-version domain fragments ────────────────────────────────────────────

def stockable_product_domain(v: VersionInfo) -> list:
    """Domain fragment selecting products that are tracked in inventory.

    Pre-v17: `type='product'`.
    v17+:    `type='consu'` AND `is_storable=True`.
    """
    if uses_is_storable(v):
        return [["type", "=", "consu"], ["is_storable", "=", True]]
    return [["type", "=", "product"]]


def sellable_product_domain(v: VersionInfo) -> list:
    """Domain fragment for 'anything that can be sold and isn't a service'.

    Pre-v17: stockables (`product`) + consumables (`consu`).
    v17+:    `type='consu'` covers both stockables and non-stockables.
    """
    if uses_is_storable(v):
        return [["type", "=", "consu"]]
    return [["type", "in", ["product", "consu"]]]
