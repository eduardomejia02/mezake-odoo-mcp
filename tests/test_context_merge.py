"""Tests for OdooClient context merging.

Verifies that when a tool passes `context={"lang": "en_US"}` for
translations, the deployment-level `allowed_company_ids` is preserved
rather than being overwritten — and vice versa, that the caller's
`lang` always wins on conflicts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mezake_mcp.odoo.client import OdooClient


def _client_with_company(company_id: int | None = 7) -> tuple[OdooClient, MagicMock]:
    """Build an OdooClient with a stubbed object-proxy. Returns
    (client, mock_object_proxy) so tests can assert on the kw passed
    through to `execute_kw`.
    """
    client = OdooClient(
        url="http://x", db="x", login="x", api_key="x", company_id=company_id,
    )
    # Bypass real auth + proxies
    client._uid = 1  # type: ignore[attr-defined]
    mock_obj = MagicMock()
    mock_obj.execute_kw.return_value = "ok"
    client._object = mock_obj  # type: ignore[attr-defined]
    return client, mock_obj


class TestContextMerge:
    def test_caller_lang_wins_over_default(self) -> None:
        client, mock_obj = _client_with_company(company_id=7)
        client.execute_kw("res.partner", "read", [[1]], {"context": {"lang": "en_US"}})
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        assert kw_passed["context"] == {"allowed_company_ids": [7], "lang": "en_US"}

    def test_no_caller_context_keeps_only_company(self) -> None:
        client, mock_obj = _client_with_company(company_id=7)
        client.execute_kw("res.partner", "read", [[1]])
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        assert kw_passed["context"] == {"allowed_company_ids": [7]}

    def test_caller_can_override_company_ids_explicitly(self) -> None:
        client, mock_obj = _client_with_company(company_id=7)
        client.execute_kw(
            "res.partner", "read", [[1]],
            {"context": {"allowed_company_ids": [99], "lang": "en_US"}},
        )
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        # Caller-supplied allowed_company_ids wins
        assert kw_passed["context"]["allowed_company_ids"] == [99]
        assert kw_passed["context"]["lang"] == "en_US"

    def test_no_company_no_caller_context_omits_context(self) -> None:
        client, mock_obj = _client_with_company(company_id=None)
        client.execute_kw("res.partner", "read", [[1]])
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        # No context to add either way
        assert "context" not in kw_passed

    def test_no_company_with_caller_context(self) -> None:
        client, mock_obj = _client_with_company(company_id=None)
        client.execute_kw("res.partner", "read", [[1]], {"context": {"lang": "en_US"}})
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        assert kw_passed["context"] == {"lang": "en_US"}

    def test_other_kw_keys_pass_through(self) -> None:
        client, mock_obj = _client_with_company(company_id=7)
        client.execute_kw(
            "res.partner", "search_read", [[]],
            {"limit": 10, "offset": 0, "context": {"lang": "en_US"}},
        )
        kw_passed = mock_obj.execute_kw.call_args.args[6]
        assert kw_passed["limit"] == 10
        assert kw_passed["offset"] == 0
        assert kw_passed["context"]["lang"] == "en_US"
