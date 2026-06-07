"""Static reference data for accounts: countries, timezones, coordinates.

django-countries is not a dependency, so we keep a curated list of the markets
FlockIQ serves (West Africa first) plus the major global markets. Keep the three
maps below in sync — every country in COUNTRY_CHOICES should have a timezone and
a representative set of coordinates.
"""

# Display order: West/East Africa first, then major global markets.
COUNTRY_CHOICES = (
    ("Nigeria", "Nigeria"),
    ("Ghana", "Ghana"),
    ("Kenya", "Kenya"),
    ("South Africa", "South Africa"),
    ("Côte d'Ivoire", "Côte d'Ivoire"),
    ("Senegal", "Senegal"),
    ("Tanzania", "Tanzania"),
    ("Uganda", "Uganda"),
    ("Rwanda", "Rwanda"),
    ("Ethiopia", "Ethiopia"),
    ("Cameroon", "Cameroon"),
    ("United Kingdom", "United Kingdom"),
    ("United States", "United States"),
    ("Canada", "Canada"),
    ("Australia", "Australia"),
    ("India", "India"),
    ("France", "France"),
    ("Germany", "Germany"),
    ("Netherlands", "Netherlands"),
    ("UAE", "United Arab Emirates"),
)

# IANA timezone per country (single representative zone).
COUNTRY_TIMEZONE_MAP = {
    "Nigeria": "Africa/Lagos",
    "Ghana": "Africa/Accra",
    "Kenya": "Africa/Nairobi",
    "South Africa": "Africa/Johannesburg",
    "Côte d'Ivoire": "Africa/Abidjan",
    "Senegal": "Africa/Dakar",
    "Tanzania": "Africa/Dar_es_Salaam",
    "Uganda": "Africa/Kampala",
    "Rwanda": "Africa/Kigali",
    "Ethiopia": "Africa/Addis_Ababa",
    "Cameroon": "Africa/Douala",
    "United Kingdom": "Europe/London",
    "United States": "America/New_York",
    "Canada": "America/Toronto",
    "Australia": "Australia/Sydney",
    "India": "Asia/Kolkata",
    "France": "Europe/Paris",
    "Germany": "Europe/Berlin",
    "Netherlands": "Europe/Amsterdam",
    "UAE": "Asia/Dubai",
}

# Representative (lat, lng) per country — used as a default weather location when a
# user has no farm with GPS coordinates set. Picked for the main poultry/commercial
# hub rather than always the political capital.
COUNTRY_COORDINATES = {
    "Nigeria": (6.5244, 3.3792),        # Lagos
    "Ghana": (5.6037, -0.1870),         # Accra
    "Kenya": (-1.2921, 36.8219),        # Nairobi
    "South Africa": (-26.2041, 28.0473),  # Johannesburg
    "Côte d'Ivoire": (5.3600, -4.0083),   # Abidjan
    "Senegal": (14.7167, -17.4677),     # Dakar
    "Tanzania": (-6.7924, 39.2083),     # Dar es Salaam
    "Uganda": (0.3476, 32.5825),        # Kampala
    "Rwanda": (-1.9706, 30.1044),       # Kigali
    "Ethiopia": (9.0300, 38.7400),      # Addis Ababa
    "Cameroon": (4.0511, 9.7679),       # Douala
    "United Kingdom": (51.5074, -0.1278),  # London
    "United States": (40.7128, -74.0060),  # New York
    "Canada": (43.6532, -79.3832),      # Toronto
    "Australia": (-33.8688, 151.2093),  # Sydney
    "India": (19.0760, 72.8777),        # Mumbai
    "France": (48.8566, 2.3522),        # Paris
    "Germany": (52.5200, 13.4050),      # Berlin
    "Netherlands": (52.3676, 4.9041),   # Amsterdam
    "UAE": (25.2048, 55.2708),          # Dubai
}

DEFAULT_TIMEZONE = "UTC"


def timezone_for_country(country: str) -> str:
    """Return the IANA timezone for a country name, falling back to UTC."""
    return COUNTRY_TIMEZONE_MAP.get(country, DEFAULT_TIMEZONE)


def coordinates_for_country(country: str):
    """Return (lat, lng) for a country name, or None if unknown."""
    return COUNTRY_COORDINATES.get(country)
