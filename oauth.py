# Copyright (c) 2025 GizMoCuz (Domoticz) - SPDX-License-Identifier: MIT
"""
oauth.py - OAuth 2.0 Authorization Code flow manager for the Home Connect API.

Handles authorization URL generation, authorization code exchange, access token
refresh, and persistent token storage in tokens.json inside the plugin HomeFolder.

Does NOT import Domoticz — accepts a log_fn callable so it can be used and tested
outside of the Domoticz runtime.
"""

import json
import os
import threading
import time
import urllib.parse

import requests


def _effective_log_level(mode: int) -> int:
    """Return the effective logging verbosity for a given debug mode.
    Modes 3/4 are cache modes; treat them as log level 2 (Verbose).
    """
    if mode in (3, 4):
        return 2
    return mode  # 0=off, 1=basic, 2=verbose


class OAuthManager:
    """Manages OAuth 2.0 tokens for the Home Connect API."""

    BASE_URL = "https://api.home-connect.com"
    AUTH_PATH = "/security/oauth/authorize"
    TOKEN_PATH = "/security/oauth/token"
    SCOPES = (
        "IdentifyAppliance Washer Dryer Dishwasher Oven "
        "CoffeeMaker Hood CleaningRobot Refrigerator Freezer"
    )

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        callback_host: str = "localhost",
        callback_port: str = "9500",
        debug_mode: int = 0,
        home_folder: str = "",
        log_fn=print,
    ):
        """
        Initialise the OAuth manager.

        Parameters
        ----------
        client_id:      Home Connect developer application client ID.
        client_secret:  Home Connect developer application client secret.
        callback_host:  Hostname or IP used in the redirect_uri (must match the
                        redirect URI registered in the developer portal).
        callback_port:  Local TCP port for the OAuth redirect_uri.
        debug_mode:     Verbosity level (0–4).
        home_folder:    Domoticz plugin HomeFolder path; tokens.json is stored here.
        log_fn:         Callable used for logging (defaults to print for standalone use).
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback_host = str(callback_host)
        self.callback_port = str(callback_port)
        self.debug_mode = debug_mode
        self.home_folder = home_folder
        self.log = log_fn

        # Token state
        self.access_token = ""
        self.refresh_token = ""
        self.token_expiry = 0.0

        # Thread safety for token refresh and save operations
        self._token_lock = threading.RLock()

        # Load persisted tokens from disk (survives plugin restarts)
        self._load_tokens()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_auth_url(self) -> str:
        """Return the full authorization URL the user must visit."""
        redirect_uri = f"http://{self.callback_host}:{self.callback_port}/callback"
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": self.SCOPES,
        }
        return self.BASE_URL + self.AUTH_PATH + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str) -> bool:
        """
        Exchange an authorization code for access + refresh tokens.

        Returns True on success, False on failure.
        """
        redirect_uri = f"http://{self.callback_host}:{self.callback_port}/callback"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        try:
            response = requests.post(
                self.BASE_URL + self.TOKEN_PATH,
                data=payload,
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token", "").strip()
                if not access_token:
                    self.log("HomeConnect: Token response missing access_token.")
                    return False
                expires_in = int(data.get("expires_in", 3600))
                if expires_in <= 0 or expires_in > 86400 * 365:
                    self.log(
                        f"HomeConnect: Suspicious expires_in={expires_in}, defaulting to 3600."
                    )
                    expires_in = 3600
                self._save_tokens(
                    access_token=access_token,
                    refresh_token=data.get("refresh_token", self.refresh_token),
                    expires_in=expires_in,
                )
                if _effective_log_level(self.debug_mode) >= 1:
                    self.log("HomeConnect: Token exchange succeeded.")
                return True
            else:
                self.log(
                    f"HomeConnect: Token exchange failed - "
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                return False
        except requests.RequestException as exc:
            self.log(f"HomeConnect: Token request failed: {type(exc).__name__}")
            return False

    def refresh(self) -> bool:
        """
        Refresh the access token using the stored refresh token.

        Returns True on success, False on failure.
        """
        if not self.refresh_token:
            self.log("HomeConnect: Cannot refresh - no refresh token stored.")
            return False

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        try:
            response = requests.post(
                self.BASE_URL + self.TOKEN_PATH,
                data=payload,
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token", "").strip()
                if not access_token:
                    self.log("HomeConnect: Token response missing access_token.")
                    return False
                expires_in = int(data.get("expires_in", 3600))
                if expires_in <= 0 or expires_in > 86400 * 365:
                    self.log(
                        f"HomeConnect: Suspicious expires_in={expires_in}, defaulting to 3600."
                    )
                    expires_in = 3600
                self._save_tokens(
                    access_token=access_token,
                    refresh_token=data.get("refresh_token", self.refresh_token),
                    expires_in=expires_in,
                )
                if _effective_log_level(self.debug_mode) >= 1:
                    self.log("HomeConnect: Token refreshed successfully.")
                return True
            else:
                self.log(
                    f"HomeConnect: Token refresh failed - "
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                return False
        except requests.RequestException as exc:
            self.log(f"HomeConnect: Token request failed: {type(exc).__name__}")
            return False

    def refresh_if_needed(self) -> bool:
        """
        Refresh the token if it expires within the next 5 minutes.

        Returns True if a refresh was performed, False otherwise.
        """
        with self._token_lock:
            if self.token_expiry == 0.0:
                # No token stored yet
                return False
            if time.time() > self.token_expiry - 300:
                if _effective_log_level(self.debug_mode) >= 1:
                    self.log("HomeConnect: Token nearing expiry, refreshing.")
                return self.refresh()
        return False

    def get_access_token(self) -> str:
        """Return the current access token, refreshing first if needed."""
        self.refresh_if_needed()
        return self.access_token

    def is_authorized(self) -> bool:
        """Return True if a non-empty access token is available."""
        return bool(self.access_token)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        """Persist tokens in memory and to tokens.json on disk."""
        with self._token_lock:
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.token_expiry = time.time() + expires_in

            token_data = {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expiry": self.token_expiry,
            }

            if self.home_folder:
                try:
                    os.makedirs(self.home_folder, exist_ok=True)
                    token_path = os.path.join(self.home_folder, "tokens.json")
                    with open(token_path, "w", encoding="utf-8") as fh:
                        json.dump(token_data, fh)
                    try:
                        os.chmod(token_path, 0o600)
                    except OSError:
                        pass  # chmod not supported on all platforms (e.g. Windows)
                    if _effective_log_level(self.debug_mode) >= 2:
                        self.log(f"HomeConnect: Tokens saved to {token_path}")
                except OSError as exc:
                    self.log(f"HomeConnect: Failed to save tokens.json: {exc}")

    def _load_tokens(self):
        """Load persisted tokens from tokens.json if present."""
        if not self.home_folder:
            return

        token_path = os.path.join(self.home_folder, "tokens.json")
        if not os.path.isfile(token_path):
            return

        try:
            with open(token_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.access_token = data.get("access_token", "")
            self.refresh_token = data.get("refresh_token", "")
            self.token_expiry = float(data.get("token_expiry", 0.0))
            if _effective_log_level(self.debug_mode) >= 1:
                self.log("HomeConnect: Loaded tokens from tokens.json.")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.log(f"HomeConnect: Failed to load tokens.json: {exc}")
