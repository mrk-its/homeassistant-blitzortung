#!/usr/bin/env python
import geohash
import random
import time
import json
import asyncio
import ssl
import websockets
import paho.mqtt.client as mqtt
import socket
import argparse
from . import component_version

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


async def run(args):
    class userdata:
        is_connected = False

    mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311, userdata=userdata)
    if args.username and args.password:
        mqtt_client.username_pw_set(args.username, args.password)

    def mqtt_on_disconnect(client, userdata, result_code: int):
        userdata.is_connected = False
        while True:
            try:
                print("reconnecting to mqtt server...")
                if client.reconnect() == 0:
                    userdata.is_connected = True
                    return
            except socket.error:
                pass
            time.sleep(1)

    def mqtt_on_connect(client, userdata, flags, result_code: int):
        userdata.is_connected = True
        print("connected to mqtt server")
        latest_version = component_version.__version__
        client.publish("component/hello", json.dumps({
            "latest_version": latest_version,
        }), retain=True)

    mqtt_client.on_disconnect = mqtt_on_disconnect
    mqtt_client.on_connect = mqtt_on_connect
    await asyncio.get_event_loop().run_in_executor(
        None, mqtt_client.connect, "localhost", 1883, 60
    )
    mqtt_client.loop_start()

    while True:
        try:
            uri = "wss://ws{}.blitzortung.org:3000/".format(random.randrange(5) + 1)
            async with websockets.connect(uri, ssl=ssl_context) as websocket:
                print(f"connected to {uri}")
                await websocket.send('{"time": 0}')
                while True:
                    msg = await websocket.recv()
                    data = json.loads(msg)
                    sig = data.pop("sig", ())
                    data["sig_num"] = len(sig)
                    if userdata.is_connected:
                        geohash_part = "/".join(
                            geohash.encode(data["lat"], data["lon"])
                        )
                        mqtt_client.publish(
                            "blitzortung/1.1/{}".format(geohash_part), json.dumps(data)
                        )
                        print(repr(data))
        except websockets.ConnectionClosed:
            pass
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username")
    parser.add_argument("-p", "--password")
    args = parser.parse_args()
    asyncio.get_event_loop().run_until_complete(run(args))
