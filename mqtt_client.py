import json
import time
import threading
import configparser
import paho.mqtt.client as mqtt

config = configparser.ConfigParser()
config.read("config.ini")

BROKER = config["mqtt"]["broker"]
PORT = config["mqtt"].getint("port")
CLIENT_ID = config["mqtt"]["client_id"]
TOPIC_SUBSCRIBE = config["topic"]["topic_subscribe"]
TOPIC_TELEMETRY = config["topic"]["topic_telemetry"]
TOPIC_ATTRIBUTE = config["topic"]["topic_attribute"]
USERNAME = config["auth"]["username"]
PASSWORD = config["auth"]["password"]  # empty for ThingsBoard


class MQTTClient:
    def __init__(self, client_id=None, username=None, password=None, on_message_cb=None, on_disconnect_cb=None):
        self.broker = BROKER
        self.port = PORT
        self.topic_subscribe = TOPIC_SUBSCRIBE
        self.topic_telemetry = TOPIC_TELEMETRY
        self.topic_attribute = TOPIC_ATTRIBUTE
        self.on_message_cb = on_message_cb
        self.on_disconnect_cb = on_disconnect_cb

        _client_id = client_id or CLIENT_ID
        _username = username or USERNAME
        _password = password or PASSWORD

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=_client_id,
            reconnect_on_failure=False,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        if _username:
            self.client.username_pw_set(_username, _password or "")

    # rc code descriptions (MQTT 3.1.1)
    _RC_MSG = {
        1: "wrong protocol version",
        2: "bad client ID",
        3: "broker unavailable",
        4: "bad username or password",
        5: "not authorised",
    }

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to broker: {self.broker}")
            if self.topic_subscribe:
                client.subscribe(self.topic_subscribe)
                print(f"Subscribed to: {self.topic_subscribe}")
        else:
            msg = self._RC_MSG.get(rc, f"rc={rc}")
            print(f"Connection failed: {msg}")

    def _on_message(self, client, userdata, msg):
        print(f"[RECEIVED] Topic: {msg.topic} | Payload: {msg.payload.decode()}")
        if self.on_message_cb:
            self.on_message_cb(msg)

    def _on_disconnect(self, client, userdata, rc):
        if rc == 0:
            print("Disconnected from broker (clean)")
        else:
            print(f"Disconnected from broker (rc={rc})")
            if self.on_disconnect_cb:
                self.on_disconnect_cb(rc)

    def connect(self):
        print(f"Connecting to {self.broker}:{self.port} ...")
        self.client.connect(self.broker, self.port, keepalive=60)

    def publish(self, payload, topic=None):
        topic = topic or self.topic_telemetry
        result = self.client.publish(topic, payload)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[PUBLISHED] Topic: {topic} | Payload: {payload}")
        else:
            print(f"[PUBLISH FAILED] rc={result.rc}")
        return result

    def start(self, timeout: int = 10):
        """Connect, start the loop, and wait for CONNACK. Raises on failure or timeout."""
        import threading
        _ready = threading.Event()
        _rc    = [None]

        def _wrap_connect(client, userdata, flags, rc):
            _rc[0] = rc
            _ready.set()
            self._on_connect(client, userdata, flags, rc)

        self.client.on_connect = _wrap_connect
        self.connect()
        self.client.loop_start()

        if not _ready.wait(timeout=timeout):
            self.client.loop_stop()
            raise Exception(f"Connection timeout after {timeout}s — broker unreachable?")

        self.client.on_connect = self._on_connect  # restore original handler

        if _rc[0] != 0:
            self.client.loop_stop()
            msg = self._RC_MSG.get(_rc[0], f"rc={_rc[0]}")
            raise Exception(f"Broker refused connection: {msg}")

    def start_blocking(self):
        self.connect()
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.client.disconnect()


def _publish_loop(client_instance):
    count = 1
    while True:
        payload = json.dumps({"message": "Hello MQTT", "count": count})
        client_instance.publish(payload)
        count += 1
        time.sleep(5)


def main():
    client = MQTTClient()
    client.connect()
    pub_thread = threading.Thread(target=_publish_loop, args=(client,), daemon=True)
    pub_thread.start()
    client.start_blocking()


if __name__ == "__main__":
    main()
