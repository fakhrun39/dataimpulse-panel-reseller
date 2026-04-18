"""
api_client.py — Async HTTP client for the DataImpulse Reseller API.

All requests are routed through the configurable base_url.
Token refresh is handled automatically when the stored token is missing or expired.
"""

import time
import logging
import httpx
from typing import Optional
from datetime import datetime, timezone

log = logging.getLogger("di-panel.api")

# DataImpulse upstream — used ONLY for token acquisition (form-data endpoint)
_DI_AUTH_URL = "https://api.dataimpulse.com/reseller/user/token/get"
_API_PREFIX = "/reseller"


class APIError(Exception):
    """Raised for non-2xx responses or network failures."""
    def __init__(self, message: str, status: int = None):
        super().__init__(message)
        self.status = status


class DataImpulseClient:
    def __init__(self, base_url: str, db, token: str = None):
        self.base_url = (base_url or "https://proxy.bbproject.myd.id").rstrip("/")
        self.db = db
        self._token = token or ""

    # ── Auth ──────────────────────────────────────────────────────────────────
    async def get_token(self, login: str, password: str) -> str:
        """Fetch a fresh JWT from DataImpulse and persist it."""
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    _DI_AUTH_URL,
                    data={"login": login, "password": password},
                )
            except httpx.RequestError as e:
                self.db.log_request("user/token/get", "POST", detail=str(e), level="ERROR")
                raise APIError(f"Network error during auth: {e}")

        ms = int((time.monotonic() - start) * 1000)
        self.db.log_request("user/token/get", "POST", status=resp.status_code, duration_ms=ms)

        if resp.status_code != 200:
            raise APIError(f"Auth failed [{resp.status_code}]: {resp.text}", resp.status_code)

        token = resp.json().get("token", "")
        self._token = token
        self.db.set_config("token", token)
        # JWT TTL is 24 h; store expiry epoch
        import base64, json as _json
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            exp = _json.loads(base64.b64decode(payload))["exp"]
            self.db.set_config("token_expires", str(exp))
        except Exception:
            pass
        log.info("Token refreshed, expires ~24h")
        return token

    def _ensure_token(self):
        """Raise if no token is loaded."""
        if not self._token:
            cfg = self.db.get_config()
            self._token = cfg.get("token", "")
        if not self._token:
            raise APIError(
                "No API token found. Go to Settings → Authenticate first.",
                401,
            )

    def _headers(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._token}"}

    # ── Core request helper ───────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict = None,
        json: dict = None,
    ) -> dict:
        url = f"{self.base_url}{_API_PREFIX}{path}"
        start = time.monotonic()
        log.debug("%s %s", method, url)
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
            except httpx.RequestError as e:
                ms = int((time.monotonic() - start) * 1000)
                self.db.log_request(path, method, detail=str(e), level="ERROR", duration_ms=ms)
                log.error("Request error %s %s — %s", method, url, e)
                raise APIError(f"Network error: {e}")

        ms = int((time.monotonic() - start) * 1000)
        level = "INFO" if resp.status_code < 400 else "WARN" if resp.status_code < 500 else "ERROR"
        self.db.log_request(path, method, status=resp.status_code, duration_ms=ms, level=level)
        log.info("%s %s → %s (%dms)", method, path, resp.status_code, ms)

        if resp.status_code == 401:
            raise APIError("Token expired or invalid — re-authenticate in Settings.", 401)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            raise APIError(f"[{resp.status_code}] {detail}", resp.status_code)

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    # ══════════════════════════════════════════════════════════════════════════
    #  USER endpoints
    # ══════════════════════════════════════════════════════════════════════════
    async def get_balance(self) -> dict:
        return await self._request("GET", "/user/balance")

    # ══════════════════════════════════════════════════════════════════════════
    #  SUB-USER endpoints
    # ══════════════════════════════════════════════════════════════════════════
    async def list_sub_users(self, limit: int = 100, offset: int = 0) -> dict:
        return await self._request("GET", "/sub-user/list", params={"limit": limit, "offset": offset})

    async def get_sub_user(self, subuser_id: int) -> dict:
        return await self._request("GET", "/sub-user/get", params={"subuser_id": subuser_id})

    async def create_sub_user(self, login: str, password: str, **kwargs) -> dict:
        body = {"login": login, "password": password, **kwargs}
        return await self._request("POST", "/sub-user/create", json=body)

    async def update_sub_user(self, subuser_id: int, **kwargs) -> dict:
        body = {"subuser_id": subuser_id, **kwargs}
        return await self._request("POST", "/sub-user/update", json=body)

    async def delete_sub_user(self, subuser_id: int) -> dict:
        return await self._request("POST", "/sub-user/delete", json={"subuser_id": subuser_id})

    async def reset_password(self, subuser_id: int, password: str) -> dict:
        return await self._request("POST", "/sub-user/reset-password",
                                   json={"subuser_id": subuser_id, "password": password})

    async def set_blocked(self, subuser_id: int, blocked: bool) -> dict:
        return await self._request("POST", "/sub-user/set-blocked",
                                   json={"subuser_id": subuser_id, "blocked": blocked})

    async def set_blocked_hosts(self, subuser_id: int, hosts: list) -> dict:
        return await self._request("POST", "/sub-user/set-blocked-hosts",
                                   json={"subuser_id": subuser_id, "blocked_hosts": hosts})

    async def set_default_pool_parameters(self, subuser_id: int, params: dict) -> dict:
        body = {"subuser_id": subuser_id, **params}
        return await self._request("POST", "/sub-user/set-default-pool-parameters", json=body)

    # ── Allowed IPs ───────────────────────────────────────────────────────────
    async def add_allowed_ip(self, subuser_id: int, ip: str) -> dict:
        return await self._request("POST", "/sub-user/allowed-ips/add",
                                   json={"subuser_id": str(subuser_id), "ip": ip})

    async def remove_allowed_ip(self, subuser_id: int, ip: str) -> dict:
        return await self._request("POST", "/sub-user/allowed-ips/remove",
                                   json={"subuser_id": str(subuser_id), "ip": ip})

    # ── Balance management ────────────────────────────────────────────────────
    async def get_sub_user_balance(self, subuser_id: int) -> dict:
        return await self._request("GET", "/sub-user/balance/get", params={"subuser_id": subuser_id})

    async def add_sub_user_balance(self, subuser_id: int, amount: float) -> dict:
        return await self._request("POST", "/sub-user/balance/add",
                                   json={"subuser_id": subuser_id, "amount": amount})

    async def drop_sub_user_balance(self, subuser_id: int) -> dict:
        return await self._request("POST", "/sub-user/balance/drop", json={"subuser_id": subuser_id})

    async def get_balance_history(self, subuser_id: int) -> dict:
        return await self._request("GET", "/sub-user/balance/addition-history",
                                   params={"subuser_id": subuser_id})

    # ── Usage stats ───────────────────────────────────────────────────────────
    async def get_sub_user_usage(self, subuser_id: int, period: str = "month") -> dict:
        return await self._request("GET", "/sub-user/usage-stat/get",
                                   params={"subuser_id": subuser_id, "period": period})

    async def get_sub_user_usage_detail(self, subuser_id: int, period: str = "month",
                                        limit: int = 50, offset: int = 0) -> dict:
        return await self._request("GET", "/sub-user/usage-stat/detail",
                                   params={"subuser_id": subuser_id, "period": period,
                                           "limit": limit, "offset": offset})

    async def get_sub_user_errors(self, subuser_id: int, period: str = "month") -> dict:
        return await self._request("GET", "/sub-user/usage-stat/errors",
                                   params={"subuser_id": subuser_id, "period": period})

    # ── Protocols ─────────────────────────────────────────────────────────────
    async def get_sub_user_protocols(self, subuser_id: int) -> dict:
        return await self._request("GET", "/sub-user/supported-protocols/get",
                                   params={"subuser_id": subuser_id})

    async def set_sub_user_protocols(self, subuser_id: int, protocols: list) -> dict:
        return await self._request("POST", "/sub-user/supported-protocols/set",
                                   json={"subuser_id": subuser_id, "protocols": protocols})

    # ══════════════════════════════════════════════════════════════════════════
    #  COMMON / LOCATIONS
    # ══════════════════════════════════════════════════════════════════════════
    async def get_locations(self, pool_type: str = "residential") -> dict:
        return await self._request("GET", "/common/locations", params={"pool_type": pool_type})

    async def get_pool_stats(self, pool_type: str = "residential") -> dict:
        return await self._request("GET", "/common/pool_stats", params={"pool_type": pool_type})

    async def get_countries(self, pool_type: str = "residential") -> list:
        return await self._request("POST", "/common/locations/countries", json={"pool_type": pool_type})

    async def get_states(self, country_code: str, pool_type: str = "residential") -> list:
        return await self._request("POST", "/common/locations/states",
                                   json={"country_code": country_code, "pool_type": pool_type})

    async def get_cities(self, country_code: str, state_code: str = None,
                         pool_type: str = "residential") -> list:
        body = {"country_code": country_code, "pool_type": pool_type}
        if state_code:
            body["state_code"] = state_code
        return await self._request("POST", "/common/locations/cities", json=body)
