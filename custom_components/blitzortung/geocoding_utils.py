"""Geocoding utilities for Blitzortung integration."""

import asyncio
import logging
from typing import Dict, Optional, Tuple
import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Cache for geocoding results to avoid repeated API calls
_geocoding_cache: Dict[Tuple[float, float], Dict] = {}
_max_cache_size = 500

# Rate limiting
_last_request_time = 0
_min_request_interval = 1.0  # 1 second between requests to be nice to Nominatim


class GeocodingService:
    """Service for reverse geocoding using OpenStreetMap Nominatim."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize the geocoding service."""
        self.hass = hass
        self.session = async_get_clientsession(hass)
        
    async def reverse_geocode(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Reverse geocode coordinates to get location information.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            
        Returns:
            Dict with location information or None if failed
        """
        # Round coordinates to reduce cache size (precision to ~100m)
        rounded_coords = (round(latitude, 3), round(longitude, 3))
        
        # Check cache first
        if rounded_coords in _geocoding_cache:
            _LOGGER.debug("Using cached geocoding result for %s", rounded_coords)
            return _geocoding_cache[rounded_coords]
            
        # Rate limiting
        global _last_request_time
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - _last_request_time
        if time_since_last < _min_request_interval:
            await asyncio.sleep(_min_request_interval - time_since_last)
        
        try:
            url = "https://nominatim.openstreetmap.org/reverse"
            params = {
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "addressdetails": 1,
                "zoom": 10,  # City level
                "extratags": 1,
            }
            headers = {
                "User-Agent": "Home Assistant Blitzortung Integration"
            }
            
            _LOGGER.debug("Geocoding request for coordinates: %s, %s", latitude, longitude)
            
            async with self.session.get(url, params=params, headers=headers, timeout=10) as response:
                _last_request_time = asyncio.get_event_loop().time()
                
                if response.status == 200:
                    data = await response.json()
                    location_info = self._parse_nominatim_response(data)
                    
                    # Cache the result
                    self._add_to_cache(rounded_coords, location_info)
                    
                    _LOGGER.debug("Geocoding successful: %s", location_info.get("display_name", "Unknown"))
                    return location_info
                else:
                    _LOGGER.warning("Geocoding request failed with status %s", response.status)
                    return None
                    
        except asyncio.TimeoutError:
            _LOGGER.warning("Geocoding request timed out for coordinates: %s, %s", latitude, longitude)
            return None
        except aiohttp.ClientError as e:
            _LOGGER.warning("Geocoding request failed: %s", e)
            return None
        except Exception as e:
            _LOGGER.error("Unexpected error during geocoding: %s", e)
            return None
    
    def _parse_nominatim_response(self, data: Dict) -> Dict:
        """Parse Nominatim response into standardized format."""
        address = data.get("address", {})
        
        # Extract different address components
        area_parts = []
        
        # Administrative areas (in order of preference)
        admin_levels = [
            "city", "town", "village", "hamlet", "municipality",
            "county", "state_district", "state", "province",
            "country"
        ]
        
        primary_area = None
        secondary_area = None
        country = address.get("country")
        
        # Find the most specific area
        for level in admin_levels:
            if level in address and not primary_area:
                primary_area = address[level]
            elif level in address and not secondary_area and level not in ["country"]:
                secondary_area = address[level]
                
        # Build area description
        if primary_area:
            area_parts.append(primary_area)
        if secondary_area and secondary_area != primary_area:
            area_parts.append(secondary_area)
        if country and country not in area_parts:
            area_parts.append(country)
            
        area_description = ", ".join(area_parts) if area_parts else "Unknown Location"
        
        return {
            "display_name": data.get("display_name", "Unknown Location"),
            "area_description": area_description,
            "primary_area": primary_area or "Unknown",
            "secondary_area": secondary_area,
            "country": country,
            "address_components": address,
            "coordinates": {
                "lat": float(data.get("lat", 0)),
                "lon": float(data.get("lon", 0))
            }
        }
    
    def _add_to_cache(self, coords: Tuple[float, float], location_info: Dict):
        """Add geocoding result to cache with size limit."""
        global _geocoding_cache
        
        if len(_geocoding_cache) >= _max_cache_size:
            # Remove oldest entry (simple FIFO)
            oldest_key = next(iter(_geocoding_cache))
            del _geocoding_cache[oldest_key]
            
        _geocoding_cache[coords] = location_info
    
    def clear_cache(self):
        """Clear the geocoding cache."""
        global _geocoding_cache
        _geocoding_cache.clear()
        _LOGGER.info("Geocoding cache cleared")
