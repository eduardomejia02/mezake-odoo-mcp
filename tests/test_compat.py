"""Tests for the Odoo version-compat helpers.

These are pure logic tests — no Odoo server needed.
"""

from mezake_mcp.odoo.compat import (
    VersionInfo,
    sellable_product_domain,
    stockable_product_domain,
    uses_is_storable,
)


def _v(major: int, edition: str = "") -> VersionInfo:
    return VersionInfo.from_odoo(
        {"server_version_info": [major, 0, 0, "final", 0, edition]}
    )


class TestVersionInfo:
    def test_parse_enterprise(self) -> None:
        v = VersionInfo.from_odoo({"server_version_info": [19, 0, 0, "final", 0, "e"]})
        assert v.major == 19
        assert v.series == "19.0"
        assert v.is_enterprise is True

    def test_parse_community(self) -> None:
        v = VersionInfo.from_odoo({"server_version_info": [18, 0, 0, "final", 0, ""]})
        assert v.major == 18
        assert v.is_enterprise is False

    def test_short_tuple_pads_with_defaults(self) -> None:
        v = VersionInfo.from_odoo({"server_version_info": [15]})
        assert v.major == 15
        assert v.minor == 0
        assert v.stage == "final"
        assert v.edition == ""

    def test_missing_key_defaults_to_zero_major(self) -> None:
        v = VersionInfo.from_odoo({})
        assert v.major == 0
        assert v.series == "0.0"


class TestFeatureFlags:
    def test_is_storable_is_v17_plus(self) -> None:
        assert uses_is_storable(_v(16)) is False
        assert uses_is_storable(_v(17)) is True
        assert uses_is_storable(_v(18)) is True
        assert uses_is_storable(_v(19)) is True
        assert uses_is_storable(_v(20)) is True


class TestStockableDomain:
    def test_pre_v17_uses_product_type(self) -> None:
        assert stockable_product_domain(_v(16)) == [["type", "=", "product"]]

    def test_v17_plus_uses_consu_plus_is_storable(self) -> None:
        assert stockable_product_domain(_v(17)) == [
            ["type", "=", "consu"],
            ["is_storable", "=", True],
        ]
        assert stockable_product_domain(_v(19)) == [
            ["type", "=", "consu"],
            ["is_storable", "=", True],
        ]


class TestSellableDomain:
    def test_pre_v17_includes_both_product_and_consu(self) -> None:
        assert sellable_product_domain(_v(16)) == [["type", "in", ["product", "consu"]]]

    def test_v17_plus_is_just_consu(self) -> None:
        assert sellable_product_domain(_v(17)) == [["type", "=", "consu"]]
        assert sellable_product_domain(_v(19)) == [["type", "=", "consu"]]
