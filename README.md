# DataImpulse Reseller Admin Panel

A private, self-hosted admin panel for managing your DataImpulse Reseller API.
Built with **FastAPI** + **Jinja2** + pure CSS (no frontend build step).

---

## Quick Start

```bash
# 1. Clone / copy the panel directory
cd dataimpulse-panel

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the panel
uvicorn main:app --reload --port 8000

# 5. Open in browser
open http://localhost:8000
```

---

## First-Time Setup

1. Go to **Settings** (`/settings`)
2. Enter your DataImpulse API **Login** and **Password**
   (found in your DataImpulse dashboard → API Management)
3. Confirm the **Base URL** is `https://proxy.bbproject.my.id`
4. Click **Save Credentials**
5. Click **Authenticate & Refresh Token** — the JWT will be stored locally
6. Navigate to **Dashboard** to verify balance is loading

---

## Architecture

```
dataimpulse-panel/
├── main.py          # FastAPI app — all routes & page controllers
├── api_client.py    # Async HTTP client — all 29 DataImpulse endpoints
├── database.py      # SQLite persistence (config + audit log)
├── requirements.txt
├── panel.db         # Auto-created SQLite DB (gitignore this!)
├── panel.log        # Rolling log file
└── templates/
    ├── base.html           # Layout, sidebar, global CSS
    ├── dashboard.html      # Overview + stats + recent activity
    ├── sub_users.html      # Sub-user list, create, block, delete
    ├── sub_user_detail.html # Full detail: balance, IPs, protocols, usage
    ├── locations.html      # Residential/datacenter country lookup
    └── logs.html           # Filterable audit log viewer
```

---

## API Endpoints Covered

| Category         | Endpoint                                    | Method |
|-----------------|---------------------------------------------|--------|
| **Auth**        | user/token/get                              | POST   |
| **User**        | user/balance                                | GET    |
| **Sub-Users**   | sub-user/list                               | GET    |
|                 | sub-user/get                                | GET    |
|                 | sub-user/create                             | POST   |
|                 | sub-user/update                             | POST   |
|                 | sub-user/delete                             | POST   |
|                 | sub-user/reset-password                     | POST   |
|                 | sub-user/set-blocked                        | POST   |
|                 | sub-user/set-blocked-hosts                  | POST   |
|                 | sub-user/set-default-pool-parameters        | POST   |
| **IPs**         | sub-user/allowed-ips/add                    | POST   |
|                 | sub-user/allowed-ips/remove                 | POST   |
| **Balance**     | sub-user/balance/get                        | GET    |
|                 | sub-user/balance/add                        | POST   |
|                 | sub-user/balance/drop                       | POST   |
|                 | sub-user/balance/addition-history           | GET    |
| **Usage**       | sub-user/usage-stat/get                     | GET    |
|                 | sub-user/usage-stat/detail                  | GET    |
|                 | sub-user/usage-stat/errors                  | GET    |
| **Protocols**   | sub-user/supported-protocols/get            | GET    |
|                 | sub-user/supported-protocols/set            | POST   |
| **Locations**   | common/locations                            | GET    |
|                 | common/pool_stats                           | GET    |
|                 | common/locations/countries                  | POST   |
|                 | common/locations/states                     | POST   |
|                 | common/locations/cities                     | POST   |
|                 | common/locations/zipcodes                   | POST   |
|                 | common/locations/asns                       | POST   |

---

## Database Schema

```sql
-- Stored in panel.db (SQLite, local file)

CREATE TABLE config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
-- Keys: login, password, token, token_expires, base_url

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT,       -- ISO UTC timestamp
    level       TEXT,       -- INFO / WARN / ERROR
    endpoint    TEXT,       -- API path called
    method      TEXT,       -- HTTP method
    status      INTEGER,    -- Response HTTP status
    duration_ms INTEGER,    -- Round-trip time
    detail      TEXT        -- Error message if applicable
);
```

> ⚠️ **Security**: `panel.db` contains your API credentials in plaintext.
> Keep it restricted to your user account (`chmod 600 panel.db`).
> Never commit it to git (it is in `.gitignore`).

---

## Security Notes

- This is a **single-user private panel** — no login wall is included by design
- To add basic auth, wrap with nginx + htpasswd or add FastAPI HTTP Basic Auth
- Token TTL is 24 hours; the panel detects 401 responses and surfaces a re-auth prompt
- All API requests are logged to `audit_log` and viewable at `/logs`

---

## Running as a Service (systemd)

```ini
[Unit]
Description=DataImpulse Admin Panel
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/dataimpulse-panel
ExecStart=/path/to/dataimpulse-panel/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now di-panel
```
