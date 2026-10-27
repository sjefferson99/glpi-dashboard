"""Read-only client for the GLPI v1 REST API.

The dashboard uses v1 rather than v2 because v2 has no endpoints for the links
between ITIL records and CIs or projects. The client logs in with a user API
token and an API client app token, keeps one session, and opens a new one when
GLPI expires it.

Error messages carry only the HTTP status and GLPI's ``ERROR_*`` code, never a
token or the rest of a response body, so they are safe to log and to show on
the page.
"""
import re

import httpx

PAGE = 500
ITEMTYPE = re.compile(r"[A-Za-z_]+")


class GlpiError(Exception):
    """A GLPI request failed; the message is safe to log and display."""


def _code(r):
    """Returns GLPI's error code from a response, prefixed with a space.

    Args:
        r: The failed ``httpx.Response``.

    Returns:
        ``" ERROR_..."`` when the body is GLPI's ``["ERROR_...", "detail"]`` list,
        otherwise an empty string. The detail is never returned.
    """
    try:
        body = r.json()
    except ValueError:
        return ""
    code = body[0] if isinstance(body, list) and body else ""
    return f" {code}" if isinstance(code, str) and code.startswith("ERROR_") else ""


class Glpi:
    """One session against GLPI's v1 API.

    Args:
        base_url: GLPI's address as this container reaches it, e.g. ``http://glpi``.
        app_token: The API client's app token.
        user_token: The read-only user's API token.
        timeout: Seconds allowed for each request.
    """

    def __init__(self, base_url, app_token, user_token, timeout=30.0):
        self.base = base_url.rstrip("/") + "/apirest.php"
        self.app_token = app_token
        self.user_token = user_token
        self.session = None
        self.http = httpx.AsyncClient(timeout=timeout)

    async def _login(self):
        r = await self.http.get(self.base + "/initSession", headers={
            "App-Token": self.app_token, "Authorization": "user_token " + self.user_token})
        if r.status_code != 200:
            raise GlpiError(f"initSession: HTTP {r.status_code}{_code(r)}")
        self.session = r.json()["session_token"]

    def _headers(self):
        return {"App-Token": self.app_token, "Session-Token": self.session}

    async def get(self, path, params=None):
        """GETs an API path, logging in first if there is no session.

        Args:
            path: The path under ``apirest.php``, e.g. ``/Ticket``.
            params: Optional query parameters.

        Returns:
            The decoded JSON body, or ``[]`` when the requested range starts past the last row.

        Raises:
            GlpiError: GLPI answered with an error, or the session expired twice in a row.
        """
        for attempt in (1, 2):
            if not self.session:
                await self._login()
            r = await self.http.get(self.base + path, params=params, headers=self._headers())
            # GLPI answers an expired session with 400/401 ERROR_SESSION_TOKEN_*: log in once more.
            if r.status_code in (400, 401) and "ERROR_SESSION_TOKEN" in r.text and attempt == 1:
                self.session = None
                continue
            if r.status_code == 400 and "ERROR_RANGE_EXCEED_TOTAL" in r.text:
                return []
            if r.status_code not in (200, 206):
                raise GlpiError(f"GET {path}: HTTP {r.status_code}{_code(r)}")
            return r.json()

    async def all(self, itemtype):
        """Reads every non-deleted item of a type, a page at a time.

        Args:
            itemtype: A plain GLPI itemtype such as ``Ticket`` or ``Computer``. Anything
                else is refused before a request is made, since it becomes part of the URL.

        Returns:
            A list of rows as GLPI stores them, with dropdowns as ids (unexpanded).

        Raises:
            GlpiError: The itemtype isn't plain letters and underscores, or a request failed.
        """
        if not ITEMTYPE.fullmatch(itemtype):
            raise GlpiError(f"bad itemtype {itemtype!r}")
        out, start = [], 0
        while True:
            page = await self.get(f"/{itemtype}", {"range": f"{start}-{start + PAGE - 1}",
                                                   "expand_dropdowns": "false"})
            out += page or []
            if not page or len(page) < PAGE:
                return out
            start += PAGE

    async def close(self):
        """Ends the GLPI session if there is one (best effort) and closes the HTTP client."""
        if self.session:
            try:
                await self.http.get(self.base + "/killSession", headers=self._headers())
            except httpx.HTTPError:
                pass
        await self.http.aclose()
