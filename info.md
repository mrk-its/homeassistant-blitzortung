Blitzortung.org lightning detector
============

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).

## Supporting the project
The public MQTT server that feeds this integration is run specifically for this project, and keeping it online costs real money every month. The integration is getting more popular month by month, and the server load - and its cost - grows with it. Two things drive the load the most: a large detection radius and multiple config entries on the same instance. Each config entry subscribes to its own set of geohash topics, and a large radius means more topics and far more strikes to relay.

If you find the integration useful, please consider supporting the server upkeep at [buymeacoffee.com/emrk](https://buymeacoffee.com/emrk). You can also help by keeping the radius as small as your use case allows and by not creating more config entries than you need. Thank you!


## Example uses

- Distance and azimuth sensors of lightning strikes nearby
- Counter of lightning strikes
- Emits geo_location events for lightning strikes (visible on the map)
- Data is realtime, with average delay of few seconds

## Configuration
To configure the integration go to **Settings** >> **Devices & services** >> **Add integration** and search for **Blitzortung**. During configuration there are two ways of providing the location:
- By providing latitude and longitude. Blitzortung integration defaults to the `home` location of your Home Assistant instance but you can override that.
- By providing a location entity (`device_tracker`, `person` or `zone`). Blitzortung integration will then follow the coordinates provided by the selected entity.

You can change the coordinates for an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **3 dot menu** >> **Reconfigure**.

To change the detection radius, time window, and max tracked lightnings, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **Configure**. Setting max tracked lightnings to `0` disables the `geo_location` strike entities entirely; the distance, azimuth and counter sensors keep working.

> [!IMPORTANT]
> If you use a location entity as the coordinate source, the integration will use new coordinates if the location changes by more than 25% of the radius length.

You can change the coordinates for an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitortung** >> **3 dot menu** >> **Reconfigure**.

### See [How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html) for usage instructions
