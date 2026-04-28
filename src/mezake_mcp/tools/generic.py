"""Generic ORM tools covering every installed Odoo model.

These 10 tools replace the need for per-model curated tools. Claude uses
them to discover models, inspect schema, search / read / create / update
/ delete records, and invoke arbitrary workflow methods — on any model
the authenticated user has access to, including modules the MCP server
has never heard of.

All tools run as the authenticated user via `get_active_client()`, so
Odoo's own record rules, access rules, and multi-company constraints
are automatically enforced.

Return format: every tool returns a JSON string. Many2one fields appear
as `[id, display_name]`; x2many fields as a list of ids; missing
relational values as `false`. These are Odoo's native wire types — we
don't reshape them, because Claude already understands them after seeing
a single response.

Translations: every read/write tool accepts an optional `context`
parameter. Pass `{"lang": "en_US"}` to read or write a specific
language for translatable fields (page titles, view arch, product
names, etc.). Without `lang`, Odoo uses the authenticated user's
profile language. See `odoo_write` for examples.
"""

from __future__ import annotations

import json
from typing import Any

from mezake_mcp.mcp_instance import mcp
from mezake_mcp.odoo.client import get_active_client


def _run(model: str, method: str, args: list, kw: dict | None = None) -> Any:
    return get_active_client().execute_kw(model, method, args, kw or {})


def _with_context(kw: dict[str, Any], context: dict | None) -> dict[str, Any]:
    """Add a `context` key to `kw` if the caller provided one."""
    if context:
        kw["context"] = context
    return kw


def _dumps(value: Any) -> str:
    # `default=str` catches any datetime/date that slips through; almost
    # everything else Odoo returns is already JSON-native.
    return json.dumps(value, default=str, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════════════
# DISCOVERY
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def odoo_list_models(name_filter: str = "", limit: int = 200) -> str:
    """List installed Odoo models. Returns JSON array of {id, model, name, modules}.

    Use this as a first step when exploring what's available on an unfamiliar
    Odoo instance. Every installed module adds rows here.

    Args:
      name_filter: partial match against either the technical name
        (e.g. 'account.move') or the display label (e.g. 'Journal Entry').
        Empty returns all models up to `limit`.
      limit: max number of rows. Default 200. Cap around 1000 before Odoo
        starts to push back on memory.
    """
    if name_filter:
        domain = ["|", ["model", "ilike", name_filter], ["name", "ilike", name_filter]]
    else:
        domain = []
    rows = _run(
        "ir.model", "search_read", [domain],
        {"fields": ["id", "model", "name", "modules"], "limit": limit, "order": "model"},
    )
    return _dumps(rows)


@mcp.tool()
def odoo_describe_model(model: str, fields: list | None = None) -> str:
    """Return the schema for a model: for every field, the type, required
    flag, readonly flag, help text, selection choices (for selection
    fields), the related model name (for relational fields), and the
    `translate` flag.

    Always call this before constructing a `search` domain or `create`
    payload against an unfamiliar model — Odoo field names don't always
    match what you'd guess (e.g. `account.move.partner_id`, not `customer`).

    The `translate` flag tells you which fields you can write per-language
    via the `context={"lang": "en_US"}` parameter on `odoo_write`.

    Args:
      model: technical name, e.g. 'account.bank.statement.line'.
      fields: optional list of field names to inspect. Omit to get every field.
    """
    attrs = [
        "string", "type", "required", "readonly", "help",
        "selection", "relation", "store", "compute", "related",
        "translate",
    ]
    schema = _run(model, "fields_get", [fields or []], {"attributes": attrs})
    return _dumps(schema)


# ════════════════════════════════════════════════════════════════════════════
# READS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def odoo_search(
    model: str,
    domain: list | None = None,
    limit: int = 200,
    offset: int = 0,
    order: str = "",
    context: dict | None = None,
) -> str:
    """Return IDs of records matching a domain.

    Prefer `odoo_search_read` when you also need field values. Use this
    when you only need IDs (e.g. to pass to `odoo_write`, `odoo_unlink`,
    `odoo_call`).

    Args:
      domain: Odoo domain, e.g. [["state","=","posted"],["amount_total",">",100]].
        Empty or omitted returns all records (bounded by `limit`).
      limit, offset, order: standard pagination + sort.
      context: optional Odoo call context. Use `{"active_test": False}` to
        include archived records, `{"lang": "en_US"}` to interpret string
        comparisons in a specific language, etc.
    """
    kw: dict[str, Any] = {"limit": limit, "offset": offset}
    if order:
        kw["order"] = order
    _with_context(kw, context)
    ids = _run(model, "search", [domain or []], kw)
    return _dumps(ids)


@mcp.tool()
def odoo_search_read(
    model: str,
    domain: list | None = None,
    fields: list | None = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "",
    context: dict | None = None,
) -> str:
    """Main read tool. Returns records as JSON.

    Wire format:
      - Many2one fields:         [id, "display_name"]
      - One2many / many2many:    [id, id, id]
      - Missing relational:      false
      - Date/Datetime:           string (UTC for datetimes)

    Args:
      fields: names to include. Omit for Odoo's default set (which skips
        binary/heavy fields). Always narrow to the fields you need — full
        record reads can be large.
      context: pass `{"lang": "en_US"}` to read translatable fields in a
        specific language. Without `lang`, Odoo returns the user-profile
        language. Reading the same record in two languages is the way to
        confirm a translation actually exists.
    """
    kw: dict[str, Any] = {"limit": limit, "offset": offset}
    if fields:
        kw["fields"] = fields
    if order:
        kw["order"] = order
    _with_context(kw, context)
    records = _run(model, "search_read", [domain or []], kw)
    return _dumps(records)


@mcp.tool()
def odoo_read(
    model: str,
    ids: list,
    fields: list | None = None,
    context: dict | None = None,
) -> str:
    """Hydrate records by ID. Prefer `odoo_search_read` unless you already
    have IDs in hand.

    Args:
      ids: list of integer IDs.
      fields: names to return. Omit for the default set.
      context: optional Odoo context, e.g. `{"lang": "en_US"}`.
    """
    kw: dict[str, Any] = {}
    if fields:
        kw["fields"] = fields
    _with_context(kw, context)
    records = _run(model, "read", [ids], kw)
    return _dumps(records)


@mcp.tool()
def odoo_read_group(
    model: str,
    domain: list | None = None,
    fields: list | None = None,
    groupby: list | None = None,
    limit: int = 100,
    offset: int = 0,
    orderby: str = "",
    context: dict | None = None,
) -> str:
    """Aggregate / group records — the tool for reports and dashboards.

    Examples:
      Revenue by month:
        odoo_read_group(
          'account.move',
          [['move_type','=','out_invoice'], ['state','=','posted']],
          ['amount_total:sum'],
          ['invoice_date:month'])

      AR by partner, top 10:
        odoo_read_group(
          'account.move.line',
          [['account_id.account_type','=','asset_receivable'],
           ['reconciled','=', false]],
          ['balance:sum'],
          ['partner_id'],
          orderby='balance desc', limit=10)

    Args:
      fields: aggregate specs. `'amount:sum'` / `'amount:avg'` / `'amount:max'`
        etc., or a plain field name for Odoo's default aggregator.
      groupby: group keys, e.g. ['partner_id'] or ['invoice_date:month'].
      orderby: e.g. 'balance desc'.
      context: optional Odoo context.
    """
    kw: dict[str, Any] = {"limit": limit, "offset": offset}
    if orderby:
        kw["orderby"] = orderby
    _with_context(kw, context)
    rows = _run(model, "read_group", [domain or [], fields or [], groupby or []], kw)
    return _dumps(rows)


# ════════════════════════════════════════════════════════════════════════════
# WRITES
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def odoo_create(model: str, values: dict, context: dict | None = None) -> str:
    """Create a single record. Returns the new ID as JSON `{"id": N}`.

    Call `odoo_describe_model(model)` first to confirm required fields
    and correct field names. For relational values:
      - Many2one: pass a single ID, e.g. {'partner_id': 42}
      - One2many / Many2many commands (standard Odoo tuple-ops):
          (0, 0, {field: value, ...})  — create & link a new record
          (4, id)                      — link an existing record
          (6, 0, [id, id, ...])        — replace the entire set
          (5, 0)                       — unlink all
          (3, id)                      — unlink just one

    Args:
      values: field -> value dict.
      context: optional Odoo context. Pass `{"lang": "en_US"}` to seed
        translatable fields in a specific language at creation time.

    Example:
      odoo_create('res.partner', {
        'name': 'Acme Corp',
        'is_company': true,
        'email': 'billing@acme.com',
        'category_id': [(6, 0, [7, 11])]   // set tags to 7 and 11
      })
    """
    kw = _with_context({}, context)
    new_id = _run(model, "create", [values], kw)
    return _dumps({"id": new_id})


@mcp.tool()
def odoo_write(
    model: str,
    ids: list,
    values: dict,
    context: dict | None = None,
) -> str:
    """Update existing records. Applies `values` to every ID in `ids`.

    Returns `{"updated": N}` on success.

    ### Translations (Odoo 17+)

    Translatable fields (`name`, `arch_db`, `description`, etc. — anything
    `odoo_describe_model` reports with `translate: true`) are stored as
    JSONB keyed by language code. To write a specific language, pass
    `context={"lang": "<code>"}`. Without `lang`, the write goes to the
    *authenticated user's* profile language, which is rarely what you want
    when seeding translations.

    Translation workflow:
      1. List installed languages:
         odoo_search_read('res.lang', [['active','=', true]],
                          ['code', 'name'])
      2. Write the source text in the default language:
         odoo_write('website.page', [42], {'name': 'Acerca de'})
      3. Write the translation in another language:
         odoo_write('website.page', [42], {'name': 'About Us'},
                    context={'lang': 'en_US'})
      4. Verify by reading both:
         odoo_read('website.page', [42], ['name'],
                   context={'lang': 'es_DO'})
         odoo_read('website.page', [42], ['name'],
                   context={'lang': 'en_US'})

    Other examples:
      Reassign two leads to another salesperson + add a tag:
        odoo_write('crm.lead', [42, 43], {
          'user_id': 7,
          'tag_ids': [(4, 12)]
        })

      Translate a website view's HTML body to English:
        odoo_write('ir.ui.view', [view_id],
                   {'arch_db': '<English QWeb>'},
                   context={'lang': 'en_US'})
    """
    kw = _with_context({}, context)
    _run(model, "write", [ids, values], kw)
    return _dumps({"updated": len(ids)})


@mcp.tool()
def odoo_translate_field(
    model: str,
    record_ids: list,
    field: str,
    translations: dict,
) -> str:
    """Update per-language translations of a translatable field WITHOUT
    rewriting the source-language content. This is the right tool for
    QWeb view bodies (`ir.ui.view.arch_db`), product names, blog posts,
    snippet text — anything where you want to add English translations
    on top of an existing Spanish (or other source-language) record.

    Why this exists separately from `odoo_write`:

    For simple translatable fields (`name`, `description`, etc.),
    `odoo_write(model, ids, values, context={"lang": "<code>"})` works
    fine — it just writes the new value to that language's slot in the
    JSONB.

    For QWeb view bodies (`arch_db`), the same approach is dangerous.
    Odoo aligns translatable strings between the new and source-language
    XML by tree position. A structural mismatch (one extra div, a
    different class) corrupts translations across BOTH languages. This
    tool calls Odoo's purpose-built `update_field_translations` method
    which operates string-by-string and never touches XML structure.

    Args:
      model: technical name, e.g. 'ir.ui.view', 'product.template'.
      record_ids: list of integer record IDs to translate.
      field: technical field name, e.g. 'arch_db', 'name', 'description'.
        Must be a translatable field (`translate: true` in
        `odoo_describe_model`).
      translations: dict keyed by language code. Each value is itself a
        dict mapping the source-language text to the translation.

    Examples:

      Translate two strings in a Spanish website page to English:
        odoo_translate_field('ir.ui.view', [view_id], 'arch_db', {
          'en_US': {
            'Acerca de': 'About Us',
            'Nuestra historia': 'Our Story',
            'Contacto': 'Contact',
          }
        })

      Translate a product name into multiple languages:
        odoo_translate_field('product.template', [42], 'name', {
          'en_US': {'Cantina Redonda 750 ml': 'Round Canteen 750 ml'},
          'fr_FR': {'Cantina Redonda 750 ml': 'Bidon Rond 750 ml'},
        })

    Returns the underlying call's result as JSON (typically `true`).

    Workflow tip: read the source-language field first to see exactly
    which strings are translatable in this view, then map each one to
    its translation. Don't try to write back the full HTML — feed only
    the individual strings.
    """
    kw: dict[str, Any] = {}
    result = _run(
        model, "update_field_translations",
        [record_ids, field, translations],
        kw,
    )
    return _dumps(result)


@mcp.tool()
def odoo_unlink(model: str, ids: list) -> str:
    """Delete records. This is destructive — only call with explicit
    user confirmation in the conversation. Returns `{"deleted": N}`.

    Odoo will refuse deletion when records are referenced elsewhere (e.g.
    posted invoices, invoiced sale orders). In that case, archive instead:
      odoo_write(model, ids, {'active': false})
    """
    _run(model, "unlink", [ids])
    return _dumps({"deleted": len(ids)})


# ════════════════════════════════════════════════════════════════════════════
# CATCH-ALL
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def odoo_call(
    model: str,
    method: str,
    args: list | None = None,
    kwargs: dict | None = None,
) -> str:
    """Invoke any method on any model. Use for workflow transitions,
    button handlers, and custom methods not covered by the specific CRUD
    tools above.

    IMPORTANT: for recordset methods (most buttons / workflow actions),
    the first element of `args` must itself be a LIST of IDs — that's
    why you often see `[[42]]`.

    For Odoo's call context (lang, allowed_company_ids, active_test, …),
    pass it under `kwargs` as `{"context": {"lang": "en_US"}}`.

    Common patterns:
      Post an invoice:
        odoo_call('account.move', 'action_post', [[42]])
      Confirm a sale order:
        odoo_call('sale.order', 'action_confirm', [[10]])
      Cancel an invoice:
        odoo_call('account.move', 'button_cancel', [[42]])
      Reconcile journal-entry lines:
        odoo_call('account.move.line', 'reconcile', [[[line_id_1, line_id_2]]])
      Post a chatter message:
        odoo_call('crm.lead', 'message_post', [[1]], {'body': 'Hello'})
      Validate a bank statement:
        odoo_call('account.bank.statement', 'button_post', [[statement_id]])

    Returns whatever the method returned, serialized as JSON.
    """
    result = _run(model, method, args or [], kwargs or {})
    return _dumps(result)
