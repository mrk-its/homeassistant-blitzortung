PLATFORMS = ["sensor"]

DOMAIN = "blitzortung"
DATA_UNSUBSCRIBE = "unsubscribe"
ATTR_LIGHTNING_DISTANCE = "distance"
ATTR_LIGHTNING_AZIMUTH = "azimuth"
ATTR_LIGHTNING_COUNTER = "counter"
BASE_URL_TEMPLATE = "http://data{data_host_nr}.blitzortung.org/Data/Protected/last_strikes.php"

CONF_RADIUS = "radius"
INACTIVITY_RESET_SECONDS = 3600
