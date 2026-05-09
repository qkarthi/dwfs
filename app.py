import json
import queue
import threading
from datetime import datetime
from flask import Flask, Response, render_template, request, jsonify

from mqtt_client import MQTTClient, TOPIC_TELEMETRY, TOPIC_ATTRIBUTE
from database import (
    init_db, get_all_clients, get_client, create_client, update_client, delete_client,
    log_publish, get_pub_history,
    log_subscribe, get_sub_history,
    log_connection_start, log_connection_end, get_connection_history,
    set_app_state, get_app_state,
    delete_history_records,
    get_topics, add_topic, delete_topic,
    get_widgets, create_widget, update_widget, delete_widget, import_widgets,
    update_widget_position,
    get_triggers, add_trigger, delete_trigger, update_trigger_delay,
)

app = Flask(__name__)
init_db()

message_history = []
sse_clients = []
sse_lock = threading.Lock()

# Multi-connection pools keyed by client DB id (int)
mqtt_clients     = {}   # id -> MQTTClient
conn_history_ids = {}   # id -> connectionHistory row id
client_names     = {}   # id -> client_name
connected_sinces = {}   # id -> datetime string


def push_event(data: dict):
    payload = f"data: {json.dumps(data)}\n\n"
    with sse_lock:
        for q in sse_clients:
            q.put(payload)


def _save_active_clients():
    set_app_state("active_client_ids", json.dumps(list(mqtt_clients.keys())))


def _make_message_handler(cname: str):
    def handler(msg):
        payload = msg.payload.decode()
        entry = {
            "topic":  msg.topic,
            "payload": payload,
            "time":   datetime.now().strftime("%H:%M:%S"),
            "client": cname,
        }
        message_history.append(entry)
        if len(message_history) > 100:
            message_history.pop(0)
        log_subscribe(cname, msg.topic, payload)
        push_event({"type": "message", **entry})
    return handler


def _make_disconnect_handler(cid: int):
    def handler(rc):
        if cid in conn_history_ids:
            log_connection_end(conn_history_ids[cid], "connection_interrupted")
        cname = client_names.get(cid, str(cid))
        mqtt_clients.pop(cid, None)
        conn_history_ids.pop(cid, None)
        client_names.pop(cid, None)
        connected_sinces.pop(cid, None)
        _save_active_clients()
        push_event({"type": "conn_status", "connected": False, "id": cid,
                    "name": cname, "reason": f"Broker disconnected (rc={rc})"})
    return handler


def _do_connect(client_record):
    """Connect one client. Existing connections are untouched. Returns error string or None."""
    cid = client_record["id"]

    # Reconnect: tear down any existing connection for the same id
    if cid in mqtt_clients:
        try:
            mqtt_clients[cid].client.disconnect()
            mqtt_clients[cid].client.loop_stop()
        except Exception:
            pass

    new_mqtt = MQTTClient(
        client_id=client_record["client_id"] or None,
        username=client_record["username"] or None,
        password=client_record["password"] or None,
        on_message_cb=_make_message_handler(client_record["client_name"]),
        on_disconnect_cb=_make_disconnect_handler(cid),
    )
    new_mqtt.broker           = client_record["broker"]
    new_mqtt.port             = int(client_record["port"])
    if client_record.get("topic_subscribe"):
        new_mqtt.topic_subscribe = client_record["topic_subscribe"]

    try:
        new_mqtt.start()
    except Exception as e:
        return str(e)

    since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mqtt_clients[cid]     = new_mqtt
    client_names[cid]     = client_record["client_name"]
    connected_sinces[cid] = since
    conn_history_ids[cid] = log_connection_start(client_record["client_name"])
    _save_active_clients()
    return None


# ── Auto-reconnect all previously active clients on startup ───
def _startup_reconnect():
    saved = get_app_state("active_client_ids")
    if saved:
        try:
            ids = json.loads(saved)
        except Exception:
            ids = [saved] if saved else []
        for cid in ids:
            record = get_client(int(cid))
            if record:
                _do_connect(record)

threading.Thread(target=_startup_reconnect, daemon=True).start()


# ── Dashboard ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", history=message_history, clients=get_all_clients())


@app.route("/stream")
def stream():
    def event_generator():
        q = queue.Queue()
        with sse_lock:
            sse_clients.append(q)
        try:
            while True:
                data = q.get(timeout=30)
                yield data
        except Exception:
            pass
        finally:
            with sse_lock:
                sse_clients.remove(q)

    return Response(event_generator(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/publish", methods=["POST"])
def publish():
    body      = request.get_json()
    client_id = body.get("client_id")
    if client_id is None:
        if not mqtt_clients:
            return jsonify({"status": "error", "message": "No client connected"}), 400
        client_id = next(iter(mqtt_clients))
    client_id = int(client_id)
    topic   = body.get("topic", TOPIC_TELEMETRY)
    payload = body.get("payload", "")
    if client_id not in mqtt_clients:
        cname = client_names.get(client_id, str(client_id))
        log_publish(cname, topic, payload, status="failed")
        return jsonify({"status": "error", "message": "Selected client is not connected"}), 400
    result  = mqtt_clients[client_id].publish(payload, topic=topic)
    if result.rc == 0:
        log_publish(client_names[client_id], topic, payload, status="ok")
        return jsonify({"status": "ok"})
    log_publish(client_names[client_id], topic, payload, status="failed")
    return jsonify({"status": "error", "rc": result.rc}), 500


@app.route("/messages")
def messages():
    return jsonify(message_history)


# ── Connect / Disconnect ───────────────────────────────────
@app.route("/api/connect", methods=["POST"])
def api_connect():
    body      = request.get_json()
    record_id = body.get("id")
    client    = get_client(record_id)
    if not client:
        return jsonify({"status": "error", "message": "Client not found"}), 404

    err = _do_connect(client)
    if err:
        return jsonify({"status": "error", "message": err}), 500

    cid = client["id"]
    push_event({"type": "conn_status", "connected": True, "id": cid,
                "name": client_names[cid], "since": connected_sinces[cid]})
    return jsonify({"status": "ok", "id": cid,
                    "connected_to": client_names[cid], "since": connected_sinces[cid]})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    body      = request.get_json() or {}
    client_id = body.get("id")
    if client_id is None:
        return jsonify({"status": "error", "message": "No client id provided"}), 400
    client_id = int(client_id)
    if client_id not in mqtt_clients:
        return jsonify({"status": "error", "message": "Client not connected"}), 400
    if client_id in conn_history_ids:
        log_connection_end(conn_history_ids[client_id], "manually_disconnected")
    try:
        mqtt_clients[client_id].client.disconnect()
        mqtt_clients[client_id].client.loop_stop()
    except Exception:
        pass
    cname = client_names.get(client_id, str(client_id))
    mqtt_clients.pop(client_id, None)
    conn_history_ids.pop(client_id, None)
    client_names.pop(client_id, None)
    connected_sinces.pop(client_id, None)
    _save_active_clients()
    push_event({"type": "conn_status", "connected": False, "id": client_id,
                "name": cname, "reason": "Manually disconnected"})
    return jsonify({"status": "ok"})


@app.route("/api/active-client")
def api_active_client():
    connected = [
        {"id": cid, "name": client_names[cid], "since": connected_sinces[cid]}
        for cid in mqtt_clients
    ]
    return jsonify({"connected_clients": connected})


# ── Client DB API ──────────────────────────────────────────
@app.route("/api/clients", methods=["GET"])
def api_get_clients():
    return jsonify(get_all_clients())


@app.route("/api/clients", methods=["POST"])
def api_create_client():
    data = request.get_json()
    try:
        new_id = create_client(data)
        return jsonify({"status": "ok", "id": new_id}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/clients/<int:record_id>", methods=["GET"])
def api_get_client(record_id):
    client = get_client(record_id)
    if not client:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify(client)


@app.route("/api/clients/<int:record_id>", methods=["PUT"])
def api_update_client(record_id):
    data = request.get_json()
    try:
        update_client(record_id, data)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/clients/<int:record_id>", methods=["DELETE"])
def api_delete_client(record_id):
    delete_client(record_id)
    return jsonify({"status": "ok"})


# ── History APIs ───────────────────────────────────────────
@app.route("/api/pub-history")
def api_pub_history():
    return jsonify(get_pub_history())


@app.route("/api/sub-history")
def api_sub_history():
    return jsonify(get_sub_history())


@app.route("/api/connection-history")
def api_connection_history():
    return jsonify(get_connection_history())


@app.route("/api/history/delete", methods=["POST"])
def api_history_delete():
    records = request.get_json().get("records", [])
    try:
        delete_history_records(records)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ── Topics API ────────────────────────────────────────────
@app.route("/api/topics", methods=["GET"])
def api_get_topics():
    client = request.args.get("client")
    return jsonify(get_topics(client))


@app.route("/api/topics", methods=["POST"])
def api_add_topic():
    data = request.get_json()
    try:
        new_id = add_topic(data["client"], data["topic"])
        return jsonify({"status": "ok", "id": new_id}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/topics/<int:topic_id>", methods=["DELETE"])
def api_delete_topic(topic_id):
    delete_topic(topic_id)
    return jsonify({"status": "ok"})


# ── Widgets API ───────────────────────────────────────────
@app.route("/api/widgets", methods=["GET"])
def api_get_widgets():
    return jsonify(get_widgets())


@app.route("/api/widgets", methods=["POST"])
def api_create_widget():
    data   = request.get_json()
    new_id = create_widget(data)
    return jsonify({"status": "ok", "id": new_id}), 201


@app.route("/api/widgets/<int:widget_id>", methods=["PUT"])
def api_update_widget(widget_id):
    data = request.get_json()
    update_widget(widget_id, data)
    return jsonify({"status": "ok"})


@app.route("/api/widgets/<int:widget_id>", methods=["DELETE"])
def api_delete_widget(widget_id):
    delete_widget(widget_id)
    return jsonify({"status": "ok"})


@app.route("/api/widgets/<int:widget_id>/position", methods=["PATCH"])
def api_widget_position(widget_id):
    data = request.get_json() or {}
    update_widget_position(
        widget_id,
        int(data.get("pos_x", 0)), int(data.get("pos_y", 0)),
        int(data["width"])  if "width"  in data else None,
        int(data["height"]) if "height" in data else None,
    )
    return jsonify({"status": "ok"})


@app.route("/api/widgets/export", methods=["GET"])
def api_export_widgets():
    data = get_widgets()
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=widgets.json"},
    )


@app.route("/api/widgets/import", methods=["POST"])
def api_import_widgets():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"status": "error", "message": "Expected a JSON array"}), 400
    import_widgets(data)
    return jsonify({"status": "ok", "imported": len(data)})


# ── Triggers API ─────────────────────────────────────────
@app.route("/api/triggers", methods=["GET"])
def api_get_triggers():
    return jsonify(get_triggers())


@app.route("/api/triggers", methods=["POST"])
def api_add_trigger():
    data = request.get_json()
    try:
        new_id = add_trigger(int(data["source_id"]), int(data["target_id"]))
        return jsonify({"status": "ok", "id": new_id}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/triggers/<int:trigger_id>", methods=["PUT"])
def api_update_trigger(trigger_id):
    data = request.get_json() or {}
    try:
        update_trigger_delay(trigger_id, int(data.get("delay_ms", 0)))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/triggers/<int:trigger_id>", methods=["DELETE"])
def api_delete_trigger(trigger_id):
    delete_trigger(trigger_id)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, threaded=True)
