#!/usr/bin/env python3
"""
Mezake Odoo MCP Server
Claude <-> Odoo integration covering CRM, Accounting, Inventory, Contacts, WhatsApp, Dashboard
"""

import os
import xmlrpc.client
from mcp.server.fastmcp import FastMCP

# ── Config (set as Railway env vars) ──────────────────────────────────────────
ODOO_URL      = os.environ.get("ODOO_URL",      "https://mezake.odoo.com")
ODOO_DB       = os.environ.get("ODOO_DB",       "elytekrd-mezake-produccion-14592479")
ODOO_USER     = os.environ.get("ODOO_USER",     "")   # your login email
ODOO_API_KEY  = os.environ.get("ODOO_API_KEY",  "")   # your API key
PORT          = int(os.environ.get("PORT", 8000))

mcp = FastMCP("Mezake Odoo")

# ── Odoo connection helpers ────────────────────────────────────────────────────

def _connect():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
    if not uid:
        raise RuntimeError("Odoo authentication failed – check ODOO_USER and ODOO_API_KEY.")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models

def _x(model: str, method: str, args: list, kw: dict = None):
    uid, m = _connect()
    return m.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, args, kw or {})

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_dashboard() -> str:
    """Full business snapshot: CRM, Accounting, Inventory, and Contacts at a glance."""
    active_leads     = _x("crm.lead",       "search_count", [[["active","=",True]]])
    won_leads        = _x("crm.lead",       "search_count", [[["stage_id.is_won","=",True],["active","=",True]]])
    open_invoices    = _x("account.move",   "search_count", [[["move_type","=","out_invoice"],["payment_state","=","not_paid"],["state","=","posted"]]])
    overdue_invoices = _x("account.move",   "search_count", [[["move_type","=","out_invoice"],["payment_state","=","not_paid"],["state","=","posted"],["invoice_date_due","<", _today()]]])
    low_stock        = _x("product.product","search_count", [[["type","=","product"],["qty_available","<=",5]]])
    total_contacts   = _x("res.partner",    "search_count", [[["active","=",True],["is_company","=",False]]])
    total_companies  = _x("res.partner",    "search_count", [[["active","=",True],["is_company","=",True]]])

    return f"""📊  MEZAKE — Business Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯  CRM
    Active Leads / Opportunities : {active_leads}
    Won Deals                    : {won_leads}

💰  Accounting
    Open (unpaid) Invoices       : {open_invoices}
    Overdue Invoices             : {overdue_invoices}  ⚠️

📦  Inventory
    Products with Low Stock (≤5) : {low_stock}

👥  Contacts
    Individual Contacts          : {total_contacts}
    Companies                    : {total_companies}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ask me to drill into any area!"""

def _today():
    from datetime import date
    return date.today().isoformat()

# ══════════════════════════════════════════════════════════════════════════════
# CRM
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_pipeline_summary() -> str:
    """CRM pipeline value and lead count broken down by stage."""
    stages = _x("crm.stage", "search_read", [[]], {"fields": ["id","name","sequence"], "order": "sequence"})
    lines = []
    total = 0
    for s in stages:
        leads = _x("crm.lead", "search_read",
            [[["stage_id","=",s["id"]],["active","=",True]]],
            {"fields":["expected_revenue"]})
        rev = sum(l.get("expected_revenue",0) for l in leads)
        total += rev
        lines.append(f"  {s['name']:<25} {len(leads):>4} leads   ${rev:>12,.2f}")
    body = "\n".join(lines)
    return f"🎯  CRM Pipeline\n{'─'*55}\n{body}\n{'─'*55}\n  {'TOTAL':<25} {'':>4}        ${total:>12,.2f}"

@mcp.tool()
def search_leads(query: str = "", stage: str = "", assigned_to: str = "", limit: int = 20) -> str:
    """Search CRM leads. Filter by name/query, stage name, or assigned user."""
    domain: list = [["active","=",True]]
    if query:       domain.append(["name","ilike",query])
    if stage:       domain.append(["stage_id.name","ilike",stage])
    if assigned_to: domain.append(["user_id.name","ilike",assigned_to])

    leads = _x("crm.lead","search_read",[domain],{
        "fields":["name","partner_name","email_from","phone","stage_id",
                  "expected_revenue","probability","user_id","create_date","source_id"],
        "limit": limit, "order": "create_date desc"})

    if not leads:
        return "No leads found matching your criteria."

    out = [f"Found {len(leads)} lead(s):\n"]
    for l in leads:
        out.append(
            f"[{l['id']}] {l['name']}\n"
            f"  Contact : {l.get('partner_name','—')}  |  {l.get('email_from','—')}  |  {l.get('phone','—')}\n"
            f"  Stage   : {l['stage_id'][1] if l.get('stage_id') else '—'}"
            f"  |  Revenue: ${l.get('expected_revenue',0):,.2f}"
            f"  |  Prob: {l.get('probability',0):.0f}%\n"
            f"  Owner   : {l['user_id'][1] if l.get('user_id') else 'Unassigned'}"
            f"  |  Source: {l['source_id'][1] if l.get('source_id') else '—'}\n"
        )
    return "\n".join(out)

@mcp.tool()
def create_lead(
    name: str,
    partner_name: str,
    email: str = "",
    phone: str = "",
    expected_revenue: float = 0.0,
    stage: str = "",
    source: str = "",
    notes: str = ""
) -> str:
    """Create a new CRM lead / opportunity."""
    vals: dict = {
        "name": name,
        "partner_name": partner_name,
        "email_from": email,
        "phone": phone,
        "expected_revenue": expected_revenue,
        "description": notes,
    }
    if stage:
        s = _x("crm.stage","search_read",[[["name","ilike",stage]]],{"fields":["id","name"],"limit":1})
        if s: vals["stage_id"] = s[0]["id"]
    if source:
        src = _x("utm.source","search_read",[[["name","ilike",source]]],{"fields":["id"],"limit":1})
        if src: vals["source_id"] = src[0]["id"]

    lead_id = _x("crm.lead","create",[vals])
    return f"✅  Lead created  |  ID: {lead_id}  |  '{name}'  →  {partner_name}"

@mcp.tool()
def update_lead(
    lead_id: int,
    stage: str = "",
    expected_revenue: float = None,
    probability: float = None,
    notes: str = "",
    assign_to_email: str = ""
) -> str:
    """Update an existing lead: move stage, change revenue, add notes, reassign."""
    vals: dict = {}
    if stage:
        s = _x("crm.stage","search_read",[[["name","ilike",stage]]],{"fields":["id","name"],"limit":1})
        if not s: return f"❌  Stage '{stage}' not found."
        vals["stage_id"] = s[0]["id"]
    if expected_revenue is not None: vals["expected_revenue"] = expected_revenue
    if probability is not None:      vals["probability"]       = probability
    if notes:                        vals["description"]       = notes
    if assign_to_email:
        u = _x("res.users","search_read",[[["login","=",assign_to_email]]],{"fields":["id"],"limit":1})
        if not u: return f"❌  User '{assign_to_email}' not found."
        vals["user_id"] = u[0]["id"]

    if not vals:
        return "Nothing to update – please provide at least one field."
    _x("crm.lead","write",[[lead_id], vals])
    return f"✅  Lead {lead_id} updated: {', '.join(vals.keys())}"

@mcp.tool()
def log_lead_activity(lead_id: int, note: str, activity_type: str = "note") -> str:
    """Log a note or activity on a CRM lead."""
    _x("crm.lead","message_post",[[lead_id]],{"body": note, "message_type": "comment"})
    return f"✅  Note logged on lead {lead_id}."

# ══════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_contacts(query: str, is_company: bool = False, limit: int = 15) -> str:
    """Search contacts or companies by name, email, or phone."""
    domain = [
        ["active","=",True],
        ["is_company","=",is_company],
        "|","|",
        ["name","ilike",query],
        ["email","ilike",query],
        ["phone","ilike",query],
    ]
    contacts = _x("res.partner","search_read",[domain],{
        "fields":["name","email","phone","mobile","company_name","street","city","country_id","is_company"],
        "limit": limit})

    if not contacts:
        return "No contacts found."

    out = [f"Found {len(contacts)} contact(s):\n"]
    for c in contacts:
        out.append(
            f"[{c['id']}] {c['name']}"
            f"{'  🏢 Company' if c.get('is_company') else ''}\n"
            f"  Email: {c.get('email','—')}  |  Phone: {c.get('phone') or c.get('mobile','—')}\n"
            f"  Location: {c.get('city','—')}, {c['country_id'][1] if c.get('country_id') else '—'}\n"
        )
    return "\n".join(out)

@mcp.tool()
def create_contact(
    name: str,
    email: str = "",
    phone: str = "",
    mobile: str = "",
    company_name: str = "",
    is_company: bool = False,
    street: str = "",
    city: str = "",
) -> str:
    """Create a new contact or company in Odoo."""
    vals: dict = {
        "name": name, "email": email, "phone": phone,
        "mobile": mobile, "is_company": is_company,
        "street": street, "city": city,
    }
    if company_name and not is_company:
        co = _x("res.partner","search_read",[[["name","ilike",company_name],["is_company","=",True]]],{"fields":["id"],"limit":1})
        if co: vals["parent_id"] = co[0]["id"]
    contact_id = _x("res.partner","create",[vals])
    return f"✅  Contact created  |  ID: {contact_id}  |  {name}"

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNTING
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_accounting_summary() -> str:
    """High-level accounting overview: receivables, payables, overdue amounts."""
    def _sum(domain):
        rows = _x("account.move.line","read_group",[domain],["balance"],[])
        return abs(rows[0].get("balance",0)) if rows else 0

    ar  = _sum([["account_id.account_type","=","asset_receivable"],     ["reconciled","=",False],["parent_state","=","posted"]])
    ap  = _sum([["account_id.account_type","=","liability_payable"],    ["reconciled","=",False],["parent_state","=","posted"]])

    overdue = _x("account.move","search_read",[
        [["move_type","=","out_invoice"],["payment_state","=","not_paid"],
         ["state","=","posted"],["invoice_date_due","<",_today()]]],
        {"fields":["amount_residual"]})
    overdue_total = sum(i.get("amount_residual",0) for i in overdue)

    return f"""💰  Accounting Summary
─────────────────────────────────────
  Accounts Receivable (owed to you) : ${ar:>12,.2f}
  Accounts Payable   (you owe)      : ${ap:>12,.2f}
  Net Position                      : ${ar-ap:>12,.2f}
  Overdue from customers            : ${overdue_total:>12,.2f}  ⚠️"""

@mcp.tool()
def get_invoices(status: str = "open", partner_name: str = "", limit: int = 20) -> str:
    """
    List customer invoices.
    status: 'open' (unpaid), 'paid', 'draft', 'overdue', 'all'
    """
    domain: list = [["move_type","=","out_invoice"]]
    if status == "open":
        domain += [["payment_state","=","not_paid"],["state","=","posted"]]
    elif status == "paid":
        domain += [["payment_state","=","paid"]]
    elif status == "draft":
        domain += [["state","=","draft"]]
    elif status == "overdue":
        domain += [["payment_state","=","not_paid"],["state","=","posted"],["invoice_date_due","<",_today()]]
    if partner_name:
        domain.append(["partner_id.name","ilike",partner_name])

    invoices = _x("account.move","search_read",[domain],{
        "fields":["name","partner_id","invoice_date","invoice_date_due",
                  "amount_total","amount_residual","payment_state","state"],
        "limit": limit, "order": "invoice_date_due asc"})

    if not invoices:
        return f"No {status} invoices found."

    total_residual = sum(i.get("amount_residual",0) for i in invoices)
    out = [f"📄  {status.upper()} Invoices ({len(invoices)} found)\n"]
    for i in invoices:
        out.append(
            f"  {i['name']:<20} {i['partner_id'][1] if i.get('partner_id') else '—':<30}\n"
            f"  Total: ${i.get('amount_total',0):>10,.2f}  |"
            f"  Due: ${i.get('amount_residual',0):>10,.2f}  |"
            f"  Due Date: {i.get('invoice_date_due','—')}\n"
        )
    out.append(f"\n  Total Outstanding: ${total_residual:,.2f}")
    return "\n".join(out)

@mcp.tool()
def create_invoice(
    partner_name: str,
    product_name: str,
    quantity: float,
    unit_price: float,
    notes: str = ""
) -> str:
    """Create a draft customer invoice for a partner and product."""
    partners = _x("res.partner","search_read",[[["name","ilike",partner_name]]],{"fields":["id","name"],"limit":1})
    if not partners: return f"❌  Partner '{partner_name}' not found."
    partner_id = partners[0]["id"]

    products = _x("product.product","search_read",[[["name","ilike",product_name]]],{"fields":["id","name","list_price"],"limit":1})
    if not products: return f"❌  Product '{product_name}' not found."
    product = products[0]

    inv_id = _x("account.move","create",[{
        "move_type": "out_invoice",
        "partner_id": partner_id,
        "narration": notes,
        "invoice_line_ids": [(0, 0, {
            "product_id": product["id"],
            "quantity": quantity,
            "price_unit": unit_price or product.get("list_price",0),
        })]
    }])
    total = quantity * (unit_price or product.get("list_price",0))
    return f"✅  Draft invoice created  |  ID: {inv_id}  |  {partners[0]['name']}  |  Total: ${total:,.2f}"

# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_products(query: str = "", category: str = "", limit: int = 20) -> str:
    """Search products with stock levels and pricing."""
    domain: list = [["type","in",["product","consu"]]]
    if query:    domain.append(["name","ilike",query])
    if category: domain.append(["categ_id.name","ilike",category])

    products = _x("product.product","search_read",[domain],{
        "fields":["name","default_code","qty_available","virtual_available",
                  "list_price","standard_price","categ_id","uom_id"],
        "limit": limit})

    if not products:
        return "No products found."

    out = [f"📦  Products ({len(products)} found)\n"]
    for p in products:
        stock_icon = "🔴" if p.get("qty_available",0) <= 5 else "🟢"
        out.append(
            f"{stock_icon} [{p.get('default_code','—')}] {p['name']}\n"
            f"   In Stock: {p.get('qty_available',0):.0f}  |"
            f"  Forecasted: {p.get('virtual_available',0):.0f}  |"
            f"  Sale: ${p.get('list_price',0):,.2f}  |"
            f"  Cost: ${p.get('standard_price',0):,.2f}\n"
        )
    return "\n".join(out)

@mcp.tool()
def get_low_stock_alert(threshold: int = 10) -> str:
    """List all products at or below a stock threshold (default 10 units)."""
    products = _x("product.product","search_read",
        [[["type","=","product"],["qty_available","<=",threshold]]],
        {"fields":["name","default_code","qty_available","virtual_available"],"limit":100})

    if not products:
        return f"✅  All products are above {threshold} units."

    out = [f"⚠️  LOW STOCK ALERT — {len(products)} product(s) at or below {threshold} units:\n"]
    for p in sorted(products, key=lambda x: x.get("qty_available",0)):
        out.append(f"  [{p.get('default_code','—')}] {p['name']:<40}  Stock: {p.get('qty_available',0):.0f}")
    return "\n".join(out)

@mcp.tool()
def get_stock_moves(product_query: str = "", limit: int = 20) -> str:
    """Get recent inventory movements for a product."""
    domain: list = [["state","=","done"]]
    if product_query:
        domain.append(["product_id.name","ilike",product_query])

    moves = _x("stock.move","search_read",[domain],{
        "fields":["name","product_id","product_uom_qty","location_id","location_dest_id","date"],
        "limit": limit, "order": "date desc"})

    if not moves:
        return "No stock movements found."

    out = [f"📋  Recent Stock Movements ({len(moves)})\n"]
    for m in moves:
        out.append(
            f"  {m.get('date','')[:10]}  {m['product_id'][1]:<35}"
            f"  Qty: {m.get('product_uom_qty',0):>8.2f}"
            f"  {m['location_id'][1]} → {m['location_dest_id'][1]}\n"
        )
    return "\n".join(out)

# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_whatsapp_messages(partner_name: str = "", limit: int = 20) -> str:
    """Read recent WhatsApp conversations in Odoo."""
    domain: list = [["message_type","=","whatsapp_message"]]
    if partner_name:
        domain.append(["author_id.name","ilike",partner_name])

    msgs = _x("mail.message","search_read",[domain],{
        "fields":["date","author_id","body","res_id","model"],
        "limit": limit, "order": "date desc"})

    if not msgs:
        return "No WhatsApp messages found."

    out = [f"💬  WhatsApp Messages ({len(msgs)})\n"]
    for m in msgs:
        import re
        clean_body = re.sub(r"<[^>]+>", "", m.get("body","")).strip()
        out.append(
            f"  {m.get('date','')[:16]}  {m['author_id'][1] if m.get('author_id') else '—':<30}\n"
            f"  {clean_body[:120]}\n"
        )
    return "\n".join(out)

@mcp.tool()
def send_whatsapp_message(partner_name: str, message: str) -> str:
    """Send a WhatsApp message to a contact via Odoo."""
    partners = _x("res.partner","search_read",
        [[["name","ilike",partner_name]]],
        {"fields":["id","name","mobile","phone"],"limit":1})
    if not partners: return f"❌  Contact '{partner_name}' not found."
    partner = partners[0]
    phone = partner.get("mobile") or partner.get("phone")
    if not phone: return f"❌  No phone/mobile number found for '{partner['name']}'."

    # Post a WhatsApp message via Odoo's discuss channel or mail.compose
    _x("res.partner","message_post",[[partner["id"]]],{
        "body": message,
        "message_type": "whatsapp_message",
    })
    return f"✅  WhatsApp message sent to {partner['name']} ({phone})"

# ══════════════════════════════════════════════════════════════════════════════
# SALES ORDERS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_sales_orders(status: str = "sale", partner_name: str = "", limit: int = 20) -> str:
    """
    List sales orders.
    status: 'draft' (quotation), 'sale' (confirmed), 'done', 'cancel'
    """
    domain: list = [["state","=",status]]
    if partner_name: domain.append(["partner_id.name","ilike",partner_name])

    orders = _x("sale.order","search_read",[domain],{
        "fields":["name","partner_id","date_order","amount_total","state","user_id"],
        "limit": limit, "order": "date_order desc"})

    if not orders:
        return f"No {status} sales orders found."

    total = sum(o.get("amount_total",0) for o in orders)
    out = [f"🛒  Sales Orders — {status.upper()} ({len(orders)} found)\n"]
    for o in orders:
        out.append(
            f"  {o['name']}  |  {o['partner_id'][1] if o.get('partner_id') else '—':<30}"
            f"  ${o.get('amount_total',0):>12,.2f}  |  {o.get('date_order','')[:10]}\n"
        )
    out.append(f"\n  Total: ${total:,.2f}")
    return "\n".join(out)

# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🚀  Mezake Odoo MCP Server starting on port {PORT}")
    mcp.run(transport="sse", host="0.0.0.0", port=PORT)
