# Copyright (c) 2025 GizMoCuz (Domoticz) - SPDX-License-Identifier: MIT
"""
api.py - REST API client for the Home Connect cloud API.

Wraps the requests library with:
- Automatic Bearer token injection via OAuthManager
- HTTP 401 retry-once after token refresh
- HTTP 429 rate-limit handling with timed block (respects Retry-After / body countdown)
- Consecutive-error backoff: self-imposed 10-min pause after 9 errors in 10 min
- Debug mode 2: verbose request/response logging
- Debug mode 3: write JSON responses to http_cache/ for later replay
- Debug mode 4: read responses from http_cache/ instead of making network calls

Does NOT import Domoticz — accepts a log_fn callable so it can be used and tested
outside of the Domoticz runtime.
"""

import json
import os
import re
import time

import requests

from oauth import OAuthManager


def _effective_log_level(mode: int) -> int:
    """Return the effective logging verbosity for a given debug mode.
    Modes 3/4 are cache modes; treat them as log level 2 (Verbose).
    """
    if mode in (3, 4):
        return 2
    return mode  # 0=off, 1=basic, 2=verbose


def _url_to_filename(method: str, path: str) -> str:
    """
    Convert an HTTP method and API path to a safe cache filename.

    Examples
    --------
    GET  /api/homeappliances          -> GET_api_homeappliances.json
    GET  /api/homeappliances/ABC/programs -> GET_api_homeappliances_ABC_programs.json
    """
    # Strip leading slash and replace non-alphanumeric chars (except dots) with _
    safe_path = re.sub(r"[^A-Za-z0-9.]", "_", path.lstrip("/"))
    # Collapse multiple consecutive underscores
    safe_path = re.sub(r"_+", "_", safe_path).strip("_")
    return f"{method.upper()}_{safe_path}.json"


class HomeConnectAPI:
    """HTTP client for the Home Connect REST API."""

    BASE_URL = "https://api.home-connect.com"

    # Bosch blocks after 10 consecutive errors in 10 min; we stop at 9.
    _MAX_CONSEC_ERRORS = 9
    _ERROR_WINDOW_SECS = 600   # 10 minutes
    _ERROR_BLOCK_SECS  = 600   # self-imposed pause length

    def __init__(
        self,
        oauth: OAuthManager,
        home_folder: str,
        debug_mode: int = 0,
        log_fn=print,
    ):
        """
        Initialise the API client.

        Parameters
        ----------
        oauth:       Authorised OAuthManager instance.
        home_folder: Domoticz plugin HomeFolder; used for the http_cache sub-directory.
        debug_mode:  Verbosity / cache behaviour level (0–4).
        log_fn:      Callable used for logging (defaults to print for standalone use).
        """
        self.oauth = oauth
        self.home_folder = home_folder
        self.debug_mode = debug_mode
        self.log = log_fn
        self.CACHE_DIR = os.path.join(home_folder, "http_cache")

        # Rate-limit / error-block state
        self.rate_limited = False       # True while either block is active
        self._rate_limit_until = 0.0   # epoch: Bosch-imposed 429 block expiry
        self._error_block_until = 0.0  # epoch: self-imposed consecutive-error block expiry
        self._consec_errors = 0
        self._first_error_time = 0.0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get(self, path: str) -> dict:
        """Perform a GET request and return the parsed JSON body."""
        return self._request("GET", path)

    def put(self, path: str, body: dict) -> dict:
        """Perform a PUT request with a JSON body and return parsed JSON."""
        return self._request("PUT", path, body=body)

    def delete(self, path: str) -> dict:
        """Perform a DELETE request and return parsed JSON."""
        return self._request("DELETE", path)

    def blocked_until(self) -> float:
        """Return the epoch timestamp until which all API calls are suppressed, or 0."""
        return max(self._rate_limit_until, self._error_block_until)

    # ------------------------------------------------------------------
    # Core request dispatcher
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body=None) -> dict:
        """
        Execute an API request honouring the current debug_mode.

        Returns a dict with the parsed JSON response, or {} on any error.
        Calls are silently suppressed (returning {}) while a rate-limit or
        error block is active.
        """
        filename = _url_to_filename(method, path)

        # ------ Offline / cache-read mode --------------------------------
        if self.debug_mode == 4:
            return self._load_from_cache(filename)

        # ------ Block check ----------------------------------------------
        now = time.time()
        until = self.blocked_until()
        if until > now:
            self.rate_limited = True
            if _effective_log_level(self.debug_mode) >= 2:
                self.log(
                    f"HomeConnect: Skipping {method} {path} — API blocked for "
                    f"{int(until - now)}s more."
                )
            return {}

        # ------ Live request ---------------------------------------------
        url = self.BASE_URL + path
        headers = {
            "Authorization": f"Bearer {self.oauth.get_access_token()}",
            "Accept": "application/vnd.bsh.sdk.v1+json",
        }
        if body is not None:
            headers["Content-Type"] = "application/vnd.bsh.sdk.v1+json"

        result = self._do_http(method, url, headers, body, path, filename, retry=True)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _track_error(self):
        """Record a consecutive API error; self-impose a block if threshold is reached."""
        now = time.time()
        if self._consec_errors == 0:
            self._first_error_time = now
        self._consec_errors += 1
        if (
            self._consec_errors >= self._MAX_CONSEC_ERRORS
            and (now - self._first_error_time) <= self._ERROR_WINDOW_SECS
        ):
            self._error_block_until = now + self._ERROR_BLOCK_SECS
            self.rate_limited = True
            self.log(
                f"HomeConnect: {self._consec_errors} consecutive errors within 10 min "
                f"— pausing API calls for 10 min to avoid Bosch block."
            )
            self._consec_errors = 0
            self._first_error_time = 0.0

    def _clear_errors(self):
        """Reset consecutive-error state after a successful response."""
        self.rate_limited = False
        self._consec_errors = 0
        self._first_error_time = 0.0

    def _do_http(
        self,
        method: str,
        url: str,
        headers: dict,
        body,
        path: str,
        filename: str,
        retry: bool,
    ) -> dict:
        """Perform the actual HTTP call, handling common error codes."""
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=body,
                timeout=15,
            )
        except requests.RequestException as exc:
            self.log(f"HomeConnect: Request error {method} {path}: {exc}")
            self._track_error()
            return {}

        # Debug mode 2: verbose logging
        if _effective_log_level(self.debug_mode) >= 2:
            preview = response.text[:300]
            self.log(
                f"HomeConnect: {method} {path} -> HTTP {response.status_code} | {preview}"
            )

        # Handle status codes
        if response.status_code == 401 and retry:
            self.log("HomeConnect: HTTP 401, refreshing token and retrying.")
            if self.oauth.refresh():
                new_token = self.oauth.get_access_token()
                if not new_token:
                    self.log(
                        "HomeConnect: Token refresh succeeded but token is empty, aborting."
                    )
                    return {}
                headers["Authorization"] = f"Bearer {new_token}"
                return self._do_http(
                    method, url, headers, body, path, filename, retry=False
                )
            self.log("HomeConnect: Token refresh failed after 401.")
            return {}

        if response.status_code == 429:
            self.rate_limited = True
            self._consec_errors = 0   # 429 is rate limiting, not an API error streak
            self._first_error_time = 0.0
            secs = None
            retry_after = response.headers.get("Retry-After", "")
            if retry_after:
                try:
                    secs = int(retry_after)
                except ValueError:
                    pass
            if secs is None:
                try:
                    err_body = response.json()
                    desc = err_body.get("error", {}).get("description", "")
                    m = re.search(r"(\d+)\s*seconds", desc)
                    if m:
                        secs = int(m.group(1))
                except Exception:
                    pass
            if secs is not None:
                self._rate_limit_until = time.time() + secs
                h, rem = divmod(secs, 3600)
                mn, s = divmod(rem, 60)
                wait_info = f" Retry after: {h:02d}:{mn:02d}:{s:02d}."
            else:
                wait_info = ""
            self.log(
                f"HomeConnect: Rate limit exceeded (HTTP 429) for {method} {path}.{wait_info}"
            )
            return {}

        if not response.ok:
            self.log(
                f"HomeConnect: HTTP error {response.status_code} for {method} {path}."
            )
            self._track_error()
            return {}

        # Parse JSON
        try:
            data = response.json()
        except ValueError:
            if _effective_log_level(self.debug_mode) >= 1:
                self.log(
                    f"HomeConnect: Non-JSON response for {method} {path} "
                    f"(status {response.status_code})."
                )
            data = {}

        # Debug mode 3: write to cache
        if self.debug_mode == 3:
            self._write_to_cache(filename, data)

        self._clear_errors()
        return data

    def _load_from_cache(self, filename: str) -> dict:
        """Load a cached JSON response from http_cache/."""
        filepath = os.path.join(self.CACHE_DIR, filename)
        if not os.path.isfile(filepath):
            self.log(
                f"HomeConnect: Cache miss - {filename} not found in {self.CACHE_DIR}."
            )
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if _effective_log_level(self.debug_mode) >= 2:
                self.log(f"HomeConnect: Cache hit - loaded {filename}.")
            return data
        except (OSError, json.JSONDecodeError) as exc:
            self.log(f"HomeConnect: Failed to read cache file {filename}: {exc}")
            return {}

    def _write_to_cache(self, filename: str, data: dict):
        """Write a JSON response to http_cache/ for later offline replay."""
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(self.CACHE_DIR, filename)
        temp_path = cache_path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(temp_path, cache_path)
            if _effective_log_level(self.debug_mode) >= 2:
                self.log(f"HomeConnect: Cached response to {filename}.")
        except OSError as exc:
            self.log(f"HomeConnect: Failed to write cache file {filename}: {exc}")
            try:
                os.remove(temp_path)
            except OSError:
                pass
