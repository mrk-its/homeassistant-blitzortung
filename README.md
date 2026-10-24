# Blitzortung.org lightning detector

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

<a href="https://www.buymeacoffee.com/emrk" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" style="height: 34px !important;width: 144px !important;" ></a>

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in a given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations, it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).


# Features
- distance and azimuth sensors of lightning strikes nearby
- counter of lightning strikes
- emits geo_location events for lightning strikes (visible on the map)
- sends strikes from a larger area to map cards (for example the weather radar card) without entities or database records
- data is realtime, with average delay of few seconds

# Manual installation
Place `custom_components/blitzortung` directory inside custom_components dir and restart Home Assistant

# HACS installation
This component is available on HACS default

# Configuration
To configure the integration go to **Settings** >> **Devices & services** >> **Add integration** and search for **Blitzortung**. During configuration there are two ways of providing the location:
- By providing latitude and longitude. Blitzortung integration defaults to the `home` location of your Home Assistant instance but you can override that.
- By providing a location entity (`device_tracker`, `person` or `zone`). Blitzortung integration will then follow the coordinates provided by the selected entity.

You can change the coordinates for an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **3 dot menu** >> **Reconfigure**.

To change the detection radius, time window, and max tracked lightnings, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **Configure**. Setting max tracked lightnings to `0` disables the `geo_location` strike entities entirely; the distance, azimuth and counter sensors keep working.

In the **Map cards** section of the same dialog, you can set a larger area for map cards. Strikes from this area go only to map cards, through the websocket API below. They do not change the sensors, they make no entities and they write nothing to the database. The integration keeps them in memory for the time window, at approximately 16 bytes for each strike and 50,000 strikes at most (0.8 MB). When a map card connects, it gets all of these strikes at once, which needs up to approximately 4 MB more for a short time. Set **Map radius** to `0` to use the detection radius. Turn on **Use a different center** to put the map area at a different location.

> [!IMPORTANT]
> If you use a location entity as the coordinate source, the integration will use new coordinates if the location changes by more than 25% of the radius length.

> [!IMPORTANT]
> Integration can create many new `geo_location` entities in a short time, especially if the radius is set to a large value. To protect the database from data floods, it is recommended to exclude the `geo_location` domain from processing by the recorder.
> ```yaml
> recorder:
>   exclude:
>     domains:
>       - geo_location
> ```

# Websocket API

Map cards can subscribe to lightning strikes:

```json
{"type": "blitzortung/subscribe_strikes"}
```

Add `"entry_id"` to get the strikes of one config entry only. First, the integration sends the strikes that it keeps in memory. Then it sends the new strikes one time each second:

```json
{"time_window": 7200, "strikes": [[50.0123, 10.0456, 1760000000123]]}
```

Each strike is `[latitude, longitude, time]`, where `time` is in milliseconds since the Unix epoch. `time_window` (seconds) is in the first event and again when it changes. A card can get the same strike more than one time, for example after a reconnect, so remove duplicates by the full `[latitude, longitude, time]` value.

# Reviews and How-Tos
You can read and see (YouTube) how this component was used in the following community video.
[How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html)

# Dashboard Card

You can use the [Weather Radar Card](https://github.com/makin-things/weather-radar-card) to show real time lightning strikes.

https://github.com/user-attachments/assets/61980296-1bfb-4279-878d-96a6cba575a0


# How to create dev environment
```
git clone https://github.com/mrk-its/homeassistant-blitzortung.git
cd homeassistant-blitzortung
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
prek install
```
