"""
DataImpulse Reseller Admin Panel — FastAPI Backend
Run:  uvicorn main:app --reload --port 8000
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from database import Database
from api_client import DataImpulseClient, APIError

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("panel.log"),
    ],
)
log = logging.getLogger("di-panel")

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="DataImpulse Admin Panel", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory="templates")
db = Database()


def get_client() -> DataImpulseClient:
    cfg = db.get_config()
    return DataImpulseClient(
        base_url=cfg.get("base_url", "https://proxy.bbproject.myd.id"),
        token=cfg.get("token"),
        db=db,
    )


# ── Helper ───────────────────────────────────────────────────────────────────
def flash_ctx(request: Request, extra: dict = None) -> dict:
    cfg = db.get_config()
    ctx = {
        "request": request,
        "token_set": bool(cfg.get("token")),
        "login_set": bool(cfg.get("login")),
        "base_url": cfg.get("base_url", "https://proxy.bbproject.myd.id"),
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    if extra:
        ctx.update(extra)
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    client = get_client()
    balance = None
    sub_count = None
    recent_logs = db.get_logs(limit=8)
    error = None

    try:
        balance = await client.get_balance()
        subs = await client.list_sub_users(limit=1, offset=0)
        sub_count = subs.get("total", "?")
    except APIError as e:
        error = str(e)
        log.warning("Dashboard fetch failed: %s", e)

    return templates.TemplateResponse(
        "dashboard.html",
        flash_ctx(request, {
            "balance": balance,
            "sub_count": sub_count,
            "recent_logs": recent_logs,
            "error": error,
        }),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    cfg = db.get_config()
    return templates.TemplateResponse("settings.html", flash_ctx(request, {"cfg": cfg}))


@app.post("/settings/save")
async def settings_save(
    login: str = Form(...),
    password: str = Form(...),
    base_url: str = Form("https://proxy.bbproject.myd.id"),
):
    db.set_config("login", login)
    db.set_config("password", password)
    db.set_config("base_url", base_url.rstrip("/"))
    db.set_config("token", "")        # force re-auth
    db.set_config("token_expires", "")
    log.info("Settings saved — credentials updated")
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/auth")
async def settings_auth():
    cfg = db.get_config()
    client = DataImpulseClient(base_url=cfg.get("base_url"), db=db)
    try:
        token = await client.get_token(cfg["login"], cfg["password"])
        log.info("Token obtained successfully")
        return JSONResponse({"ok": True, "token_preview": token[:20] + "…"})
    except APIError as e:
        log.error("Auth failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ══════════════════════════════════════════════════════════════════════════════
#  SUB-USERS
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/sub-users", response_class=HTMLResponse)
async def sub_users_page(request: Request, limit: int = 50, offset: int = 0):
    client = get_client()
    data = {}
    error = None
    try:
        data = await client.list_sub_users(limit=limit, offset=offset)
    except APIError as e:
        error = str(e)
        log.warning("Sub-user list failed: %s", e)
    return templates.TemplateResponse(
        "sub_users.html",
        flash_ctx(request, {"data": data, "error": error, "limit": limit, "offset": offset}),
    )


@app.get("/sub-users/{subuser_id}", response_class=HTMLResponse)
async def sub_user_detail(request: Request, subuser_id: int):
    client = get_client()
    error = None
    user = balance = usage = protocols = allowed_ips = None
    try:
        user = await client.get_sub_user(subuser_id)
        balance = await client.get_sub_user_balance(subuser_id)
        usage = await client.get_sub_user_usage(subuser_id, "month")
        protocols = await client.get_sub_user_protocols(subuser_id)
    except APIError as e:
        error = str(e)
        log.warning("Sub-user detail failed for %s: %s", subuser_id, e)
    return templates.TemplateResponse(
        "sub_user_detail.html",
        flash_ctx(request, {
            "user": user, "balance": balance, "usage": usage,
            "protocols": protocols, "subuser_id": subuser_id, "error": error,
        }),
    )


# ── Sub-user API actions (JSON endpoints called by JS) ────────────────────────
@app.post("/api/sub-users/create")
async def api_create_sub_user(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.create_sub_user(**body)
        log.info("Created sub-user: %s", body.get("login"))
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/update")
async def api_update_sub_user(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.update_sub_user(**body)
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/delete")
async def api_delete_sub_user(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.delete_sub_user(body["subuser_id"])
        log.warning("Deleted sub-user: %s", body["subuser_id"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/set-blocked")
async def api_set_blocked(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.set_blocked(body["subuser_id"], body["blocked"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/reset-password")
async def api_reset_password(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.reset_password(body["subuser_id"], body["password"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Balance management ────────────────────────────────────────────────────────
@app.post("/api/sub-users/balance/add")
async def api_balance_add(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.add_sub_user_balance(body["subuser_id"], body["amount"])
        log.info("Added %.2f GB to sub-user %s", body["amount"], body["subuser_id"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/balance/drop")
async def api_balance_drop(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.drop_sub_user_balance(body["subuser_id"])
        log.warning("Dropped balance for sub-user %s", body["subuser_id"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/sub-users/{subuser_id}/balance/history")
async def api_balance_history(subuser_id: int):
    client = get_client()
    try:
        return JSONResponse(await client.get_balance_history(subuser_id))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/sub-users/{subuser_id}/usage")
async def api_usage(subuser_id: int, period: str = "month"):
    client = get_client()
    try:
        return JSONResponse(await client.get_sub_user_usage(subuser_id, period))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/sub-users/{subuser_id}/usage/errors")
async def api_usage_errors(subuser_id: int, period: str = "month"):
    client = get_client()
    try:
        return JSONResponse(await client.get_sub_user_errors(subuser_id, period))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Allowed IPs ───────────────────────────────────────────────────────────────
@app.post("/api/sub-users/allowed-ips/add")
async def api_ip_add(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.add_allowed_ip(body["subuser_id"], body["ip"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/sub-users/allowed-ips/remove")
async def api_ip_remove(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.remove_allowed_ip(body["subuser_id"], body["ip"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Protocols ─────────────────────────────────────────────────────────────────
@app.post("/api/sub-users/protocols/set")
async def api_protocols_set(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.set_sub_user_protocols(body["subuser_id"], body["protocols"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Set blocked hosts ─────────────────────────────────────────────────────────
@app.post("/api/sub-users/blocked-hosts")
async def api_blocked_hosts(request: Request):
    body = await request.json()
    client = get_client()
    try:
        result = await client.set_blocked_hosts(body["subuser_id"], body["hosts"])
        return JSONResponse(result)
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ══════════════════════════════════════════════════════════════════════════════
#  LOCATIONS
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/locations", response_class=HTMLResponse)
async def locations_page(request: Request):
    client = get_client()
    error = None
    residential = datacenter = None
    try:
        residential = await client.get_locations("residential")
        datacenter = await client.get_locations("datacenter")
    except APIError as e:
        error = str(e)
        log.warning("Locations fetch failed: %s", e)
    return templates.TemplateResponse(
        "locations.html",
        flash_ctx(request, {
            "residential": residential,
            "datacenter": datacenter,
            "error": error,
        }),
    )


@app.post("/api/locations/countries")
async def api_countries(request: Request):
    body = await request.json()
    client = get_client()
    try:
        return JSONResponse(await client.get_countries(body.get("pool_type", "residential")))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/locations/states")
async def api_states(request: Request):
    body = await request.json()
    client = get_client()
    try:
        return JSONResponse(await client.get_states(body["country_code"], body.get("pool_type", "residential")))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/locations/cities")
async def api_cities(request: Request):
    body = await request.json()
    client = get_client()
    try:
        return JSONResponse(await client.get_cities(body["country_code"], body.get("state_code"), body.get("pool_type", "residential")))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/pool-stats")
async def api_pool_stats(pool_type: str = "residential"):
    client = get_client()
    try:
        return JSONResponse(await client.get_pool_stats(pool_type))
    except APIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGS
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, limit: int = 100):
    logs_data = db.get_logs(limit=limit)
    return templates.TemplateResponse(
        "logs.html",
        flash_ctx(request, {"logs": logs_data, "limit": limit}),
    )


@app.get("/api/logs")
async def api_logs(limit: int = 50):
    return JSONResponse(db.get_logs(limit=limit))
