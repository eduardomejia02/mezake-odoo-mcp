"""Legacy tool set — behavior-preserving port of the original v2.0 server.py.

Every tool here matches the previous implementation exactly. This module
is intentionally kept as one file during the refactor; later phases will
replace most of these with generic ORM tools + a smaller set of curated
workflows and retire this file.
"""

from __future__ import annotations

import re

from mezake_mcp.config import get_settings
from mezake_mcp.mcp_instance import mcp
from mezake_mcp.odoo.client import _ctx, _today, _x  # noqa: F401 — _ctx re-exported for parity


# ════════════════════════════════════════════════════════════════════════════
# COMPANY
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_active_company() -> str:
    """Show which company this MCP instance is locked to."""
    s = get_settings()
    if s.odoo_company_id:
        return f"🏢 Active company: {s.active_company_label} (ID: {s.odoo_company_id})"
    return "🏢 No company lock — showing data across all companies."


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_dashboard() -> str:
    """Full business snapshot: CRM, Accounting, Inventory, HR, Contacts."""
    s = get_settings()
    active_leads     = _x("crm.lead",        "search_count", [[["active", "=", True]]])
    won_leads        = _x("crm.lead",        "search_count", [[["stage_id.is_won", "=", True], ["active", "=", True]]])
    open_invoices    = _x("account.move",    "search_count", [[["move_type", "=", "out_invoice"], ["payment_state", "=", "not_paid"], ["state", "=", "posted"]]])
    overdue_invoices = _x("account.move",    "search_count", [[["move_type", "=", "out_invoice"], ["payment_state", "=", "not_paid"], ["state", "=", "posted"], ["invoice_date_due", "<", _today()]]])
    open_bills       = _x("account.move",    "search_count", [[["move_type", "=", "in_invoice"], ["payment_state", "=", "not_paid"], ["state", "=", "posted"]]])
    low_stock        = _x("product.product", "search_count", [[["type", "=", "product"], ["qty_available", "<=", 5]]])
    total_contacts   = _x("res.partner",     "search_count", [[["active", "=", True], ["is_company", "=", False]]])
    total_companies  = _x("res.partner",     "search_count", [[["active", "=", True], ["is_company", "=", True]]])
    try:
        employees = _x("hr.employee", "search_count", [[["active", "=", True]]])
    except Exception:
        employees = "N/A"
    company_label = f" [{s.active_company_label}]" if s.odoo_company_id else " [All Companies]"
    return f"""📊  Business Dashboard{company_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯  CRM
    Active Leads / Opportunities : {active_leads}
    Won Deals                    : {won_leads}
💰  Accounting
    Open Customer Invoices       : {open_invoices}
    Overdue Invoices             : {overdue_invoices}  ⚠️
    Open Vendor Bills            : {open_bills}
📦  Inventory
    Products with Low Stock (≤5) : {low_stock}
👥  Contacts
    Individual Contacts          : {total_contacts}
    Companies                    : {total_companies}
👔  HR
    Active Employees             : {employees}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


# ════════════════════════════════════════════════════════════════════════════
# CRM
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_pipeline_summary() -> str:
    """CRM pipeline: lead count and expected revenue by stage."""
    stages = _x("crm.stage", "search_read", [[]], {"fields": ["id", "name", "sequence"], "order": "sequence"})
    lines, total = [], 0
    for stage in stages:
        leads = _x("crm.lead", "search_read", [[["stage_id", "=", stage["id"]], ["active", "=", True]]], {"fields": ["expected_revenue"]})
        rev = sum(lead.get("expected_revenue", 0) for lead in leads)
        total += rev
        lines.append(f"  {stage['name']:<28} {len(leads):>4} leads   ${rev:>12,.2f}")
    return "🎯  CRM Pipeline\n" + "─" * 58 + "\n" + "\n".join(lines) + "\n" + "─" * 58 + f"\n  TOTAL{' ' * 23} ${total:>12,.2f}"


@mcp.tool()
def search_leads(query: str = "", stage: str = "", assigned_to: str = "",
                 source: str = "", date_from: str = "", date_to: str = "",
                 limit: int = 20) -> str:
    """Search CRM leads by name, stage, assigned user, source/campaign, or creation date.
    date_from / date_to: YYYY-MM-DD format."""
    domain = [["active", "=", True]]
    if query:       domain.append(["name", "ilike", query])
    if stage:       domain.append(["stage_id.name", "ilike", stage])
    if assigned_to: domain.append(["user_id.name", "ilike", assigned_to])
    if source:      domain.append(["source_id.name", "ilike", source])
    if date_from:   domain.append(["create_date", ">=", date_from])
    if date_to:     domain.append(["create_date", "<=", date_to + " 23:59:59"])
    leads = _x("crm.lead", "search_read", [domain], {
        "fields": ["name", "partner_name", "email_from", "phone", "stage_id",
                   "expected_revenue", "probability", "user_id", "create_date", "source_id", "medium_id"],
        "limit": limit, "order": "create_date desc"})
    if not leads:
        return "No leads found."
    out = [f"Found {len(leads)} lead(s):\n"]
    for lead in leads:
        out.append(
            f"[{lead['id']}] {lead['name']}\n"
            f"  Contact : {lead.get('partner_name', '—')} | {lead.get('email_from', '—')} | {lead.get('phone', '—')}\n"
            f"  Stage   : {lead['stage_id'][1] if lead.get('stage_id') else '—'} | "
            f"Revenue: ${lead.get('expected_revenue', 0):,.2f} | Prob: {lead.get('probability', 0):.0f}%\n"
            f"  Owner   : {lead['user_id'][1] if lead.get('user_id') else 'Unassigned'} | "
            f"Source: {lead['source_id'][1] if lead.get('source_id') else '—'}\n"
        )
    return "\n".join(out)


@mcp.tool()
def create_lead(name: str, partner_name: str, email: str = "", phone: str = "",
                expected_revenue: float = 0.0, stage: str = "", source: str = "",
                assigned_to_email: str = "", notes: str = "") -> str:
    """Create a new CRM lead/opportunity."""
    vals: dict = {"name": name, "partner_name": partner_name, "email_from": email,
                  "phone": phone, "expected_revenue": expected_revenue, "description": notes}
    if stage:
        s = _x("crm.stage", "search_read", [[["name", "ilike", stage]]], {"fields": ["id"], "limit": 1})
        if s: vals["stage_id"] = s[0]["id"]
    if source:
        src = _x("utm.source", "search_read", [[["name", "ilike", source]]], {"fields": ["id"], "limit": 1})
        if src: vals["source_id"] = src[0]["id"]
    if assigned_to_email:
        u = _x("res.users", "search_read", [[["login", "=", assigned_to_email]]], {"fields": ["id"], "limit": 1})
        if u: vals["user_id"] = u[0]["id"]
    lid = _x("crm.lead", "create", [vals])
    return f"✅ Lead created | ID: {lid} | '{name}' → {partner_name}"


@mcp.tool()
def update_lead(lead_id: int, stage: str = "", expected_revenue: float = None,
                probability: float = None, notes: str = "", assign_to_email: str = "") -> str:
    """Update a CRM lead: stage, revenue, probability, notes, or reassign."""
    vals: dict = {}
    if stage:
        s = _x("crm.stage", "search_read", [[["name", "ilike", stage]]], {"fields": ["id", "name"], "limit": 1})
        if not s:
            return f"❌ Stage '{stage}' not found."
        vals["stage_id"] = s[0]["id"]
    if expected_revenue is not None: vals["expected_revenue"] = expected_revenue
    if probability is not None:      vals["probability"]       = probability
    if notes:                        vals["description"]       = notes
    if assign_to_email:
        u = _x("res.users", "search_read", [[["login", "=", assign_to_email]]], {"fields": ["id"], "limit": 1})
        if not u:
            return f"❌ User '{assign_to_email}' not found."
        vals["user_id"] = u[0]["id"]
    if not vals:
        return "Nothing to update — provide at least one field."
    _x("crm.lead", "write", [[lead_id], vals])
    return f"✅ Lead {lead_id} updated: {', '.join(vals.keys())}"


@mcp.tool()
def mark_lead_won(lead_id: int) -> str:
    """Mark a CRM lead as Won."""
    _x("crm.lead", "action_set_won_rainbowman", [[lead_id]])
    return f"🏆 Lead {lead_id} marked as WON."


@mcp.tool()
def mark_lead_lost(lead_id: int, reason: str = "") -> str:
    """Mark a CRM lead as Lost with an optional reason."""
    vals: dict = {"active": False}
    if reason:
        lost_reasons = _x("crm.lost.reason", "search_read", [[["name", "ilike", reason]]], {"fields": ["id"], "limit": 1})
        if lost_reasons:
            vals["lost_reason_ids"] = [(4, lost_reasons[0]["id"])]
    _x("crm.lead", "write", [[lead_id], vals])
    return f"❌ Lead {lead_id} marked as LOST. Reason: {reason or 'not specified'}"


@mcp.tool()
def log_lead_note(lead_id: int, note: str) -> str:
    """Log a note/comment on a CRM lead."""
    _x("crm.lead", "message_post", [[lead_id]], {"body": note, "message_type": "comment"})
    return f"✅ Note logged on lead {lead_id}."


@mcp.tool()
def schedule_activity(lead_id: int, activity_type: str, summary: str,
                      due_date: str, assigned_to_email: str = "") -> str:
    """Schedule a follow-up activity on a CRM lead.
    activity_type: 'call', 'email', 'meeting', 'todo'
    due_date: YYYY-MM-DD format"""
    type_map = {"call": "Phone Call", "email": "Email", "meeting": "Meeting", "todo": "To-Do"}
    type_name = type_map.get(activity_type.lower(), activity_type)
    act_types = _x("mail.activity.type", "search_read", [[["name", "ilike", type_name]]], {"fields": ["id"], "limit": 1})
    if not act_types:
        return f"❌ Activity type '{activity_type}' not found."
    vals: dict = {
        "activity_type_id": act_types[0]["id"],
        "summary": summary,
        "date_deadline": due_date,
        "res_id": lead_id,
        "res_model": "crm.lead",
    }
    if assigned_to_email:
        u = _x("res.users", "search_read", [[["login", "=", assigned_to_email]]], {"fields": ["id"], "limit": 1})
        if u: vals["user_id"] = u[0]["id"]
    _x("mail.activity", "create", [vals])
    return f"✅ Activity '{summary}' scheduled for {due_date} on lead {lead_id}."


@mcp.tool()
def get_utm_sources() -> str:
    """List all UTM sources and campaigns for lead attribution tracking."""
    sources   = _x("utm.source",   "search_read", [[]], {"fields": ["id", "name"]})
    campaigns = _x("utm.campaign", "search_read", [[]], {"fields": ["id", "name"]})
    out = ["📊 UTM Sources & Campaigns\n"]
    out.append(f"Sources ({len(sources)}):")
    for s in sources:
        count = _x("crm.lead", "search_count", [[["source_id", "=", s["id"]], ["active", "=", True]]])
        out.append(f"  [{s['id']}] {s['name']:<30} {count} active leads")
    out.append(f"\nCampaigns ({len(campaigns)}):")
    for c in campaigns:
        count = _x("crm.lead", "search_count", [[["campaign_id", "=", c["id"]], ["active", "=", True]]])
        out.append(f"  [{c['id']}] {c['name']:<30} {count} active leads")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_contacts(query: str, is_company: bool = False,
                    company_name: str = "", country: str = "", limit: int = 15) -> str:
    """Search contacts or companies by name, email, phone, parent company, or country."""
    domain = [["active", "=", True], ["is_company", "=", is_company],
              "|", "|", ["name", "ilike", query], ["email", "ilike", query], ["phone", "ilike", query]]
    if company_name: domain.append(["parent_id.name", "ilike", company_name])
    if country:      domain.append(["country_id.name", "ilike", country])
    contacts = _x("res.partner", "search_read", [domain], {
        "fields": ["name", "email", "phone", "city", "country_id", "is_company", "company_name"], "limit": limit})
    if not contacts:
        return "No contacts found."
    out = [f"Found {len(contacts)} contact(s):\n"]
    for c in contacts:
        out.append(
            f"[{c['id']}] {c['name']}{'  🏢' if c.get('is_company') else ''}\n"
            f"  Email: {c.get('email', '—')} | Phone: {c.get('phone', '—')}\n"
            f"  Location: {c.get('city', '—')}, {c['country_id'][1] if c.get('country_id') else '—'}\n"
        )
    return "\n".join(out)


@mcp.tool()
def create_contact(name: str, email: str = "", phone: str = "",
                   company_name: str = "", is_company: bool = False, city: str = "",
                   street: str = "", notes: str = "") -> str:
    """Create a new contact or company."""
    vals: dict = {"name": name, "email": email, "phone": phone,
                  "is_company": is_company, "city": city, "street": street, "comment": notes}
    if company_name and not is_company:
        co = _x("res.partner", "search_read", [[["name", "ilike", company_name], ["is_company", "=", True]]],
                {"fields": ["id"], "limit": 1})
        if co: vals["parent_id"] = co[0]["id"]
    cid = _x("res.partner", "create", [vals])
    return f"✅ Contact created | ID: {cid} | {name}"


@mcp.tool()
def update_contact(contact_id: int, name: str = "", email: str = "", phone: str = "",
                   city: str = "", street: str = "", notes: str = "") -> str:
    """Update an existing contact."""
    vals: dict = {}
    if name:   vals["name"]    = name
    if email:  vals["email"]   = email
    if phone:  vals["phone"]   = phone
    if city:   vals["city"]    = city
    if street: vals["street"]  = street
    if notes:  vals["comment"] = notes
    if not vals:
        return "Nothing to update."
    _x("res.partner", "write", [[contact_id], vals])
    return f"✅ Contact {contact_id} updated."


# ════════════════════════════════════════════════════════════════════════════
# ACCOUNTING — INVOICES
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_accounting_summary() -> str:
    """Accounting overview: receivables, payables, overdue amounts."""
    def _sum(domain):
        rows = _x("account.move.line", "read_group", [domain], ["balance"], [])
        return abs(rows[0].get("balance", 0)) if rows else 0
    ar = _sum([["account_id.account_type", "=", "asset_receivable"], ["reconciled", "=", False], ["parent_state", "=", "posted"]])
    ap = _sum([["account_id.account_type", "=", "liability_payable"], ["reconciled", "=", False], ["parent_state", "=", "posted"]])
    overdue = _x("account.move", "search_read", [[
        ["move_type", "=", "out_invoice"], ["payment_state", "=", "not_paid"],
        ["state", "=", "posted"], ["invoice_date_due", "<", _today()]]], {"fields": ["amount_residual"]})
    od = sum(i.get("amount_residual", 0) for i in overdue)
    return (f"💰 Accounting Summary\n{'─' * 44}\n"
            f"  Receivable (owed to you) : ${ar:>12,.2f}\n"
            f"  Payable    (you owe)     : ${ap:>12,.2f}\n"
            f"  Net Position             : ${ar - ap:>12,.2f}\n"
            f"  Overdue from customers   : ${od:>12,.2f}  ⚠️")


@mcp.tool()
def get_invoices(status: str = "open", partner_name: str = "", limit: int = 20,
                 date_from: str = "", date_to: str = "", move_type: str = "out_invoice",
                 currency: str = "", min_amount: float = None, max_amount: float = None) -> str:
    """List invoices or vendor bills.
    status: open, paid, draft, overdue, all.
    move_type: out_invoice (customer invoice) or in_invoice (vendor bill).
    date_from / date_to: YYYY-MM-DD format.
    currency: e.g. USD, DOP, EUR.
    min_amount / max_amount: filter by total amount."""
    domain = [["move_type", "=", move_type]]
    if status == "open":      domain += [["payment_state", "=", "not_paid"], ["state", "=", "posted"]]
    elif status == "paid":    domain += [["payment_state", "=", "paid"]]
    elif status == "draft":   domain += [["state", "=", "draft"]]
    elif status == "overdue": domain += [["payment_state", "=", "not_paid"], ["state", "=", "posted"], ["invoice_date_due", "<", _today()]]
    if partner_name:                domain.append(["partner_id.name", "ilike", partner_name])
    if date_from:                   domain.append(["invoice_date", ">=", date_from])
    if date_to:                     domain.append(["invoice_date", "<=", date_to])
    if currency:                    domain.append(["currency_id.name", "=", currency.upper()])
    if min_amount is not None:      domain.append(["amount_total", ">=", min_amount])
    if max_amount is not None:      domain.append(["amount_total", "<=", max_amount])
    invoices = _x("account.move", "search_read", [domain], {
        "fields": ["name", "partner_id", "invoice_date", "invoice_date_due", "amount_total", "amount_residual", "payment_state", "state"],
        "limit": limit, "order": "invoice_date desc"})
    if not invoices:
        return f"No {status} invoices found."
    total = sum(i.get("amount_residual", 0) for i in invoices)
    label = "Vendor Bills" if move_type == "in_invoice" else "Invoices"
    date_range = f" ({date_from} to {date_to})" if date_from or date_to else ""
    out = [f"📄 {status.upper()} {label}{date_range} ({len(invoices)})\n"]
    for i in invoices:
        out.append(
            f"  {i['name']:<18} {i['partner_id'][1] if i.get('partner_id') else '—':<28} "
            f"${i.get('amount_total', 0):>10,.2f} | Due: ${i.get('amount_residual', 0):>10,.2f} | "
            f"Date: {i.get('invoice_date', '—')} | {i.get('payment_state', '—')}"
        )
    out.append(f"\n  Total Outstanding: ${total:,.2f}")
    return "\n".join(out)


@mcp.tool()
def create_invoice(partner_name: str, lines: str, move_type: str = "out_invoice",
                   notes: str = "", due_date: str = "") -> str:
    """Create a customer invoice or vendor bill.
    move_type: out_invoice or in_invoice.
    lines: comma-separated 'product_name:qty:price' e.g. 'Consulting:2:500,Setup:1:200'"""
    partners = _x("res.partner", "search_read", [[["name", "ilike", partner_name]]], {"fields": ["id", "name"], "limit": 1})
    if not partners:
        return f"❌ Partner '{partner_name}' not found."
    invoice_lines = []
    for line in lines.split(","):
        parts = [p.strip() for p in line.split(":")]
        if len(parts) < 3: continue
        prod_name, qty, price = parts[0], float(parts[1]), float(parts[2])
        products = _x("product.product", "search_read", [[["name", "ilike", prod_name]]], {"fields": ["id", "name"], "limit": 1})
        if products:
            invoice_lines.append((0, 0, {"product_id": products[0]["id"], "quantity": qty, "price_unit": price}))
        else:
            invoice_lines.append((0, 0, {"name": prod_name, "quantity": qty, "price_unit": price}))
    if not invoice_lines:
        return "❌ No valid lines parsed. Format: 'product:qty:price'"
    vals: dict = {"move_type": move_type, "partner_id": partners[0]["id"],
                  "narration": notes, "invoice_line_ids": invoice_lines}
    if due_date: vals["invoice_date_due"] = due_date
    inv_id = _x("account.move", "create", [vals])
    total = sum(line[2]["quantity"] * line[2]["price_unit"] for line in invoice_lines)
    label = "Vendor bill" if move_type == "in_invoice" else "Invoice"
    return f"✅ {label} created (draft) | ID: {inv_id} | {partners[0]['name']} | Total: ${total:,.2f}"


@mcp.tool()
def confirm_invoice(invoice_id: int) -> str:
    """Confirm (post) a draft invoice or vendor bill."""
    _x("account.move", "action_post", [[invoice_id]])
    return f"✅ Invoice {invoice_id} confirmed and posted."


@mcp.tool()
def mark_invoice_paid(invoice_id: int, payment_date: str = "",
                      journal_name: str = "Bank") -> str:
    """Register a payment for an invoice, marking it as paid.
    payment_date: YYYY-MM-DD (defaults to today). journal_name: e.g. Bank, Cash."""
    invoice = _x("account.move", "search_read", [[["id", "=", invoice_id]]],
                 {"fields": ["partner_id", "amount_residual", "move_type", "currency_id"]})
    if not invoice:
        return f"❌ Invoice {invoice_id} not found."
    inv = invoice[0]
    journals = _x("account.journal", "search_read", [[["name", "ilike", journal_name]]],
                  {"fields": ["id", "name"], "limit": 1})
    if not journals:
        return f"❌ Journal '{journal_name}' not found."
    pay_type = "inbound" if inv["move_type"] == "out_invoice" else "outbound"
    payment_vals = {
        "payment_type":       pay_type,
        "partner_type":       "customer" if inv["move_type"] == "out_invoice" else "supplier",
        "partner_id":         inv["partner_id"][0],
        "amount":             inv["amount_residual"],
        "journal_id":         journals[0]["id"],
        "date":               payment_date or _today(),
        "currency_id":        inv["currency_id"][0] if inv.get("currency_id") else False,
    }
    pay_id = _x("account.payment", "create", [payment_vals])
    _x("account.payment", "action_post", [[pay_id]])
    # Reconcile
    pay_lines = _x("account.payment", "search_read", [[["id", "=", pay_id]]],
                   {"fields": ["move_id"]})
    inv_lines  = _x("account.move.line", "search_read",
                    [[["move_id", "=", invoice_id], ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]]]],
                    {"fields": ["id"]})
    pay_mv_lines = _x("account.move.line", "search_read",
                      [[["move_id", "=", pay_lines[0]["move_id"][0]],
                        ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]]]],
                      {"fields": ["id"]})
    all_ids = [line["id"] for line in inv_lines + pay_mv_lines]
    if all_ids:
        _x("account.move.line", "reconcile", [all_ids])
    return f"✅ Payment registered for invoice {invoice_id} | Date: {payment_date or _today()} | Journal: {journals[0]['name']}"


@mcp.tool()
def create_bulk_journal_entry(journal_name: str, date: str, lines: str,
                              reference: str = "") -> str:
    """Create a manual journal entry with multiple lines.
    date: YYYY-MM-DD
    lines: semicolon-separated 'account_code:debit:credit:label'
    e.g. '1010:1000:0:Revenue;2010:0:1000:Cash'"""
    journals = _x("account.journal", "search_read", [[["name", "ilike", journal_name]]],
                  {"fields": ["id", "name"], "limit": 1})
    if not journals:
        return f"❌ Journal '{journal_name}' not found."
    move_lines = []
    for line in lines.split(";"):
        parts = [p.strip() for p in line.split(":")]
        if len(parts) < 4: continue
        code, debit, credit, label = parts[0], float(parts[1]), float(parts[2]), parts[3]
        accounts = _x("account.account", "search_read", [[["code", "=", code]]], {"fields": ["id"], "limit": 1})
        if not accounts:
            return f"❌ Account code '{code}' not found."
        move_lines.append((0, 0, {"account_id": accounts[0]["id"], "debit": debit,
                                   "credit": credit, "name": label}))
    if not move_lines:
        return "❌ No valid lines parsed."
    move_id = _x("account.move", "create", [{
        "move_type": "entry", "journal_id": journals[0]["id"],
        "date": date, "ref": reference, "line_ids": move_lines,
    }])
    _x("account.move", "action_post", [[move_id]])
    return f"✅ Journal entry created & posted | ID: {move_id} | {len(move_lines)} lines"


@mcp.tool()
def get_revenue_report(date_from: str, date_to: str) -> str:
    """Revenue report for a date range. date_from/date_to: YYYY-MM-DD."""
    invoices = _x("account.move", "search_read", [[
        ["move_type", "=", "out_invoice"], ["state", "=", "posted"],
        ["invoice_date", ">=", date_from], ["invoice_date", "<=", date_to],
    ]], {"fields": ["name", "partner_id", "invoice_date", "amount_total", "amount_residual", "payment_state"]})
    if not invoices:
        return f"No invoices found between {date_from} and {date_to}."
    total_billed  = sum(i.get("amount_total", 0) for i in invoices)
    total_paid    = sum(i.get("amount_total", 0) - i.get("amount_residual", 0) for i in invoices)
    total_pending = sum(i.get("amount_residual", 0) for i in invoices)
    paid_count    = sum(1 for i in invoices if i.get("payment_state") == "paid")
    out = [f"📈 Revenue Report: {date_from} → {date_to}\n{'─' * 50}"]
    out.append(f"  Total Invoiced  : ${total_billed:>12,.2f}  ({len(invoices)} invoices)")
    out.append(f"  Total Collected : ${total_paid:>12,.2f}  ({paid_count} paid)")
    out.append(f"  Total Pending   : ${total_pending:>12,.2f}  ({len(invoices) - paid_count} unpaid)")
    out.append(f"  Collection Rate : {(total_paid / total_billed * 100) if total_billed else 0:.1f}%")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# HR & EMPLOYEES
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_employees(department: str = "", company_name: str = "", limit: int = 50) -> str:
    """List active employees, optionally filtered by department or company."""
    domain = [["active", "=", True]]
    if department:   domain.append(["department_id.name", "ilike", department])
    if company_name: domain.append(["company_id.name", "ilike", company_name])
    employees = _x("hr.employee", "search_read", [domain], {
        "fields": ["name", "job_title", "department_id", "work_email", "work_phone", "company_id"],
        "limit": limit})
    if not employees:
        return "No employees found."
    out = [f"👔 Employees ({len(employees)})\n"]
    for e in employees:
        out.append(
            f"[{e['id']}] {e['name']:<30} {e.get('job_title', '—'):<25}\n"
            f"  Dept: {e['department_id'][1] if e.get('department_id') else '—'} | "
            f"Email: {e.get('work_email', '—')} | "
            f"Company: {e['company_id'][1] if e.get('company_id') else '—'}\n"
        )
    return "\n".join(out)


@mcp.tool()
def create_employee(name: str, job_title: str = "", department: str = "",
                    work_email: str = "", work_phone: str = "",
                    company_name: str = "") -> str:
    """Create a new employee record."""
    vals: dict = {"name": name, "job_title": job_title,
                  "work_email": work_email, "work_phone": work_phone}
    if department:
        dept = _x("hr.department", "search_read", [[["name", "ilike", department]]], {"fields": ["id"], "limit": 1})
        if dept: vals["department_id"] = dept[0]["id"]
    if company_name:
        co = _x("res.company", "search_read", [[["name", "ilike", company_name]]], {"fields": ["id"], "limit": 1})
        if co: vals["company_id"] = co[0]["id"]
    eid = _x("hr.employee", "create", [vals])
    return f"✅ Employee created | ID: {eid} | {name}"


@mcp.tool()
def get_leaves(employee_name: str = "", status: str = "confirm", limit: int = 20) -> str:
    """View leave/time-off requests.
    status: draft, confirm, validate, refuse."""
    domain = [["state", "=", status]]
    if employee_name: domain.append(["employee_id.name", "ilike", employee_name])
    leaves = _x("hr.leave", "search_read", [domain], {
        "fields": ["employee_id", "holiday_status_id", "date_from", "date_to", "number_of_days", "state"],
        "limit": limit})
    if not leaves:
        return f"No {status} leave requests found."
    out = [f"🏖️  Leave Requests — {status.upper()} ({len(leaves)})\n"]
    for leave in leaves:
        out.append(
            f"  {leave['employee_id'][1] if leave.get('employee_id') else '—':<30} "
            f"{leave['holiday_status_id'][1] if leave.get('holiday_status_id') else '—':<20} "
            f"{leave.get('date_from', '—')[:10]} → {leave.get('date_to', '—')[:10]} "
            f"({leave.get('number_of_days', 0):.1f} days)"
        )
    return "\n".join(out)


@mcp.tool()
def approve_leave(leave_id: int) -> str:
    """Approve a leave request."""
    _x("hr.leave", "action_approve", [[leave_id]])
    return f"✅ Leave {leave_id} approved."


@mcp.tool()
def refuse_leave(leave_id: int, reason: str = "") -> str:
    """Refuse a leave request."""
    _x("hr.leave", "action_refuse", [[leave_id]])
    if reason:
        _x("hr.leave", "message_post", [[leave_id]], {"body": reason})
    return f"❌ Leave {leave_id} refused."


# ════════════════════════════════════════════════════════════════════════════
# PAYROLL
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_payslips(employee_name: str = "", date_from: str = "",
                  date_to: str = "", status: str = "done",
                  company_name: str = "", department: str = "", limit: int = 30) -> str:
    """List payslips. status: draft, verify, done.
    Filter by employee, date range, company, or department."""
    domain = [["state", "=", status]]
    if employee_name: domain.append(["employee_id.name", "ilike", employee_name])
    if date_from:     domain.append(["date_from", ">=", date_from])
    if date_to:       domain.append(["date_to", "<=", date_to])
    if company_name:  domain.append(["company_id.name", "ilike", company_name])
    if department:    domain.append(["employee_id.department_id.name", "ilike", department])
    slips = _x("hr.payslip", "search_read", [domain], {
        "fields": ["employee_id", "date_from", "date_to", "net_wage", "state", "company_id"],
        "limit": limit, "order": "date_from desc"})
    if not slips:
        return f"No {status} payslips found."
    total = sum(s.get("net_wage", 0) for s in slips)
    out = [f"💵 Payslips — {status.upper()} ({len(slips)})\n"]
    for s in slips:
        out.append(
            f"  {s['employee_id'][1] if s.get('employee_id') else '—':<30} "
            f"{s.get('date_from', '—')[:10]} → {s.get('date_to', '—')[:10]} "
            f"Net: ${s.get('net_wage', 0):>10,.2f}"
        )
    out.append(f"\n  Total Net Payroll: ${total:,.2f}")
    return "\n".join(out)


@mcp.tool()
def create_payslip(employee_name: str, date_from: str, date_to: str) -> str:
    """Create a payslip for an employee.
    date_from / date_to: YYYY-MM-DD (e.g. 2025-01-01 / 2025-01-31)"""
    employees = _x("hr.employee", "search_read", [[["name", "ilike", employee_name]]],
                   {"fields": ["id", "name"], "limit": 1})
    if not employees:
        return f"❌ Employee '{employee_name}' not found."
    slip_id = _x("hr.payslip", "create", [{
        "employee_id": employees[0]["id"],
        "date_from":   date_from,
        "date_to":     date_to,
    }])
    _x("hr.payslip", "compute_sheet", [[slip_id]])
    return f"✅ Payslip created & computed | ID: {slip_id} | {employees[0]['name']} | {date_from} → {date_to}"


@mcp.tool()
def confirm_payslip(payslip_id: int) -> str:
    """Confirm/validate a payslip (mark as done)."""
    _x("hr.payslip", "action_payslip_done", [[payslip_id]])
    return f"✅ Payslip {payslip_id} confirmed."


@mcp.tool()
def get_payroll_summary(date_from: str, date_to: str) -> str:
    """Payroll summary for a period by company and department."""
    slips = _x("hr.payslip", "search_read", [[
        ["state", "=", "done"],
        ["date_from", ">=", date_from],
        ["date_to", "<=", date_to],
    ]], {"fields": ["employee_id", "net_wage", "gross_wage", "company_id", "department_id"]})
    if not slips:
        return f"No confirmed payslips found between {date_from} and {date_to}."
    total_gross = sum(s.get("gross_wage", 0) for s in slips)
    total_net   = sum(s.get("net_wage", 0)   for s in slips)
    by_company: dict = {}
    for s in slips:
        co = s["company_id"][1] if s.get("company_id") else "Unknown"
        by_company.setdefault(co, {"gross": 0, "net": 0, "count": 0})
        by_company[co]["gross"] += s.get("gross_wage", 0)
        by_company[co]["net"]   += s.get("net_wage", 0)
        by_company[co]["count"] += 1
    out = [f"💵 Payroll Summary: {date_from} → {date_to}\n{'─' * 50}"]
    for co, data in by_company.items():
        out.append(f"  {co}\n    {data['count']} employees | Gross: ${data['gross']:,.2f} | Net: ${data['net']:,.2f}")
    out.append(f"\n{'─' * 50}\n  TOTAL — {len(slips)} payslips | Gross: ${total_gross:,.2f} | Net: ${total_net:,.2f}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# INVENTORY
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_products(query: str = "", category: str = "",
                    min_price: float = None, max_price: float = None,
                    in_stock_only: bool = False, limit: int = 20) -> str:
    """Search products with stock levels and pricing.
    min_price / max_price: filter by sale price.
    in_stock_only: if True, only show products with stock > 0."""
    domain = [["type", "in", ["product", "consu"]]]
    if query:                  domain.append(["name", "ilike", query])
    if category:               domain.append(["categ_id.name", "ilike", category])
    if min_price is not None:  domain.append(["list_price", ">=", min_price])
    if max_price is not None:  domain.append(["list_price", "<=", max_price])
    if in_stock_only:          domain.append(["qty_available", ">", 0])
    products = _x("product.product", "search_read", [domain], {
        "fields": ["name", "default_code", "qty_available", "virtual_available", "list_price", "standard_price", "categ_id"],
        "limit": limit})
    if not products:
        return "No products found."
    out = [f"📦 Products ({len(products)})\n"]
    for p in products:
        icon = "🔴" if p.get("qty_available", 0) <= 5 else "🟢"
        out.append(
            f"{icon} [{p.get('default_code', '—')}] {p['name']}\n"
            f"   Stock: {p.get('qty_available', 0):.0f} | Forecast: {p.get('virtual_available', 0):.0f} | "
            f"Price: ${p.get('list_price', 0):,.2f} | Cost: ${p.get('standard_price', 0):,.2f}\n"
        )
    return "\n".join(out)


@mcp.tool()
def get_low_stock_alert(threshold: int = 10) -> str:
    """List all products at or below a stock threshold."""
    products = _x("product.product", "search_read",
                  [[["type", "=", "product"], ["qty_available", "<=", threshold]]],
                  {"fields": ["name", "default_code", "qty_available", "virtual_available"], "limit": 200})
    if not products:
        return f"✅ All products are above {threshold} units."
    out = [f"⚠️  LOW STOCK ALERT — {len(products)} product(s) at or below {threshold} units:\n"]
    for p in sorted(products, key=lambda x: x.get("qty_available", 0)):
        out.append(f"  [{p.get('default_code', '—')}] {p['name']:<40} "
                   f"Stock: {p.get('qty_available', 0):.0f} | Forecast: {p.get('virtual_available', 0):.0f}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# WHATSAPP
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_whatsapp_messages(partner_name: str = "", limit: int = 20) -> str:
    """Read recent WhatsApp conversations."""
    domain = [["message_type", "=", "whatsapp_message"]]
    if partner_name: domain.append(["author_id.name", "ilike", partner_name])
    msgs = _x("mail.message", "search_read", [domain], {
        "fields": ["date", "author_id", "body", "res_id", "model"], "limit": limit, "order": "date desc"})
    if not msgs:
        return "No WhatsApp messages found."
    out = [f"💬 WhatsApp Messages ({len(msgs)})\n"]
    for m in msgs:
        body = re.sub(r"<[^>]+>", "", m.get("body", "")).strip()
        out.append(f"  {m.get('date', '')[:16]}  {m['author_id'][1] if m.get('author_id') else '—'}\n  {body[:140]}\n")
    return "\n".join(out)


@mcp.tool()
def send_whatsapp_message(partner_name: str, message: str) -> str:
    """Send a WhatsApp message to a contact via Odoo."""
    partners = _x("res.partner", "search_read", [[["name", "ilike", partner_name]]],
                  {"fields": ["id", "name", "phone"], "limit": 1})
    if not partners:
        return f"❌ Contact '{partner_name}' not found."
    p = partners[0]
    phone = p.get("phone")
    if not phone:
        return f"❌ No phone number for '{p['name']}'."
    _x("res.partner", "message_post", [[p["id"]]], {"body": message, "message_type": "whatsapp_message"})
    return f"✅ WhatsApp sent to {p['name']} ({phone})"


@mcp.tool()
def list_whatsapp_chatbots() -> str:
    """List all WhatsApp chatbot configurations in Odoo."""
    try:
        bots = _x("im_livechat.chatbot", "search_read", [[]], {
            "fields": ["name", "script_step_ids", "active"]})
        if not bots:
            return "No chatbots found."
        out = [f"🤖 WhatsApp Chatbots ({len(bots)})\n"]
        for b in bots:
            steps_count = len(b.get("script_step_ids", []))
            out.append(f"  [{b['id']}] {b['name']}  |  {steps_count} steps  |  {'Active' if b.get('active') else 'Inactive'}")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Chatbot module may not be installed: {str(e)[:100]}"


@mcp.tool()
def get_chatbot_steps(chatbot_id: int) -> str:
    """Get the steps/rules of a WhatsApp chatbot."""
    try:
        steps = _x("im_livechat.chatbot.script.step", "search_read",
                   [[["chatbot_script_id", "=", chatbot_id]]], {
                       "fields": ["message", "step_type", "answer_ids", "sequence"],
                       "order": "sequence"})
        if not steps:
            return f"No steps found for chatbot {chatbot_id}."
        out = [f"🤖 Chatbot {chatbot_id} Steps ({len(steps)})\n"]
        for s in steps:
            out.append(f"  [{s['id']}] Step {s.get('sequence', 0)} — {s.get('step_type', '—')}\n"
                       f"    Message: {s.get('message', '—')[:120]}\n")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Could not retrieve chatbot steps: {str(e)[:100]}"


@mcp.tool()
def create_chatbot_step(chatbot_id: int, message: str, step_type: str = "question_selection",
                        sequence: int = 10) -> str:
    """Add a new step to a WhatsApp chatbot.
    step_type: free_input_single, free_input_multi, question_selection, create_lead, create_ticket, forward_operator."""
    try:
        step_id = _x("im_livechat.chatbot.script.step", "create", [{
            "chatbot_script_id": chatbot_id,
            "message":           message,
            "step_type":         step_type,
            "sequence":          sequence,
        }])
        return f"✅ Chatbot step created | ID: {step_id} | '{message[:60]}'"
    except Exception as e:
        return f"❌ Could not create chatbot step: {str(e)[:100]}"


# ════════════════════════════════════════════════════════════════════════════
# PROJECTS & TASKS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_projects(limit: int = 20) -> str:
    """List active projects."""
    try:
        projects = _x("project.project", "search_read", [[["active", "=", True]]], {
            "fields": ["name", "user_id", "partner_id", "date_start", "date", "task_count", "company_id"],
            "limit": limit})
        if not projects:
            return "No projects found."
        out = [f"📋 Projects ({len(projects)})\n"]
        for p in projects:
            out.append(
                f"[{p['id']}] {p['name']}\n"
                f"  Manager: {p['user_id'][1] if p.get('user_id') else '—'} | "
                f"Tasks: {p.get('task_count', 0)} | "
                f"Company: {p['company_id'][1] if p.get('company_id') else '—'}\n"
            )
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Project module may not be installed: {str(e)[:100]}"


@mcp.tool()
def list_tasks(project_name: str = "", assigned_to: str = "",
               stage: str = "", limit: int = 20) -> str:
    """List tasks, optionally filtered by project, assignee, or stage."""
    try:
        domain = [["active", "=", True]]
        if project_name: domain.append(["project_id.name", "ilike", project_name])
        if assigned_to:  domain.append(["user_ids.name", "ilike", assigned_to])
        if stage:        domain.append(["stage_id.name", "ilike", stage])
        tasks = _x("project.task", "search_read", [domain], {
            "fields": ["name", "project_id", "user_ids", "stage_id", "date_deadline", "priority"],
            "limit": limit})
        if not tasks:
            return "No tasks found."
        out = [f"✅ Tasks ({len(tasks)})\n"]
        for t in tasks:
            priority = "🔴" if t.get("priority") == "1" else "⚪"
            out.append(
                f"{priority} [{t['id']}] {t['name']}\n"
                f"  Project: {t['project_id'][1] if t.get('project_id') else '—'} | "
                f"Stage: {t['stage_id'][1] if t.get('stage_id') else '—'} | "
                f"Due: {t.get('date_deadline', '—')}\n"
            )
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Could not retrieve tasks: {str(e)[:100]}"


@mcp.tool()
def create_task(name: str, project_name: str, description: str = "",
                assigned_to_email: str = "", deadline: str = "",
                priority: str = "normal") -> str:
    """Create a new task in a project.
    priority: normal or high"""
    try:
        projects = _x("project.project", "search_read", [[["name", "ilike", project_name]]],
                      {"fields": ["id", "name"], "limit": 1})
        if not projects:
            return f"❌ Project '{project_name}' not found."
        vals: dict = {
            "name":        name,
            "project_id":  projects[0]["id"],
            "description": description,
            "priority":    "1" if priority.lower() == "high" else "0",
        }
        if deadline: vals["date_deadline"] = deadline
        if assigned_to_email:
            u = _x("res.users", "search_read", [[["login", "=", assigned_to_email]]], {"fields": ["id"], "limit": 1})
            if u: vals["user_ids"] = [(4, u[0]["id"])]
        tid = _x("project.task", "create", [vals])
        return f"✅ Task created | ID: {tid} | '{name}' in {projects[0]['name']}"
    except Exception as e:
        return f"❌ Could not create task: {str(e)[:100]}"


# ════════════════════════════════════════════════════════════════════════════
# WEBSITE
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_website_leads(limit: int = 20) -> str:
    """View leads that came through the website."""
    leads = _x("crm.lead", "search_read", [[
        ["active", "=", True],
        ["medium_id.name", "ilike", "website"],
    ]], {"fields": ["name", "partner_name", "email_from", "create_date", "source_id", "page_id"],
         "limit": limit, "order": "create_date desc"})
    if not leads:
        return "No website leads found."
    out = [f"🌐 Website Leads ({len(leads)})\n"]
    for lead in leads:
        out.append(
            f"[{lead['id']}] {lead['name']}\n"
            f"  Contact : {lead.get('partner_name', '—')} | {lead.get('email_from', '—')}\n"
            f"  Source  : {lead['source_id'][1] if lead.get('source_id') else '—'} | "
            f"Date: {lead.get('create_date', '—')[:10]}\n"
        )
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# SALES ORDERS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_sales_orders(status: str = "sale", partner_name: str = "",
                     date_from: str = "", date_to: str = "", limit: int = 20) -> str:
    """List sales orders.
    status: draft (quotation), sale (confirmed), done, cancel."""
    domain = [["state", "=", status]]
    if partner_name: domain.append(["partner_id.name", "ilike", partner_name])
    if date_from:    domain.append(["date_order", ">=", date_from])
    if date_to:      domain.append(["date_order", "<=", date_to])
    orders = _x("sale.order", "search_read", [domain], {
        "fields": ["name", "partner_id", "date_order", "amount_total", "state", "user_id"],
        "limit": limit, "order": "date_order desc"})
    if not orders:
        return f"No {status} sales orders found."
    total = sum(o.get("amount_total", 0) for o in orders)
    out = [f"🛒 Sales Orders — {status.upper()} ({len(orders)})\n"]
    for o in orders:
        out.append(
            f"  {o['name']:<16} {o['partner_id'][1] if o.get('partner_id') else '—':<30} "
            f"${o.get('amount_total', 0):>12,.2f} | {o.get('date_order', '—')[:10]}"
        )
    out.append(f"\n  Total: ${total:,.2f}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# SOCIAL MARKETING
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_social_accounts() -> str:
    """List all connected social media accounts in Odoo Social Marketing."""
    try:
        accounts = _x("social.account", "search_read", [[]], {
            "fields": ["name", "media_type", "audience", "followers", "company_id", "has_account_stats"]})
        if not accounts:
            return "No social media accounts connected."
        out = ["📱 Connected Social Accounts\n"]
        for a in accounts:
            out.append(
                f"[{a['id']}] {a['name']}  ({a.get('media_type', '—')})\n"
                f"  Followers: {a.get('followers', 0):,} | Audience: {a.get('audience', 0):,} | "
                f"Company: {a['company_id'][1] if a.get('company_id') else '—'}\n"
            )
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Social Marketing module error: {str(e)[:150]}"


@mcp.tool()
def list_social_campaigns(limit: int = 20) -> str:
    """List all Social Marketing campaigns."""
    try:
        campaigns = _x("social.campaign", "search_read", [[]], {
            "fields": ["name", "state", "tag_ids", "campaign_id", "post_ids"],
            "limit": limit})
        if not campaigns:
            return "No social campaigns found."
        out = [f"📣 Social Campaigns ({len(campaigns)})\n"]
        for c in campaigns:
            posts = len(c.get("post_ids", []))
            out.append(
                f"[{c['id']}] {c['name']}\n"
                f"  State: {c.get('state', '—')} | Posts: {posts}\n"
            )
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Could not retrieve campaigns: {str(e)[:150]}"


@mcp.tool()
def create_social_campaign(name: str, utm_campaign: str = "") -> str:
    """Create a new Social Marketing campaign.
    utm_campaign: link to an existing UTM campaign name for lead tracking."""
    try:
        vals: dict = {"name": name}
        if utm_campaign:
            utms = _x("utm.campaign", "search_read", [[["name", "ilike", utm_campaign]]], {"fields": ["id"], "limit": 1})
            if utms: vals["campaign_id"] = utms[0]["id"]
        cid = _x("social.campaign", "create", [vals])
        return f"✅ Social campaign created | ID: {cid} | '{name}'"
    except Exception as e:
        return f"❌ Could not create campaign: {str(e)[:150]}"


@mcp.tool()
def list_social_posts(campaign_name: str = "", state: str = "", limit: int = 20) -> str:
    """List social media posts.
    state: draft, scheduled, posting, posted, failed.
    campaign_name: filter by campaign."""
    try:
        domain = []
        if state: domain.append(["state", "=", state])
        if campaign_name: domain.append(["campaign_id.name", "ilike", campaign_name])
        posts = _x("social.post", "search_read", [domain], {
            "fields": ["message", "state", "account_ids", "campaign_id", "scheduled_date",
                       "post_id", "click_count", "reach"],
            "limit": limit, "order": "scheduled_date desc"})
        if not posts:
            return "No posts found."
        out = [f"📝 Social Posts ({len(posts)})\n"]
        for p in posts:
            accounts = len(p.get("account_ids", []))
            out.append(
                f"[{p['id']}] [{p.get('state', '—').upper()}] {p.get('message', '')[:80]}...\n"
                f"  Campaign: {p['campaign_id'][1] if p.get('campaign_id') else '—'} | "
                f"Accounts: {accounts} | Scheduled: {str(p.get('scheduled_date', '—'))[:16]}\n"
                f"  Clicks: {p.get('click_count', 0)} | Reach: {p.get('reach', 0)}\n"
            )
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Could not retrieve posts: {str(e)[:150]}"


@mcp.tool()
def create_social_post(message: str, account_names: str, campaign_name: str = "",
                       scheduled_date: str = "") -> str:
    """Create a social media post and optionally schedule it.
    account_names: comma-separated account names e.g. 'Psicomed Facebook,Psicomed Instagram'.
    scheduled_date: YYYY-MM-DD HH:MM:SS format, leave empty to post immediately."""
    try:
        # Find accounts
        account_ids = []
        for name in account_names.split(","):
            accounts = _x("social.account", "search_read", [[["name", "ilike", name.strip()]]], {"fields": ["id", "name"], "limit": 1})
            if accounts:
                account_ids.append(accounts[0]["id"])
        if not account_ids:
            return f"❌ No social accounts found matching '{account_names}'. Use list_social_accounts() to see available accounts."
        vals: dict = {
            "message":     message,
            "account_ids": [(6, 0, account_ids)],
        }
        if campaign_name:
            campaigns = _x("social.campaign", "search_read", [[["name", "ilike", campaign_name]]], {"fields": ["id"], "limit": 1})
            if campaigns: vals["campaign_id"] = campaigns[0]["id"]
        if scheduled_date:
            vals["scheduled_date"] = scheduled_date
        post_id = _x("social.post", "create", [vals])
        if scheduled_date:
            _x("social.post", "action_schedule", [[post_id]])
            return f"✅ Post created & scheduled | ID: {post_id} | Date: {scheduled_date}"
        else:
            _x("social.post", "action_post", [[post_id]])
            return f"✅ Post created & published | ID: {post_id}"
    except Exception as e:
        return f"❌ Could not create post: {str(e)[:150]}"


@mcp.tool()
def get_social_campaign_stats(campaign_name: str) -> str:
    """Get stats for a Social Marketing campaign: reach, clicks, leads, revenue."""
    try:
        campaigns = _x("social.campaign", "search_read", [[["name", "ilike", campaign_name]]], {
            "fields": ["name", "state", "post_ids", "campaign_id"], "limit": 1})
        if not campaigns:
            return f"❌ Campaign '{campaign_name}' not found."
        c = campaigns[0]
        posts = _x("social.post", "search_read", [[["campaign_id", "=", c["id"]]]], {
            "fields": ["message", "state", "click_count", "reach", "account_ids"]})
        total_reach  = sum(p.get("reach", 0) for p in posts)
        total_clicks = sum(p.get("click_count", 0) for p in posts)
        posted  = sum(1 for p in posts if p.get("state") == "posted")
        draft   = sum(1 for p in posts if p.get("state") == "draft")
        # Get linked UTM leads
        leads = 0
        if c.get("campaign_id"):
            leads = _x("crm.lead", "search_count", [[["campaign_id", "=", c["campaign_id"][0]], ["active", "=", True]]])
        out = [f"📊 Campaign Stats: {c['name']}\n{'─' * 44}"]
        out.append(f"  Posts     : {len(posts)} total ({posted} posted, {draft} draft)")
        out.append(f"  Reach     : {total_reach:,}")
        out.append(f"  Clicks    : {total_clicks:,}")
        out.append(f"  CTR       : {(total_clicks / total_reach * 100) if total_reach else 0:.2f}%")
        out.append(f"  CRM Leads : {leads}")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Could not get stats: {str(e)[:150]}"


@mcp.tool()
def delete_social_post(post_id: int) -> str:
    """Delete a draft social media post."""
    try:
        _x("social.post", "unlink", [[post_id]])
        return f"✅ Post {post_id} deleted."
    except Exception as e:
        return f"❌ Could not delete post: {str(e)[:150]}"


@mcp.tool()
def explore_social_ads_fields() -> str:
    """Explore what paid advertising fields are available in Odoo Social Marketing.
    Use this to understand what ad capabilities exist in this Odoo instance."""
    try:
        # Check social.post fields for boost/paid capabilities
        post_fields = _x("social.post", "fields_get", [], {"attributes": ["string", "type", "help"]})
        boost_fields = {k: v for k, v in post_fields.items()
                       if any(kw in k.lower() for kw in ["boost", "paid", "budget", "target", "spend", "audience", "ad_"])}

        out = ["🔍 Social Marketing Paid Ad Fields\n" + "─" * 50]
        if boost_fields:
            out.append("\nBOOST/AD fields on social.post:")
            for fname, finfo in boost_fields.items():
                out.append(f"  {fname} ({finfo.get('type', '—')}): {finfo.get('string', '—')}")
        else:
            out.append("\nNo boost/ad fields found on social.post")

        # Check for dedicated ad models
        for model in ["social.facebook.account", "social.post.boost",
                      "social.campaign.post", "social.ad"]:
            try:
                fields = _x(model, "fields_get", [], {"attributes": ["string"]})
                out.append(f"\n✅ Model '{model}' exists with {len(fields)} fields")
            except Exception:
                out.append(f"  ❌ Model '{model}' not found")

        return "\n".join(out)
    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"
