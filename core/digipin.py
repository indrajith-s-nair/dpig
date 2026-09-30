"""
DIGIPIN (Digital Postal Index Number) implementation.
Zero-dependency, compliant with India Post & IIT Hyderabad national addressing grid.
Standard bounds:
Latitude: 2.5° to 38.5° N
Longitude: 63.5° to 99.5° E
4x4 hierarchical grid down to 10 levels of precision (~3.8m x 3.8m).
"""
import math
import re
from typing import Dict, Tuple, Optional, Any

LAT_MIN = 2.5
LAT_MAX = 38.5
LON_MIN = 63.5
LON_MAX = 99.5

DIGIPIN_GRID = [
    ['F', 'C', '9', '8'],
    ['J', '3', '2', '7'],
    ['K', '4', '5', '6'],
    ['L', 'M', 'P', 'T'],
]

CHAR_TO_POS = {}
for r, row in enumerate(DIGIPIN_GRID):
    for c, char in enumerate(row):
        CHAR_TO_POS[char] = (r, c)

VALID_CHARS = set(CHAR_TO_POS.keys())


def is_in_bounds(lat: float, lon: float) -> bool:
    """Check if coordinates fall within India DIGIPIN bounds."""
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def encode(lat: float, lon: float, precision: int = 10) -> str:
    """
    Encode latitude and longitude into a DIGIPIN string.
    Default precision is 10 characters (~3.8m resolution).
    """
    if not (LAT_MIN <= lat <= LAT_MAX):
        # Clamp gracefully or raise if drastically outside
        lat = max(LAT_MIN, min(LAT_MAX, lat))
    if not (LON_MIN <= lon <= LON_MAX):
        lon = max(LON_MIN, min(LON_MAX, lon))

    precision = max(1, min(10, precision))

    curr_lat_min = LAT_MIN
    curr_lat_max = LAT_MAX
    curr_lon_min = LON_MIN
    curr_lon_max = LON_MAX

    chars = []

    for _ in range(precision):
        lat_step = (curr_lat_max - curr_lat_min) / 4.0
        lon_step = (curr_lon_max - curr_lon_min) / 4.0

        # Row 0 is at top (curr_lat_max), Row 3 is at bottom (curr_lat_min)
        if lat >= curr_lat_max:
            row = 0
        else:
            row = int((curr_lat_max - lat) / lat_step)
            if row > 3:
                row = 3
            elif row < 0:
                row = 0

        # Col 0 is at left (curr_lon_min), Col 3 is at right (curr_lon_max)
        if lon >= curr_lon_max:
            col = 3
        else:
            col = int((lon - curr_lon_min) / lon_step)
            if col > 3:
                col = 3
            elif col < 0:
                col = 0

        chars.append(DIGIPIN_GRID[row][col])

        # Narrow bounding box for next level
        sub_lat_max = curr_lat_max - (row * lat_step)
        sub_lat_min = sub_lat_max - lat_step

        sub_lon_min = curr_lon_min + (col * lon_step)
        sub_lon_max = sub_lon_min + lon_step

        curr_lat_min = sub_lat_min
        curr_lat_max = sub_lat_max
        curr_lon_min = sub_lon_min
        curr_lon_max = sub_lon_max

    return "".join(chars)


def format_digipin(code: str) -> str:
    """Format 10-char DIGIPIN into standard readable format: XXX-XXX-XXXX"""
    clean = re.sub(r'[^A-Z0-9]', '', code.upper())
    if len(clean) == 10:
        return f"{clean[0:3]}-{clean[3:6]}-{clean[6:10]}"
    return clean


def decode(code: str) -> Dict[str, Any]:
    """
    Decode a DIGIPIN into center latitude, longitude, and bounding box.
    """
    clean = re.sub(r'[^A-Z0-9]', '', code.upper())
    if not clean:
        raise ValueError("Invalid empty DIGIPIN code")

    curr_lat_min = LAT_MIN
    curr_lat_max = LAT_MAX
    curr_lon_min = LON_MIN
    curr_lon_max = LON_MAX

    for char in clean:
        if char not in CHAR_TO_POS:
            raise ValueError(f"Invalid character '{char}' in DIGIPIN code")

        row, col = CHAR_TO_POS[char]
        lat_step = (curr_lat_max - curr_lat_min) / 4.0
        lon_step = (curr_lon_max - curr_lon_min) / 4.0

        sub_lat_max = curr_lat_max - (row * lat_step)
        sub_lat_min = sub_lat_max - lat_step

        sub_lon_min = curr_lon_min + (col * lon_step)
        sub_lon_max = sub_lon_min + lon_step

        curr_lat_min = sub_lat_min
        curr_lat_max = sub_lat_max
        curr_lon_min = sub_lon_min
        curr_lon_max = sub_lon_max

    center_lat = (curr_lat_min + curr_lat_max) / 2.0
    center_lon = (curr_lon_min + curr_lon_max) / 2.0

    return {
        "latitude": round(center_lat, 6),
        "longitude": round(center_lon, 6),
        "precision_levels": len(clean),
        "bbox": {
            "lat_min": round(curr_lat_min, 6),
            "lat_max": round(curr_lat_max, 6),
            "lon_min": round(curr_lon_min, 6),
            "lon_max": round(curr_lon_max, 6),
        }
    }


def validate_digipin(code: str) -> bool:
    """Validate format and characters of a DIGIPIN code."""
    clean = re.sub(r'[^A-Z0-9]', '', code.upper())
    if len(clean) not in range(1, 11):
        return False
    return all(c in VALID_CHARS for c in clean)


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on the Earth (in meters).
    Used for 350m duplicate clustering as requested in the system flowchart.
    """
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c
