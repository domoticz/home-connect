# Bosch Home Connect plugin for Domoticz
# Copyright (c) 2025 GizMoCuz (Domoticz)
# SPDX-License-Identifier: MIT
#
# Built against the official Home Connect REST API:
#   https://developer.home-connect.com/docs/

"""
<plugin key="HomeConnect" name="Bosch Home Connect" author="GizMoCuz" version="1.0.0"
        externallink="https://developer.home-connect.com/">
    <description>
        <h2>Bosch Home Connect</h2><br/>
        Integrates Bosch/Siemens/Neff/Balay home appliances via the Home Connect cloud API.<br/>
        Requires a developer account at developer.home-connect.com.<br/>
    </description>
    <params>
        <param field="Mode1" label="Client ID" width="400px" required="true" default=""/>
        <param field="Mode2" label="Client Secret" width="400px" required="true" password="true" default=""/>
        <param field="Address" label="OAuth Callback Host (external IP or DynDNS, e.g. myhome.duckdns.org)" width="350px" required="true" default=""/>
        <param field="Port" label="OAuth Callback Port" width="80px" required="true" default="9500"/>
        <param field="Mode6" label="Debug Level" width="200px">
            <options>
                <option label="Off" value="0" default="true"/>
                <option label="Basic" value="1"/>
                <option label="Verbose" value="2"/>
            </options>
        </param>
    </params>
</plugin>
"""

import json
import os
import queue
import time
import urllib.parse

import Domoticz
from oauth import OAuthManager
from api import HomeConnectAPI
import devices as dev
from appliances.base import BaseAppliance
from appliances.washer import WasherAppliance
from appliances.dishwasher import DishwasherAppliance
from appliances.oven import OvenAppliance
from appliances.coffeemaker import CoffeeMakerAppliance
from appliances.hood import HoodAppliance
from appliances.robot import CleaningRobotAppliance
from appliances.refrigerator import RefrigeratorAppliance
from sse import SSEThread


def _make_appliance(ha_id, name, appliance_type, unit_base, api, debug_mode, log_fn):
    """Return the correct appliance subclass instance based on appliance_type."""
    for cls in (
        WasherAppliance,
        DishwasherAppliance,
        OvenAppliance,
        CoffeeMakerAppliance,
        HoodAppliance,
        CleaningRobotAppliance,
        RefrigeratorAppliance,
    ):
        if appliance_type in cls.SUPPORTED_TYPES:
            return cls(
                ha_id=ha_id, name=name, appliance_type=appliance_type,
                unit_base=unit_base, api=api, debug_mode=debug_mode, log_fn=log_fn,
            )
    return BaseAppliance(
        ha_id=ha_id, name=name, appliance_type=appliance_type,
        unit_base=unit_base, api=api, debug_mode=debug_mode, log_fn=log_fn,
    )


_RATE_LIMIT_SECS = 300  # minimum seconds between repeated discovery/poll calls


def _effective_log_level(mode: int) -> int:
    """Return the effective logging verbosity for a given debug mode.
    Modes 3/4 are cache modes; treat them as log level 2 (Verbose).
    """
    if mode in (3, 4):
        return 2
    return mode  # 0=off, 1=basic, 2=verbose


class BasePlugin:
    """Main plugin class — instantiated once by Domoticz at startup."""

    def __init__(self):
        self.oauth = None
        self.api = None
        self.callback_server = None
        self.heartbeat_counter = 0
        self.debug_mode = 0
        self.auth_code_received = False
        self.appliances = []      # list of BaseAppliance instances
        self.poll_counter = 0
        self.sse_thread = None
        self._event_queue = queue.Queue()
        self._last_poll_time = 0.0
        self._last_discovery_time = 0.0
        self._poll_interval = 60  # heartbeats; recalculated after discovery
        self._last_block_log_time = 0.0

    # ------------------------------------------------------------------
    # Appliance helpers
    # ------------------------------------------------------------------

    def _appliance_by_id(self, ha_id):
        """Return the BaseAppliance with the given haId, or None."""
        for appliance in self.appliances:
            if appliance.ha_id == ha_id:
                return appliance
        return None

    def _apply_sse_event(self, event_type, payload):
        """Apply a single SSE event on the main plugin thread."""
        ha_id = payload.get("haId")
        items = payload.get("items", [])

        if event_type in ("STATUS", "NOTIFY", "EVENT"):
            appliance = self._appliance_by_id(ha_id)
            if appliance:
                for item in items:
                    appliance.handle_event(Devices, item.get("key", ""), item.get("value", ""))

        elif event_type == "CONNECTED":
            appliance = self._appliance_by_id(ha_id)
            if appliance:
                appliance.connected = True
                dev.update_switch(Devices, appliance.u(0), True)
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log(f"HomeConnect: {appliance.name} connected.")

        elif event_type == "DISCONNECTED":
            appliance = self._appliance_by_id(ha_id)
            if appliance:
                appliance.connected = False
                dev.update_switch(Devices, appliance.u(0), False)
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log(f"HomeConnect: {appliance.name} disconnected.")

        elif event_type in ("PAIRED", "DEPAIRED"):
            if self.api.blocked_until() > time.time():
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log(
                        f"HomeConnect: Appliance {event_type.lower()} - skipping re-discovery (API blocked)."
                    )
            elif time.time() - self._last_discovery_time >= _RATE_LIMIT_SECS:
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log(f"HomeConnect: Appliance {event_type.lower()} - re-discovering.")
                ha_list = self._discover_appliances()
                self._poll_all(ha_list)
            else:
                if _effective_log_level(self.debug_mode) >= 2:
                    Domoticz.Log(
                        f"HomeConnect: Appliance {event_type.lower()} - skipping re-discovery (discovered recently)."
                    )

        elif event_type == "_RECONNECTED":
            # Full poll after reconnect to catch any missed state changes,
            # but rate-limited to once per 5 minutes to stay within API limits.
            if self.api.blocked_until() > time.time():
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log("HomeConnect: SSE reconnected - skipping poll (API blocked).")
            elif time.time() - self._last_poll_time >= _RATE_LIMIT_SECS:
                if _effective_log_level(self.debug_mode) >= 1:
                    Domoticz.Log("HomeConnect: SSE reconnected - polling all appliances.")
                self._poll_all()
            else:
                if _effective_log_level(self.debug_mode) >= 2:
                    Domoticz.Log("HomeConnect: SSE reconnected - skipping poll (polled recently).")

        else:
            if _effective_log_level(self.debug_mode) >= 2:
                Domoticz.Log(f"HomeConnect: Unknown SSE event type: {event_type}")

    def _start_sse(self):
        """Start the SSE streaming thread."""
        if self.sse_thread is not None and self.sse_thread.is_alive():
            return
        self.sse_thread = SSEThread(
            oauth=self.oauth,
            event_queue=self._event_queue,
            debug_mode=self.debug_mode,
            log_fn=Domoticz.Log,
        )
        self.sse_thread.start()
        if _effective_log_level(self.debug_mode) >= 1:
            Domoticz.Log("HomeConnect: SSE thread started.")

    # ------------------------------------------------------------------
    # Appliance discovery and polling
    # ------------------------------------------------------------------

    def _discover_appliances(self):
        """Fetch appliance list from API and build self.appliances.
        Returns the raw ha_list so the caller can pass it to _poll_all()
        without making a second API call.
        """
        resp = self.api.get("/api/homeappliances")
        ha_list = resp.get("data", {}).get("homeappliances", [])
        using_cache = False
        if not ha_list and self.api.rate_limited:
            cached = self._load_appliance_cache()
            if cached:
                Domoticz.Log(
                    "HomeConnect: Rate limited — loading appliances from cache."
                )
                ha_list = cached
                using_cache = True
            else:
                Domoticz.Log(
                    "HomeConnect: Rate limited and no appliance cache available."
                )
                return []
        if not ha_list:
            Domoticz.Log("HomeConnect: No appliances found.")
            return []

        self.appliances = []
        for i, ha in enumerate(ha_list):
            ha_id = ha.get("haId")
            if not ha_id:
                Domoticz.Log(f"HomeConnect: Skipping appliance at index {i} - missing haId.")
                continue
            unit_base = i * 20 + 1
            raw_name = ha.get("name", ha_id)
            name = raw_name[13:].strip() if raw_name.startswith("Home Connect ") else raw_name
            appliance = _make_appliance(
                ha_id=ha_id,
                name=name,
                appliance_type=ha.get("type", "Unknown"),
                unit_base=unit_base,
                api=self.api,
                debug_mode=self.debug_mode,
                log_fn=Domoticz.Log,
            )
            appliance.connected = bool(ha.get("connected", False))
            appliance.create_devices(Devices)
            self.appliances.append(appliance)
            if _effective_log_level(self.debug_mode) >= 1:
                Domoticz.Log(
                    f"HomeConnect: Discovered {ha.get('type', '?')} '{ha.get('name', '?')}'"
                    f" (units {unit_base}-{unit_base + 19})"
                )

        Domoticz.Log(f"HomeConnect: Discovered {len(self.appliances)} appliance(s).")
        self._update_poll_interval()
        self._last_discovery_time = time.time()
        if not using_cache:
            self._save_appliance_cache(ha_list)
        return ha_list

    def _update_poll_interval(self):
        """Recalculate the heartbeat poll interval based on appliance count.

        Each poll cycle makes 2 API calls per appliance (status + settings).
        Targeting 80% of the typical 1000 req/day limit (800 calls/day):
          interval_seconds = 86400 * 2*N / 800 = 216*N
        Clamped to [5 min, 60 min].
        """
        n = max(1, len(self.appliances))
        interval_seconds = max(300, min(3600, 216 * n))
        self._poll_interval = round(interval_seconds / 5)  # convert to heartbeats (5s each)
        if _effective_log_level(self.debug_mode) >= 1:
            Domoticz.Log(
                f"HomeConnect: Poll interval set to {interval_seconds}s"
                f" ({self._poll_interval} heartbeats) for {n} appliance(s)."
            )

    def _log_block_remaining(self):
        """Log how long the API block has remaining, at most once per hour."""
        now = time.time()
        if now - self._last_block_log_time < 3600:
            return
        remaining = int(self.api.blocked_until() - now)
        h, rem = divmod(remaining, 3600)
        mn, s = divmod(rem, 60)
        Domoticz.Log(
            f"HomeConnect: API blocked — {h:02d}:{mn:02d}:{s:02d} remaining before retry."
        )
        self._last_block_log_time = now

    def _appliance_cache_path(self):
        return os.path.join(Parameters["HomeFolder"], "appliances_cache.json")

    def _save_appliance_cache(self, ha_list):
        path = self._appliance_cache_path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(ha_list, fh, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            Domoticz.Log(f"HomeConnect: Failed to save appliance cache: {exc}")
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _load_appliance_cache(self):
        path = self._appliance_cache_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []

    def _poll_all(self, ha_list=None):
        """Poll status for all appliances.
        Pass ha_list from _discover_appliances() to initialise connected state;
        subsequent calls use the per-appliance connected flag kept current by SSE events.
        """
        if ha_list is not None:
            for ha in ha_list:
                ha_id = ha.get("haId")
                if ha_id:
                    appliance = self._appliance_by_id(ha_id)
                    if appliance:
                        appliance.connected = bool(ha.get("connected", False))

        for appliance in self.appliances:
            appliance.poll(Devices, appliance.connected)

        self._last_poll_time = time.time()

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    def onStart(self):
        # Read and apply debug level
        self.debug_mode = int(Parameters["Mode6"])
        if _effective_log_level(self.debug_mode) >= 1:
            Domoticz.Debugging(1)
        else:
            Domoticz.Debugging(0)

        # Validate required parameters before proceeding
        if not Parameters.get("Mode1", "").strip():
            Domoticz.Error("HomeConnect: Client ID (Mode1) is required.")
            return
        if not Parameters.get("Mode2", "").strip():
            Domoticz.Error("HomeConnect: Client Secret (Mode2) is required.")
            return
        try:
            callback_port = int(Parameters.get("Port", "9500"))
            if not (1 <= callback_port <= 65535):
                raise ValueError()
        except ValueError:
            Domoticz.Error(
                f"HomeConnect: Invalid OAuth Callback Port '{Parameters.get('Port')}'. Must be 1-65535."
            )
            return

        Domoticz.Heartbeat(5)

        Domoticz.Log("HomeConnect: Plugin starting.")

        # Build OAuth manager (loads persisted tokens from tokens.json)
        self.oauth = OAuthManager(
            client_id=Parameters["Mode1"],
            client_secret=Parameters["Mode2"],
            callback_host=Parameters["Address"],
            callback_port=Parameters["Port"],
            debug_mode=self.debug_mode,
            home_folder=Parameters["HomeFolder"],
            log_fn=Domoticz.Log,
        )

        # Build API client
        self.api = HomeConnectAPI(
            oauth=self.oauth,
            home_folder=Parameters["HomeFolder"],
            debug_mode=self.debug_mode,
            log_fn=Domoticz.Log,
        )

        if self.oauth.is_authorized():
            Domoticz.Log("HomeConnect: Already authorized, ready.")
            ha_list = self._discover_appliances()
            self._poll_all(ha_list)
            self._start_sse()
        else:
            # Start local HTTP callback server to receive the OAuth redirect
            self.callback_server = Domoticz.Connection(
                Name="OAuthCallback",
                Transport="TCP/IP",
                Protocol="HTTP",
                Port=Parameters["Port"],
            )
            self.callback_server.Listen()
            Domoticz.Log(
                f"HomeConnect: Please authorize at: {self.oauth.get_auth_url()}"
            )

    def onStop(self):
        if self.sse_thread is not None:
            self.sse_thread.stop()
            self.sse_thread.join(timeout=5)
            self.sse_thread = None
        if self.callback_server is not None:
            try:
                self.callback_server.Disconnect()
            except Exception:
                pass
            self.callback_server = None
        Domoticz.Log("HomeConnect: Plugin stopped.")

    def onHeartbeat(self):
        if self.oauth is None:
            return

        self.heartbeat_counter += 1

        if _effective_log_level(self.debug_mode) >= 2:
            Domoticz.Log(f"HomeConnect: Heartbeat #{self.heartbeat_counter}")

        self.oauth.refresh_if_needed()

        # Drain SSE event queue (events pushed by SSE thread, applied here on main thread)
        try:
            while True:
                event_type, payload = self._event_queue.get_nowait()
                self._apply_sse_event(event_type, payload)
        except queue.Empty:
            pass

        # Poll at a rate calculated from appliance count to stay within API limits.
        # Skip entirely while the API is blocked; keep poll_counter at the threshold
        # so polling fires on the first heartbeat after the block lifts.
        if self.appliances:
            if self.api.blocked_until() > time.time():
                self._log_block_remaining()
                self.poll_counter = self._poll_interval
            else:
                self.poll_counter += 1
                if self.poll_counter >= self._poll_interval:
                    self.poll_counter = 0
                    self._poll_all()

    # ------------------------------------------------------------------
    # OAuth callback server handlers
    # ------------------------------------------------------------------

    def onConnect(self, Connection, Status, Description):
        if Status != 0:
            Domoticz.Error(
                f"HomeConnect: Failed to bind OAuth callback server on port {Parameters.get('Port')}: {Description}"
            )
            self.callback_server = None
            return
        if _effective_log_level(self.debug_mode) >= 1:
            Domoticz.Log(
                f"HomeConnect: OAuth callback server listening on port {Parameters.get('Port')}"
            )

    def onMessage(self, Connection, Data):
        """Handle incoming HTTP request on the OAuth callback server."""
        if self.auth_code_received:
            return

        if _effective_log_level(self.debug_mode) >= 2:
            Domoticz.Log(f"HomeConnect: onMessage Data keys={list(Data.keys())}")

        url = Data.get("URL", "")
        if "?" in url:
            qs = urllib.parse.parse_qs(url.split("?", 1)[1])
            code = qs.get("code", [None])[0]
            if code:
                code = urllib.parse.unquote(code)
                self.auth_code_received = True
                success = self.oauth.exchange_code(code)
                if success:
                    Domoticz.Log("HomeConnect: Authorization successful.")
                    ha_list = self._discover_appliances()
                    self._poll_all(ha_list)
                    self._start_sse()
                else:
                    Domoticz.Error(
                        "HomeConnect: Token exchange failed. Check log and try again."
                    )
                html = (
                    "<html><body>"
                    "<h2>Bosch Home Connect</h2>"
                    "<p>Authorization complete. You may close this window.</p>"
                    "</body></html>"
                )
                Connection.Send({
                    "Status": "200",
                    "Headers": {"Content-Type": "text/html", "Connection": "close"},
                    "Data": html,
                })
                if self.callback_server is not None:
                    try:
                        self.callback_server.Disconnect()
                    except Exception:
                        pass
                    self.callback_server = None
        else:
            Domoticz.Log("HomeConnect: onMessage - no 'code' param found in URL.")

    # ------------------------------------------------------------------
    # Device command handler
    # ------------------------------------------------------------------

    def onCommand(self, Unit, Command, Level, Hue):
        if _effective_log_level(self.debug_mode) >= 1:
            Domoticz.Log(f"HomeConnect: onCommand Unit={Unit} Command={Command} Level={Level}")
        for appliance in self.appliances:
            if appliance.unit_base <= Unit < appliance.unit_base + 20:
                appliance.handle_command(Devices, Unit, Command, Level)
                return

    # ------------------------------------------------------------------
    # Stub callbacks
    # ------------------------------------------------------------------

    def onDisconnect(self, Connection):
        if _effective_log_level(self.debug_mode) >= 2:
            Domoticz.Log(f"HomeConnect: onDisconnect {Connection.Name}")

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        pass

    def onDeviceAdded(self, Unit):
        pass

    def onDeviceModified(self, Unit):
        pass

    def onDeviceRemoved(self, Unit):
        pass


# ----------------------------------------------------------------------
# Required Domoticz global function wrappers
# ----------------------------------------------------------------------

_plugin = BasePlugin()


def onStart():
    _plugin.onStart()


def onStop():
    _plugin.onStop()


def onHeartbeat():
    _plugin.onHeartbeat()


def onConnect(Connection, Status, Description):
    _plugin.onConnect(Connection, Status, Description)


def onMessage(Connection, Data):
    _plugin.onMessage(Connection, Data)


def onCommand(Unit, Command, Level, Hue):
    _plugin.onCommand(Unit, Command, Level, Hue)


def onDisconnect(Connection):
    _plugin.onDisconnect(Connection)


def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)


def onDeviceAdded(Unit):
    _plugin.onDeviceAdded(Unit)


def onDeviceModified(Unit):
    _plugin.onDeviceModified(Unit)


def onDeviceRemoved(Unit):
    _plugin.onDeviceRemoved(Unit)
