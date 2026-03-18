# Copyright (c) 2025 GizMoCuz (Domoticz) - SPDX-License-Identifier: MIT
"""
sse.py - SSE (Server-Sent Events) streaming thread for the Home Connect API.

Maintains a persistent connection to GET /api/homeappliances/events and pushes
parsed events to a thread-safe queue for processing on the main plugin thread.
"""

import json
import threading
import requests


def _effective_log_level(mode: int) -> int:
    if mode in (3, 4):
        return 2
    return mode


SSE_URL = "https://api.home-connect.com/api/homeappliances/events"


class SSEThread(threading.Thread):
    """Background thread that streams SSE events from the Home Connect API."""

    def __init__(self, oauth, event_queue, debug_mode=0, log_fn=print):
        super().__init__(daemon=True, name="HomeConnect-SSE")
        self.oauth = oauth
        self.event_queue = event_queue
        self.debug_mode = debug_mode
        self.log = log_fn
        self._stop_event = threading.Event()
        self._connected_once = False
        self.reconnect_delay = 10  # seconds, doubles on each failure up to 3600

    def run(self):
        while not self._stop_event.is_set():
            try:
                self._stream()
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                # Normal: server closed the connection or no data received.
                # Reconnect immediately without backoff.
                self.reconnect_delay = 10
                if _effective_log_level(self.debug_mode) >= 2:
                    self.log("HomeConnect: SSE connection closed, reconnecting.")
            except Exception as exc:
                if not self._stop_event.is_set():
                    self.log(
                        f"HomeConnect: SSE unexpected error ({type(exc).__name__}), "
                        f"reconnecting in {self.reconnect_delay}s."
                    )
                    self._stop_event.wait(self.reconnect_delay)
                    self.reconnect_delay = min(self.reconnect_delay * 2, 3600)

    def _stream(self):
        """Open the SSE connection and parse events until stopped or an error occurs."""
        token = self.oauth.get_access_token()
        response = requests.get(
            SSE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
            stream=True,
            timeout=(10, 45),  # (connect_timeout, read_timeout)
        )

        try:
            if response.status_code == 401:
                self.oauth.refresh()
                raise requests.RequestException("401 Unauthorized - token refreshed")

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                self._stop_event.wait(retry_after)
                raise requests.RequestException("429 Rate limited")

            if not response.ok:
                raise requests.RequestException(f"HTTP {response.status_code}")

            if _effective_log_level(self.debug_mode) >= 1:
                self.log("HomeConnect: SSE stream connected.")

            self.reconnect_delay = 10  # reset on successful connection

            # On reconnection (not first connect), signal main thread to poll
            # to catch any state changes missed during the gap.
            if self._connected_once:
                self.event_queue.put(("_RECONNECTED", {}))
            else:
                self._connected_once = True

            event_type = None
            data_lines = []

            for raw_line in response.iter_lines(decode_unicode=True):
                if self._stop_event.is_set():
                    break

                line = raw_line.strip() if raw_line else ""

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        data_lines.append(chunk)
                elif line.startswith(":"):
                    pass  # SSE comment / keep-alive
                elif line == "":
                    if event_type and data_lines:
                        raw_data = " ".join(data_lines)
                        try:
                            payload = json.loads(raw_data)
                            self.event_queue.put((event_type, payload))
                            if _effective_log_level(self.debug_mode) >= 2:
                                self.log(
                                    f"HomeConnect: SSE {event_type}: "
                                    f"{raw_data[:200]}"
                                )
                        except json.JSONDecodeError:
                            if _effective_log_level(self.debug_mode) >= 2:
                                self.log(
                                    f"HomeConnect: SSE invalid JSON: {raw_data[:100]}"
                                )
                    event_type = None
                    data_lines = []
        finally:
            response.close()

    def stop(self):
        """Signal the thread to stop. Returns immediately.
        The thread will exit within the read timeout window (45s max).
        """
        self._stop_event.set()
