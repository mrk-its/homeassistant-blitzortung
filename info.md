Blitzortung.org lightning detector
============

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).

## Example uses

- Distance and azimuth sensors of lightning strikes nearby
- Counter of lightning strikes
- Emits geo_location events for lightning strikes (visible on the map)
- Data is realtime, with average delay of few seconds

## Configuration

Search for Blitzortung on Configuration/Integrations page. After adding integration, you can optionally configure the location and radius with Blitzortung/Options (by default your home locattion is used with 100km radius).

### See [How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html) for usage instructions