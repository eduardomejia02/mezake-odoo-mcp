# Mezake Odoo MCP Server

Claude ↔ Odoo integration. Gives Claude full access to your Odoo instance.

## What Claude can do via this MCP

| Module | Actions |
|---|---|
| Dashboard | Full business snapshot |
| CRM | Search/create/update leads, pipeline summary, log activities |
| Contacts | Search, create contacts & companies |
| Accounting | Invoices (list/create), payments, AR/AP summary |
| Inventory | Products, stock levels, low-stock alerts, movements |
| WhatsApp | Read conversations, send messages |
| Sales | List and track sales orders |

## Deploy to Railway (10 minutes)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Mezake Odoo MCP"
git remote add origin https://github.com/YOUR_USERNAME/mezake-odoo-mcp.git
git push -u origin main
```

### 2. Create Railway Project
1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project → Deploy from GitHub repo**
3. Select your `mezake-odoo-mcp` repo

### 3. Set Environment Variables
In Railway → your service → **Variables**, add:

| Variable | Value |
|---|---|
| `ODOO_URL` | `https://mezake.odoo.com` |
| `ODOO_DB` | `elytekrd-mezake-produccion-14592479` |
| `ODOO_USER` | your Odoo login email |
| `ODOO_API_KEY` | your Odoo API key |

### 4. Get your public URL
Railway → your service → **Settings → Networking → Generate Domain**
Your MCP URL will be: `https://your-app.up.railway.app/sse`

### 5. Connect to Claude.ai
1. Go to Claude.ai → Settings → Integrations
2. Add MCP server: `https://your-app.up.railway.app/sse`
3. Done — Claude now has full Odoo access!

## Security
- Never commit your API key to Git — always use Railway environment variables
- Regenerate your Odoo API key after initial setup (Settings → Technical → API Keys)
