# ⬡ Device Work Flow Simulator (DWFS)

A browser-based visual workflow tool for simulating, monitoring, and automating MQTT device communication with **ThingsBoard** — built for IoT developers and field engineers who need to test device logic without writing code.

---

## What It Does

DWFS lets you build a live **drag-and-drop widget canvas** where each tile represents a real MQTT action — publish a telemetry value, listen for an RPC command, or send a gateway ACK. Widgets can be wired together in a **Node-RED-style trigger chain** so that one action automatically fires the next, with optional timing delays between them.

All communication happens over real MQTT connections to your broker — no mocking, no simulation layer.

---

## Key Features

### Widget Canvas
- Drag, resize, and reshape widgets freely on the canvas
- 5 shape options: Square, Rectangle, Circle, Oval, Pentagon
- Per-widget background colour via full colour picker
- Clone, edit, and delete widgets at any time
- Export / import the entire canvas as JSON

### Widget Types

| Type | What It Does |
|------|-------------|
| **Publish** | Sends a payload to a topic on click or on a repeating timer. Supports static, random, and circular value modes |
| **Subscribe** | Listens to a topic and displays the latest received value. Supports method and param filters |
| **RPC Response** | Listens for ThingsBoard device RPC requests and auto-responds. Supports method filtering |
| **GW RPC Response** | Handles ThingsBoard **Gateway** RPC — parses `device` + `data.id`, sends the correct ACK format |

### Indicator & Display (RPC / GW RPC)
- **💡 Indicator** — a colour-customisable glowing bulb on the tile that lights up when the monitored value is `true`/`1` and dims on `false`/`0`
- **🖥 Display** — shows the live received value as large text on the tile, with a custom text colour
- Both use a dot-notation path (e.g. `params` or `data.params`) to extract the value from the payload
- Each has its own independent colour picker

### Wire Trigger System
- Enter **Wire mode** and click any two widgets to connect them with an animated dashed wire
- When the source widget fires, the target widget automatically publishes
- Click any wire to set a **delay in milliseconds** or delete the connection
- Chains can span multiple widgets (pub → pub → pub → ...)

### Live Monitoring (Work Flow tab)
- **Live Messages** — real-time SSE stream of all incoming MQTT messages
- **Publish History** — every outbound publish logged with topic, payload, size, client, and ✓ ok / ✗ FAILED status (failed publishes are recorded when the client is disconnected)
- **Connection Logs** — live connect / disconnect events with timestamps and disconnect reasons (including broker-side drops)
- **Payload Key Monitor** — auto-extracts JSON keys from received payloads and tracks their value history in a table

### Multi-Client Support
- Manage multiple ThingsBoard device credentials in the **Client DB** tab
- Connect / disconnect any number of clients simultaneously
- Each widget is bound to a specific client by name
- Auto-reconnects previously active clients on server restart

### Publish Panel
- Select from saved topics per client, or add new ones
- Beautify JSON payloads with one click
- Instant publish result feedback (ok / error)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 · Flask · paho-mqtt |
| Realtime push | Server-Sent Events (SSE) |
| Database | SQLite (`dwfs.db`) |
| Frontend | Vanilla JS · HTML · CSS (no framework) |
| Protocol | MQTT 3.1.1 — ThingsBoard Cloud or On-premise |

---

## Project Structure

```
TB_AppMakerDev/
├── app.py            # Flask routes and multi-client MQTT connection pool
├── mqtt_client.py    # paho-mqtt wrapper (connect, publish, subscribe, start)
├── database.py       # SQLite schema, migrations, and all DB helper functions
├── config.ini        # Broker / topic / auth defaults  ← gitignored
├── dwfs.db           # SQLite database                 ← gitignored
└── templates/
    └── index.html    # Single-page app — all UI, CSS, and JS
```

---

## Getting Started

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd TB_AppMakerDev
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install flask paho-mqtt
```

### 2. Configure your broker

Create `config.ini` in the project root (it is gitignored — never commit credentials):

```ini
[mqtt]
broker    = your.thingsboard.host
port      = 1883
client_id = your-device-client-id

[topic]
topic_telemetry = v1/devices/me/telemetry
topic_attribute = v1/devices/me/attributes
topic_subscribe = v1/devices/me/rpc/request/+
topic_sharedkey = v1/devices/me/attributes/request/1

[auth]
; ThingsBoard: username = device access token, password must be empty
username = YOUR_ACCESS_TOKEN
password =
```

### 3. Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## Gateway RPC Flow

DWFS supports the ThingsBoard **Gateway RPC** protocol out of the box.

**Incoming message** (subscribe topic: `v1/gateway/rpc`):
```json
{
  "device": "motor_1",
  "data": {
    "id": 12,
    "method": "setState",
    "params": { "status": "OFF" }
  }
}
```

**Auto-response sent** (publish topic: `v1/gateway/rpc`):
```json
{
  "device": "motor_1",
  "id": 12,
  "data": { "success": true }
}
```

The `device` name and request `id` are extracted automatically from the incoming payload. Use the **Filter** field (comma-separated keywords) on the widget to target specific devices, methods, or param values — e.g. `motor_1, setState, OFF`.

---

## Workflow Example

1. Add a **GW RPC Response** widget bound to `v1/gateway/rpc`, filter: `motor_1, setState`
2. Enable **Indicator** with value identifier `params.status` and pick a green bulb colour
3. Add a **Publish** widget that sends a LoRa command to `v1/gateway/telemetry`
4. Wire the RPC widget → Publish widget with a 200 ms delay
5. When ThingsBoard sends an RPC to `motor_1/setState`, DWFS auto-ACKs it, lights the bulb, and 200 ms later fires the publish — no code required

---

## License

MIT
