# Blitzortung.org lightning detector

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

<a href="https://www.buymeacoffee.com/emrk" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" style="height: 34px !important;width: 144px !important;" ></a>

Blitzortung.org is a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about lightning strikes in a given area (by default within 100km radius of your home). Data is served through a public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations, it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use their own servers to server data for their own clients).


# Features
- distance and azimuth sensors of lightning strikes nearby
- counter of lightning strikes
- emits geo_location events for lightning strikes (visible on the map)
- data is realtime, with average delay of few seconds

# Manual installation
Place `custom_components/blitzortung` directory inside custom_components dir and restart Home Assistant.

# HACS installation
This component is available on HACS default. Download the integration Blitzortung and then restart Home Assistant.

# Configuration
Search for Blitzortung on `Configuration/Integrations` page. After adding the integration, you can optionally configure the location or tracker and radius with Blitzortung/Options (by default your home location is used with 100km radius).

During configuration there are two ways of providing the location of the center of the map:
1. By providing latitude and longitude. Blitzortung defaults to the `home` location of your Home Assistant instance but you can override that.
2. By providing a tracker or person. Blitzortung will the follow the provided tracker or person - great for boats, RV's and people.

To change the detection radius, time window, and max tracked lightnings, go to **Settings** >> **Devices & services** >> **Blitzortung** >> **Configure**.

Blitzorting integration allows multiple entries, e.g. one for home and one for your boat.

# Reviews and How-Tos
You can read and see (YouTube) how this component was used in the following community video.
[How to Add a Lightning Sensor](https://www.vcloudinfo.com/2020/08/adding-a-lightning-sensor-to-home-assistant.html)

# How to create dev environment
```
git clone https://github.com/mrk-its/homeassistant-blitzortung.git
cd homeassistant-blitzortung
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
prek install
```
