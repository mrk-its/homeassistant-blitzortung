# Blitzortung.org lightning detector

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)


Blitzortung.org ia a worldwide, real time, community collaborative lightning location network. This component uses Blitzortung data and provides real time notifications about ligtnings in given area (by default within 100km radius of your home). Data is served through public MQTT server (dedicated to serve requests for this component) - thanks to geohash-based topics and some other optimizations it greatly reduces amount of data sent to clients comparing to direct websocket connection to Blitzortung servers (it is also required by Blitzortung data usage policy - third party apps must use own servers to server data for their own clients).

# Features
- distance and azimuth sensors of ligtning strikes nearby
- counter of lightning strikes nearby
- data is realtime, with average delay of few seconds


# Manual installation
Place `custom_components/blitzortung` directory inside custom_components dir and restart Home Assistant

# HACS installation
This component may be also added with HACS - simply add this repository as "Custom Repository"

# Configuration
Search for Blitzortung on `Configuration/Integrations` page. After adding integration you can optionally configure location and radius with Blitzortung/Options (by default your home locaiton is used with 100km radius)
