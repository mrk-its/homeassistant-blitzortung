# Blitzortung.org lightning detector

Blitzortung.org ia a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about ligtnings in given area (by default within 100km radius of your home). Data is served through public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use own servers to server data for their own clients).

# Features
- distance and azimuth sensors of ligtning strikes nearby
- counter of lightning strikes nearby
- data is realtime, with average delay of few seconds

# Manual installation
Place `custom_components/blitzortung` directory inside custom_components dir, restart Home Assistant and search for Blitzortung on `Configuration/Integrations` page

You can also install it with HACS - currently as custom repository, process of adding to HACS default repository is in progress.
