"""The blitzortung integration."""

import logging
import math
import time

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, UnitOfLength, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback, HomeAssistant, State
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event

from homeassistant.util.json import json_loads_object
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
from homeassistant.util.unit_conversion import DistanceConverter

from .const import (
    ATTR_LIGHTNING_DISTANCE,
    ATTR_LIGHTNING_AZIMUTH,
    BLITZORTUNG_CONFIG,
    CONF_IDLE_RESET_TIMEOUT,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONF_ENABLE_GEOCODING,
    CONF_DEVICE_TRACKER,
    CONF_TRACKING_MODE,
    DEFAULT_IDLE_RESET_TIMEOUT,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_ENABLE_GEOCODING,
    DOMAIN,
    PLATFORMS,
    SERVER_STATS,
)
from .geohash_utils import geohash_overlap
from .mqtt import MQTT, MQTT_CONNECTED, MQTT_DISCONNECTED
from .geocoding_utils import GeocodingService
from .version import __version__

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Optional(SERVER_STATS, default=False): bool})},
    extra=vol.ALLOW_EXTRA,
)

BlitzortungConfigEntry = ConfigEntry["BlitzortungCoordinator"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Initialize basic config of blitzortung component."""
    hass.data[BLITZORTUNG_CONFIG] = config.get(DOMAIN) or {}
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: BlitzortungConfigEntry):
    """Set up blitzortung from a config entry."""
    config = hass.data[BLITZORTUNG_CONFIG]

    latitude = config_entry.data[CONF_LATITUDE]
    longitude = config_entry.data[CONF_LONGITUDE]
    radius = config_entry.options[CONF_RADIUS]
    max_tracked_lightnings = config_entry.options[CONF_MAX_TRACKED_LIGHTNINGS]
    time_window_seconds = config_entry.options[CONF_TIME_WINDOW] * 60
    enable_geocoding = config_entry.options.get(CONF_ENABLE_GEOCODING, DEFAULT_ENABLE_GEOCODING)
    tracking_mode = config_entry.data.get(CONF_TRACKING_MODE, "static")
    device_tracker = config_entry.data.get(CONF_DEVICE_TRACKER)


    if max_tracked_lightnings >= 500:
        _LOGGER.warning(
            "Large number of tracked lightnings: %s, it may lead to"
            "bigger memory usage / unstable frontend",
            max_tracked_lightnings,
        )

    if hass.config.units == IMPERIAL_SYSTEM:
        radius_mi = radius
        radius = DistanceConverter.convert(
            radius, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        )
        _LOGGER.info("imperial system, %s mi -> %s km", radius_mi, radius)

    config_entry.runtime_data = BlitzortungCoordinator(
        hass,
        latitude,
        longitude,
        radius,
        max_tracked_lightnings,
        time_window_seconds,
        DEFAULT_UPDATE_INTERVAL,
        enable_geocoding=enable_geocoding,
        tracking_mode=tracking_mode,
        device_tracker=device_tracker,
        server_stats=config.get(SERVER_STATS),
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    await config_entry.runtime_data.connect()

    if not config_entry.update_listeners:
        config_entry.add_update_listener(async_update_options)

    return True


async def async_update_options(hass, config_entry: BlitzortungConfigEntry):
    """Update options."""
    _LOGGER.info("async_update_options")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: BlitzortungConfigEntry):
    """Unload a config entry."""
    await config_entry.runtime_data.disconnect()
    _LOGGER.debug("Disconnected")

    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


async def async_migrate_entry(hass, entry: BlitzortungConfigEntry):
    _LOGGER.debug("Migrating Blitzortung entry from Version %s", entry.version)
    if entry.version == 1:
        latitude = entry.data[CONF_LATITUDE]
        longitude = entry.data[CONF_LONGITUDE]
        radius = entry.data[CONF_RADIUS]
        name = entry.data[CONF_NAME]

        entry.unique_id = f"{latitude}-{longitude}-{name}-lightning"
        entry.data = {CONF_NAME: name}
        entry.options = {
            CONF_LATITUDE: latitude,
            CONF_LONGITUDE: longitude,
            CONF_RADIUS: radius,
        }
        entry.version = 2
    if entry.version == 2:
        entry.options = dict(entry.options)
        entry.options[CONF_IDLE_RESET_TIMEOUT] = DEFAULT_IDLE_RESET_TIMEOUT
        entry.version = 3
    if entry.version == 3:
        entry.options = dict(entry.options)
        entry.options[CONF_TIME_WINDOW] = entry.options.pop(
            CONF_IDLE_RESET_TIMEOUT, DEFAULT_TIME_WINDOW
        )
        entry.version = 4
    if entry.version == 4:
        new_data = entry.data.copy()

        latitude = entry.options.get(CONF_LATITUDE, hass.config.latitude)
        longitude = entry.options.get(CONF_LONGITUDE, hass.config.longitude)
        radius = entry.options.get(CONF_RADIUS, DEFAULT_RADIUS)
        time_window = entry.options.get(CONF_TIME_WINDOW, DEFAULT_TIME_WINDOW)
        max_tracked_lightnings = entry.options.get(
            CONF_MAX_TRACKED_LIGHTNINGS, DEFAULT_MAX_TRACKED_LIGHTNINGS
        )

        new_data[CONF_LATITUDE] = latitude
        new_data[CONF_LONGITUDE] = longitude
        new_options = {
            CONF_RADIUS: radius,
            CONF_TIME_WINDOW: time_window,
            CONF_MAX_TRACKED_LIGHTNINGS: max_tracked_lightnings,
        }

        # Add geocoding option if not present (for migration)
        if CONF_ENABLE_GEOCODING not in entry.options:
            new_options[CONF_ENABLE_GEOCODING] = DEFAULT_ENABLE_GEOCODING

        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=5
        )

    return True


class BlitzortungCoordinator:
    def __init__(
        self,
        hass,
        latitude,
        longitude,
        radius,  # unit: km
        max_tracked_lightnings,
        time_window_seconds,
        update_interval,
        enable_geocoding=True,
        tracking_mode="static",
        device_tracker=None,
        server_stats=False,
    ):
        """Initialize."""
        self.hass = hass
        self.initial_latitude = latitude
        self.initial_longitude = longitude
        self.latitude = latitude
        self.longitude = longitude
        self.radius = radius
        self.max_tracked_lightnings = max_tracked_lightnings
        self.time_window_seconds = time_window_seconds
        self.server_stats = server_stats
        self.enable_geocoding = enable_geocoding
        self.tracking_mode = tracking_mode
        self.device_tracker = device_tracker
        self.last_time = 0
        self.sensors = []
        self.callbacks = []
        self.lightning_callbacks = []
        self.on_tick_callbacks = []
        self.geohash_overlap = geohash_overlap(
            self.latitude, self.longitude, self.radius
        )
        self._disconnect_callbacks = []
        self.unloading = False
        self._location_available = True

        # Initialize geocoding service if enabled
        self.geocoding_service = GeocodingService(hass) if enable_geocoding else None

        _LOGGER.info(
            "lat: %s, lon: %s, radius: %skm, geohashes: %s",
            self.latitude,
            self.longitude,
            self.radius,
            self.enable_geocoding,
            self.tracking_mode,
            self.device_tracker,
            self.geohash_overlap,
        )

        self.mqtt_client = MQTT(
            hass,
            "blitzortung.ha.sed.pl",
            1883,
        )

        self._disconnect_callbacks.append(
            async_dispatcher_connect(
                self.hass, MQTT_CONNECTED, self._on_connection_change
            )
        )
        self._disconnect_callbacks.append(
            async_dispatcher_connect(
                self.hass, MQTT_DISCONNECTED, self._on_connection_change
            )
        )

    @callback
    def _on_connection_change(self, *args, **kwargs):
        if self.unloading:
            return
        for sensor in self.sensors:
            sensor.async_write_ha_state()

    def _get_device_tracker_location(self) -> tuple[float, float] | None:
        """Get current location from device tracker."""
        if not self.device_tracker:
            return None
            
        state = self.hass.states.get(self.device_tracker)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
            
        try:
            latitude = float(state.attributes.get("latitude"))
            longitude = float(state.attributes.get("longitude"))
            return latitude, longitude
        except (TypeError, ValueError):
            return None

    def _update_location(self, new_latitude: float, new_longitude: float):
        """Update the tracking location and recompute geohashes."""
        old_lat, old_lon = self.latitude, self.longitude
        self.latitude = new_latitude
        self.longitude = new_longitude
        
        # Recompute geohash overlap for new location
        new_geohash_overlap = geohash_overlap(
            self.latitude, self.longitude, self.radius
        )
        
        # If geohashes changed, we need to resubscribe
        if new_geohash_overlap != self.geohash_overlap:
            _LOGGER.info(
                "Location changed from (%s, %s) to (%s, %s), updating geohashes from %s to %s",
                old_lat, old_lon, new_latitude, new_longitude,
                self.geohash_overlap, new_geohash_overlap
            )
            self.geohash_overlap = new_geohash_overlap
            
            # Resubscribe to new geohashes if connected
            if self.mqtt_client.connected:
                self.hass.async_create_task(self._resubscribe_geohashes())

    async def _resubscribe_geohashes(self):
        """Resubscribe to MQTT topics for new geohashes."""
        try:
            # Unsubscribe from all blitzortung topics
            _LOGGER.debug("Resubscribing to geohashes: %s", self.geohash_overlap)
            
            # Subscribe to new geohashes
            for geohash_code in self.geohash_overlap:
                geohash_part = "/".join(geohash_code)
                await self.mqtt_client.async_subscribe(
                    "blitzortung/1.1/{}/#".format(geohash_part), self.on_mqtt_message, qos=0
                )
        except Exception as e:
            _LOGGER.error("Error resubscribing to geohashes: %s", e)

    @callback
    def _device_tracker_state_changed(self, event):
        """Handle device tracker state changes."""
        if self.unloading or self.tracking_mode != "device_tracker":
            return
            
        new_state = event.data.get("new_state")
        if not new_state:
            return
            
        location = self._get_device_tracker_location()
        if location:
            new_lat, new_lon = location
            # Only update if location changed significantly (avoid micro-movements)
            if (abs(new_lat - self.latitude) > 0.001 or 
                abs(new_lon - self.longitude) > 0.001):
                self._update_location(new_lat, new_lon)
                self._location_available = True
        else:
            if self._location_available:
                _LOGGER.warning("Device tracker %s location unavailable", self.device_tracker)
                self._location_available = False

    def compute_polar_coords(self, lightning):
        dy = (lightning["lat"] - self.latitude) * math.pi / 180
        dx = (
            (lightning["lon"] - self.longitude)
            * math.pi
            / 180
            * math.cos(self.latitude * math.pi / 180)
        )
        distance = round(math.sqrt(dx * dx + dy * dy) * 6371, 1)
        # Ensure clean rounding by converting to float with proper precision
        distance = float(f"{distance:.1f}")
        azimuth = round(math.atan2(dx, dy) * 180 / math.pi) % 360

        lightning[ATTR_LIGHTNING_DISTANCE] = distance
        lightning[ATTR_LIGHTNING_AZIMUTH] = azimuth

    async def connect(self):
        await self.mqtt_client.async_connect()
        _LOGGER.info("Connected to Blitzortung proxy mqtt server")
        
        # Set up device tracker monitoring if needed
        if self.tracking_mode == "device_tracker" and self.device_tracker:
            # Get initial location from device tracker
            location = self._get_device_tracker_location()
            if location:
                new_lat, new_lon = location
                self._update_location(new_lat, new_lon)
                _LOGGER.info("Initial device tracker location: %s, %s", new_lat, new_lon)
            else:
                _LOGGER.warning("Could not get initial location from device tracker %s", self.device_tracker)
                self._location_available = False
            
            # Set up state change listener
            self._disconnect_callbacks.append(
                async_track_state_change_event(
                    self.hass, [self.device_tracker], self._device_tracker_state_changed
                )
            )
        
        for geohash_code in self.geohash_overlap:
            geohash_part = "/".join(geohash_code)
            await self.mqtt_client.async_subscribe(
                "blitzortung/1.1/{}/#".format(geohash_part), self.on_mqtt_message, qos=0
            )
        if self.server_stats:
            await self.mqtt_client.async_subscribe(
                "$SYS/broker/#", self.on_mqtt_message, qos=0
            )
        await self.mqtt_client.async_subscribe(
            "component/hello", self.on_hello_message, qos=0
        )

        self._disconnect_callbacks.append(
            async_track_time_interval(self.hass, self._tick, DEFAULT_UPDATE_INTERVAL)
        )

    async def disconnect(self):
        self.unloading = True
        await self.mqtt_client.async_disconnect()
        for cb in self._disconnect_callbacks:
            cb()

    def on_hello_message(self, message, *args):
        def parse_version(version_str):
            return tuple(map(int, version_str.split(".")))

        data = json_loads_object(message.payload)
        latest_version_str = data.get("latest_version")
        if latest_version_str:
            default_message = (
                f"New version {latest_version_str} is available. "
                f"[Check it out](https://github.com/mrk-its/homeassistant-blitzortung)"
            )
            latest_version_message = data.get("latest_version_message", default_message)
            latest_version_title = data.get("latest_version_title", "Blitzortung")
            latest_version = parse_version(latest_version_str)
            current_version = parse_version(__version__)
            if latest_version > current_version:
                _LOGGER.info("new version is available: %s", latest_version_str)
                self.hass.components.persistent_notification.async_create(
                    title=latest_version_title,
                    message=latest_version_message,
                    notification_id="blitzortung_new_version_available",
                )

    async def on_mqtt_message(self, message, *args):
        for callback in self.callbacks:
            callback(message)
        if message.topic.startswith("blitzortung/1.1"):
            lightning = json_loads_object(message.payload)
            self.compute_polar_coords(lightning)
            if lightning[SensorDeviceClass.DISTANCE] < self.radius:
                _LOGGER.debug("lightning data: %s", lightning)
                
                # Add geocoding information if enabled
                if self.geocoding_service:
                    try:
                        location_info = await self.geocoding_service.reverse_geocode(
                            lightning["lat"], lightning["lon"]
                        )
                        if location_info:
                            lightning["area"] = location_info.get("area_description", "Unknown")
                            lightning["location"] = location_info.get("display_name", "Unknown")
                            lightning["primary_area"] = location_info.get("primary_area", "Unknown")
                            lightning["country"] = location_info.get("country", "Unknown")
                            _LOGGER.debug("Geocoded lightning location: %s", lightning["area"])
                        else:
                            lightning["area"] = "Unknown"
                            lightning["location"] = "Unknown"
                    except Exception as e:
                        _LOGGER.warning("Geocoding failed for lightning strike: %s", e)
                        lightning["area"] = "Geocoding Failed"
                        lightning["location"] = "Geocoding Failed"
                else:
                    lightning["area"] = "Geocoding Disabled"
                    lightning["location"] = "Geocoding Disabled"
                    
                self.last_time = time.time()
                for callback in self.lightning_callbacks:
                    await callback(lightning)
                for sensor in self.sensors:
                    sensor.update_lightning(lightning)

    def register_sensor(self, sensor):
        self.sensors.append(sensor)
        self.register_on_tick(sensor.tick)

    def register_message_receiver(self, message_cb):
        self.callbacks.append(message_cb)

    def register_lightning_receiver(self, lightning_cb):
        self.lightning_callbacks.append(lightning_cb)

    def register_on_tick(self, on_tick_cb):
        self.on_tick_callbacks.append(on_tick_cb)

    @property
    def is_inactive(self):
        return bool(
            self.time_window_seconds
            and (time.time() - self.last_time) >= self.time_window_seconds
        )

    @property
    def is_connected(self):
        return self.mqtt_client.connected and (
            self.tracking_mode == "static" or self._location_available
        )

    async def _tick(self, *args):
        for cb in self.on_tick_callbacks:
            cb()
