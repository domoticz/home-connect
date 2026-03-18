# Bosch Home Connect – Domoticz Plugin

Monitor and control your Bosch/Siemens/Neff/Balay appliances from Domoticz via the Home Connect cloud API.

**Supported brands:** Bosch · Siemens · Neff · Balay

---

## Supported Appliances

| Appliance | Domoticz Devices Created |
|-----------|--------------------------|
| Washer | Online, Power, Operation, Door, Remote Control, Child Lock, Program, Progress, Finish Time, Temperature, Spin Speed |
| Dryer | Online, Power, Operation, Door, Remote Control, Child Lock, Program, Progress, Finish Time, Drying Target |
| WasherDryer | Combined — all Washer + Dryer devices |
| Dishwasher | Online, Power, Operation, Door, Remote Control, Child Lock, Program, Progress, Finish Time, Intensiv Zone, Brilliance Dry, Vario Speed |
| Oven | Online, Power, Operation, Door, Remote Control, Child Lock, Program, Progress, Finish Time, Cavity Temperature, Setpoint Temperature, Alarm Clock |
| Microwave | Online, Power, Operation, Door, Remote Control, Program |
| WarmingDrawer | Online, Power, Operation, Warming Level |
| CoffeeMaker | Online, Power, Operation, Beverage Program, Bean Amount, Temperature, Coffee Counter, Hot Water Counter |
| Hood | Online, Power, Venting Level, Intensive Level, Functional Light |
| CleaningRobot | Online, Power, Operation, Cleaning Program, Cleaning Mode, Dust Box, Lifted |
| Refrigerator | Online, Power, Fridge Temperature, Fridge Setpoint, Door, Super Cool, Eco Mode, Vacation Mode |
| FridgeFreezer | Online, Power, Fridge Temperature, Fridge Setpoint, Fridge Door, Freezer Temperature, Freezer Setpoint, Freezer Door, Super Cool, Super Freeze, Eco Mode |
| Freezer | Online, Power, Freezer Temperature, Freezer Setpoint, Door, Super Freeze |

---

## Prerequisites

Before you begin, make sure you have the following:

- **Domoticz 2022.1 or later** with Python plugin support enabled
- **Python 3.6+** installed on the Domoticz host
- **`requests` library** — install with:
  ```bash
  pip install requests
  ```
- A **Home Connect account** at [home-connect.com](https://www.home-connect.com)
- At least one supported appliance **added to the Home Connect app** on your phone
- **Network access** to `api.home-connect.com` — this is a cloud-based API; there is no local/LAN alternative

---

## Step 1 — Install the Plugin

1. **Clone the repository** into your Domoticz plugins directory:

   ```bash
   cd /home/pi/domoticz/plugins
   git clone https://github.com/domoticz/home-connect.git HomeConnect
   ```

   On Windows, open a terminal in `C:\domoticz\plugins\` and run:
   ```
   git clone https://github.com/domoticz/home-connect.git HomeConnect
   ```

2. **Install the required Python library:**

   ```bash
   pip install -r /home/pi/domoticz/plugins/HomeConnect/requirements.txt
   ```

   > **Docker users:** The official Domoticz Docker image already includes all necessary Python libraries. You can skip this step.

3. **Restart Domoticz** to detect the new plugin:

   ```bash
   sudo systemctl restart domoticz
   ```

---

## Step 2 — Set Up Port Forwarding and Determine Your Redirect URI

**Important:** Home Connect does not accept internal (LAN) IP addresses such as `192.168.x.x` or `127.0.0.1` as redirect URIs. The redirect URI you register must be reachable from the internet.

You have two options:

**Option A — Use your external IP address**

Find your router's external (public) IP address (e.g. from [whatismyip.com](https://www.whatismyip.com)).
Then set up **port forwarding** on your router:

- External port: `9500` (or whichever port you choose)
- Internal destination: your Domoticz server's LAN IP and the same port (e.g. `192.168.0.70:9500`)

Your redirect URI will be: `http://<your-external-ip>:9500/callback`

**Option B — Use a dynamic DNS hostname (recommended)**

If your external IP address changes regularly (most home connections), use a free dynamic DNS service such as [DuckDNS](https://www.duckdns.org) or [No-IP](https://www.noip.com) to get a stable hostname (e.g. `myhome.duckdns.org`). Set up port forwarding as in Option A.

Your redirect URI will be: `http://myhome.duckdns.org:9500/callback`

> **Note:** The redirect URI only needs to be reachable at the moment you perform the one-time authorization in Step 5. After that, the plugin uses the saved tokens and never uses the redirect URI again. Port forwarding can be removed afterwards if desired.

The port (`9500` by default) can be changed. If you change it, update both the Domoticz hardware settings and the redirect URI in the developer portal.

---

## Step 3 — Register a Developer Application

You need to register an OAuth application in the Home Connect developer portal to obtain API credentials.

1. Go to [developer.home-connect.com](https://developer.home-connect.com) and sign in with your **Home Connect account** (the same account your appliances are registered to).

2. Navigate to **Applications → Register Application**.

3. Fill in the registration form:

   - **Application ID**
     Any name you like, e.g. `Domoticz`.

   - **OAuth Flow**
     Select `Authorization Code Grant`.

   - **Home Connect User Account**
     Enable **"Use same credentials as developer account"**. This links the developer app to your real appliances.

   - **Redirect URI**
     Enter the externally reachable URI you determined in Step 2, for example:
     ```
     http://myhome.duckdns.org:9500/callback
     ```
     or with an external IP:
     ```
     http://1.2.3.4:9500/callback
     ```
     This must exactly match what you configure in Domoticz (same host, same port, same path `/callback`). Internal IP addresses (`192.168.x.x`, `127.0.0.1`) will not work — Home Connect rejects them with a 403 error.

4. Click **Save**.

5. On the application details page, copy your **Client ID** and **Client Secret**.
   Keep the Client Secret private — treat it like a password.

---

## Step 4 — Add Hardware in Domoticz

1. In Domoticz, go to **Settings → Hardware**.

2. Click **Add** and fill in the following fields:

   - **Name**
     Any descriptive name, e.g. `Home Connect`.

   - **Type**
     Select `Bosch Home Connect` from the dropdown.

   - **Client ID**
     Paste the Client ID from Step 3.

   - **Client Secret**
     Paste the Client Secret from Step 3.

   - **OAuth Callback Host**
     Enter the **externally reachable** hostname or IP address you determined in Step 2.
     This must exactly match the host part of the redirect URI you registered in Step 3.
     Internal IP addresses such as `192.168.x.x` will not work — use your external IP or dynamic DNS hostname.
     Examples: `1.2.3.4`, `myhome.duckdns.org`.

   - **OAuth Callback Port**
     The port the plugin listens on for the OAuth callback. Default: `9500`.
     Must match the port in the redirect URI registered in Step 3.

   - **Debug**
     Leave as `Off` for normal use. See [Debug Modes](#debug-modes) for options.

3. Click **Save**.

The plugin will start and log an authorization URL to the Domoticz log within a few seconds.

---

## Step 5 — Authorize (One-Time)

Authorization only needs to be done once. The plugin saves the tokens and refreshes them automatically afterwards.

1. Open the Domoticz log: **Setup → Log**.

2. Find the line logged by the plugin that starts with:
   ```
   HomeConnect: Please authorize at: https://api.home-connect.com/security/oauth/authorize?...
   ```

3. Copy the full URL and open it in a web browser.
   Use a browser that can reach the OAuth Callback Host you configured — typically a browser on the same network as Domoticz.

4. Log in to your Home Connect account and click **Allow** to grant the requested permissions.

5. Your browser will be redirected to `http://<your-host>:<port>/callback?code=...`.
   The plugin's built-in HTTP server receives this redirect, exchanges the authorization code for tokens, and saves them to disk.
   You will see a simple confirmation page — you can close the browser tab.

6. The Domoticz log will show:
   ```
   HomeConnect: Authorization successful.
   ```

7. Devices for all discovered appliances will appear in Domoticz under **Switches** and **Sensors** within a few seconds.

> **Token storage:** Tokens are saved to `plugins/HomeConnect/tokens.json`.
> Keep this file private — it grants access to your Home Connect account.
> Do not include it in version control.

---

## Devices Reference

Each appliance creates a group of Domoticz devices named `<Appliance Name> - <Device>`.
For example, a washer named "Washing Machine" creates devices like:
`Washing Machine - Power`, `Washing Machine - Program`, `Washing Machine - Progress`, etc.

| Device | Domoticz Type | Notes |
|--------|---------------|-------|
| Online | Switch | On = connected to cloud, Off = unreachable |
| Power | Selector Switch | Off / On / Standby |
| Operation | Selector Switch | Inactive / Ready / Running / Paused / ActionRequired / Finished / Error / Aborting |
| Door | Contact Sensor | Open / Closed |
| Remote Control | Switch | On = appliance currently allows remote commands |
| Child Lock | Switch | Toggleable on/off |
| Program | Selector Switch | Dynamically populated from the appliance's available programs |
| Progress | Percentage | 0–100% of current program completion |
| Finish Time | Text device | Estimated time remaining or finish timestamp |
| Temperature | Temperature sensor | Current cavity or fluid temperature in °C |
| Setpoint Temperature | Custom sensor | Target temperature in °C (read/write where supported) |
| Energy | kWh device | Cumulative energy consumption (only on appliances that report it) |

---

## Debug Modes

| Mode | Description |
|------|-------------|
| 0 – Off | No extra logging. Errors only. |
| 1 – Basic | Logs key events: token refresh, authorization steps, appliance state changes. |
| 2 – Verbose | Logs every HTTP request and the full API response body. |
| 3 – Write HTTP cache | Makes real API calls and saves every response as a JSON file under `plugins/HomeConnect/http_cache/`. Logging level: Basic. |
| 4 – Read HTTP cache (offline) | Loads API responses from `http_cache/` instead of making real network calls. Useful for development and testing without internet access or API quota. Logging level: Basic. |

### HTTP Cache Workflow

1. Run the plugin with **mode 3** while your appliances are active to capture a set of real API responses.
2. Switch to **mode 4** to replay those saved responses without making any network calls.
3. Return to **mode 0** for normal production use.

Cache files are stored as `http_cache/GET_api_homeappliances.json` etc., named after the HTTP method and URL path. They can be committed to version control as test fixtures or shared with developers.

---

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Authorization URL keeps appearing in the log | Tokens not yet obtained | Complete Step 5 |
| Browser shows `unauthorized_client` after login | Redirect URI mismatch | Ensure the URI in the developer portal exactly matches the OAuth Callback Host + Port in Domoticz (including `http://`, the IP, the port, and `/callback`) |
| Home Connect returns `403 Forbidden` during login | Internal IP used as redirect URI | Home Connect rejects internal IPs (`192.168.x.x`, `127.0.0.1`). Use an external IP or dynamic DNS hostname and set up port forwarding (see Step 2) |
| Browser redirected but page not loading | Port forwarding not set up or wrong host | Ensure port forwarding is configured on your router (external port 9500 → Domoticz LAN IP:9500) and that the OAuth Callback Host in Domoticz matches the registered redirect URI |
| "Missing cache file" errors | Mode 4 selected but `http_cache/` is empty | Run with mode 3 first to capture real data, then switch to mode 4 |
| Devices not updating | Appliance offline or remote control disabled | Check appliance connectivity in the Home Connect app |
| Program selector is empty | No programs returned by the API | Ensure the appliance is powered on and connected |
| "Rate limited" in log | Too many API requests | Normal — the plugin backs off automatically |
| Token refresh fails | Client Secret wrong or revoked | Re-enter credentials in hardware settings and restart |
| "Connection refused" on callback port | Port already in use | Change OAuth Callback Port (and update the redirect URI in the developer portal to match) |

---

## Notes and Limitations

- **Cloud-only:** The Home Connect API requires an active internet connection. Bosch/Siemens do not provide a local LAN API.
- **API rate limits:** The developer sandbox allows approximately 250 calls/day. Production apps have higher limits. The plugin minimizes calls by using SSE streaming for real-time updates rather than polling.
- **Remote start:** Programs can only be started remotely when the appliance has **Remote Control** enabled. Enable this in the appliance's own settings menu or in the Home Connect app.
- **Real-time updates:** A background thread maintains a persistent SSE connection to the API. State changes are typically reflected in Domoticz within 1–2 seconds.
- **Multiple accounts:** Each Domoticz hardware instance supports one Home Connect account. To monitor appliances from multiple accounts, add multiple hardware instances with separate credentials.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
