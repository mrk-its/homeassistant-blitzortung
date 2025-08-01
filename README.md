# Blitzortung.org lightning detector

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

<a href="https://www.buymeacoffee.com/zacharyd3" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" style="height: 34px !important;width: 144px !important;" ></a>

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).


# Features
- distance and azimuth sensors of lightning strikes nearby
- counter of lightning strikes
- emits geo_location events for lightning strikes (visible on the map)
- based on either a static latitude and longitude, or a device tracker
- data is realtime, with average delay of few seconds

# Manual installation
Place `custom_components/blitzortung` directory inside custom_components dir and restart Home Assistant

# HACS installation
This component is not available on HACS unless it gets merged with the original repo (pull request submitted already)

# Configuration
Search for Blitzortung on `Configuration/Integrations` page. After adding integration, you can optionally configure the location and radius with Blitzortung/Options (by default your home locattion is used with 100km radius).

You can change the source of the coordinates, or completely change the coordinates of an existing Blitzortung configuration using the reconfigure flow, go to **Settings** >> **Devices & services** >> **Blitortung** >> **3 dot menu** >> **Reconfigure**.

To change the detection radius, time window, max tracked lightnings, or disable geocoding, go to **Settings** >> **Devices & services** >> **Blitortung** >> **Configure**.

# Reviews and How-Tos
You can read and see (youtube) how this component was used in the following community video.
[How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html)
