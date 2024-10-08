#!/usr/bin/env python
import struct
from urllib.parse import urlparse

import geohash
import random
import time
import logging
import json
import asyncio
import ssl
import websockets
import paho.mqtt.client as mqtt
import socket
import argparse
from . import component_version

logger = logging.getLogger(__name__)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def decode(b):
    e = {}
    d = list(b)
    c = d[0]
    f = c
    g = [c]
    h = 256
    o = h
    for b in range(1, len(d)):
        a = ord(d[b])
        a = d[b] if h > a else e.get(a, f + c)
        g.append(a)
        c = a[0]
        e[o] = f + c
        o+=1
        f = a

    return "".join(g)

async def run(args):
    class userdata:
        is_connected = False

    parsed = urlparse(args.mqtt_server_url)
    assert parsed.scheme == "mqtt"

    mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311, userdata=userdata)
    if parsed.username and parsed.password:
        mqtt_client.username_pw_set(parsed.username, parsed.password)

    def mqtt_on_disconnect(client, userdata, result_code: int):
        userdata.is_connected = False
        while True:
            try:
                logger.info("reconnecting to mqtt server...")
                if client.reconnect() == 0:
                    userdata.is_connected = True
                    return
            except socket.error:
                pass
            time.sleep(1)

    def mqtt_on_connect(client, userdata, flags, result_code: int):
        userdata.is_connected = True
        logger.info("connected to mqtt server")

    def publish_latest_version(self, client):
        latest_version = component_version.__version__
        client.publish("component/hello", json.dumps({
            "latest_version": latest_version,
        }), retain=True)

    mqtt_client.on_disconnect = mqtt_on_disconnect
    mqtt_client.on_connect = mqtt_on_connect
    await asyncio.get_event_loop().run_in_executor(
        None, mqtt_client.connect, parsed.hostname, int(parsed.port or 1883), 60
    )
    mqtt_client.loop_start()

    while True:
        try:
            hosts = ["ws1", "ws3", "ws7", "ws7", "ws8"]
            uri = "wss://{}.blitzortung.org:443/".format(random.choice(hosts))
            async with websockets.connect(uri, ssl=ssl_context) as websocket:
                logger.info("connected to %s", uri)
                await websocket.send('{"a": 111}')
                while True:
                    msg = await websocket.recv()
                    data = json.loads(decode(msg))
                    sig = data.pop("sig", ())
                    data["sig_num"] = len(sig)
                    if userdata.is_connected:
                        geohash_part = "/".join(
                            geohash.encode(data["lat"], data["lon"])
                        )
                        logger.debug("received: %r", data)
                        if args.json:
                            topic = "blitzortung/1.1/{}".format(geohash_part)
                            to_send = {k: data.get(k) for k in ('lat', 'lon', 'status', 'region', 'time')}
                            payload = json.dumps(to_send, separators=(',', ':'))
                            mqtt_client.publish(topic, payload)
                            logger.info("topic: %s: %r", topic, payload)
                        if args.binary:
                            new_topic = "b/{}".format(geohash_part)
                            new_payload = struct.pack("ff", data['lat'], data['lon'])
                            mqtt_client.publish(new_topic, new_payload)
                            logger.info("topic: %s: %r", new_topic, new_payload)

        except websockets.ConnectionClosed:
            pass
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mqtt_server_url")
    parser.add_argument("-l", "--log-level", default="INFO")
    parser.add_argument("-b", "--binary", action="store_true")
    parser.add_argument("-j", "--json", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    asyncio.get_event_loop().run_until_complete(run(args))
