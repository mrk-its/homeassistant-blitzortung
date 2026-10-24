Blitzortung.org lightning detector
============

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).

## Example uses

- Distance and azimuth sensors of lightning strikes nearby
- Counter of lightning strikes
- Emits geo_location events for lightning strikes (visible on the map)
- Sends strikes from a larger area to map cards (for example the weather radar card) without entities or database records
- Data is realtime, with average delay of few seconds

## Configuration
To configure the integration go to **Settings** >> **Devices & services** >> **Add integration** and search for **Blitzortung**. During configuration there are two ways of providing the location:
- By providing latitude and longitude. Blitzortung integration defaults to the `home` location of your Home Assistant instance but you can override that.
- By providing a location entity (`device_tracker`, `person` or `zone`). Blitzortung integration will then follow the coordinates provided by the selected entity.

You can change the coordinates for an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **3 dot menu** >> **Reconfigure**.

To change the detection radius, time window, and max tracked lightnings, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **Configure**. Setting max tracked lightnings to `0` disables the `geo_location` strike entities entirely; the distance, azimuth and counter sensors keep working.

In the **Map cards** section of the same dialog, you can set a larger area for map cards. Strikes from this area go only to map cards, through a websocket API (see the README). They do not change the sensors, they make no entities and they write nothing to the database. The integration keeps them in memory for the time window, at approximately 16 bytes for each strike and 50,000 strikes at most (0.8 MB). When a map card connects, it gets all of these strikes at once, which needs up to approximately 4 MB more for a short time. Set **Map radius** to `0` to use the detection radius. Turn on **Use a different center** to put the map area at a different location.

> [!IMPORTANT]
> If you use a location entity as the coordinate source, the integration will use new coordinates if the location changes by more than 25% of the radius length.

You can change the coordinates for an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitortung** >> **3 dot menu** >> **Reconfigure**.

### See [How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html) for usage instructions
