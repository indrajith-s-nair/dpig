"""
Geo-spatial service for resolving Administrative Ward and Zone from
Geographic Coordinates (latitude, longitude) and India Post DIGIPIN.
"""
import logging
from typing import Optional, Dict, Any, Tuple
from core.digipin import decode as decode_digipin, validate_digipin, format_digipin, haversine_distance_meters

logger = logging.getLogger(__name__)


def resolve_ward_from_location(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    digipin: Optional[str] = None,
    cluster=None
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """
    Given (lat, lon) or a DIGIPIN code, determines the exact administrative Ward and Zone.

    Matching hierarchy:
    1. If a DIGIPIN is available, check for matching Ward digipin_prefix (e.g. 4-6 chars).
    2. Otherwise or as fallback, compute Haversine distance to all Ward centroids in the cluster
       and select the closest Ward.

    Returns:
        (Ward instance or None, payload dict with ward & zone details)
    """
    from core.models import Ward, Cluster

    if not cluster:
        cluster = Cluster.objects.filter(is_active=True).first()

    clean_digi = ''.join(c for c in (digipin or '') if c.isalnum()).upper()

    # If coordinates are missing, decode from DIGIPIN
    if (lat is None or lon is None) and clean_digi:
        try:
            dec = decode_digipin(clean_digi)
            lat = dec['latitude']
            lon = dec['longitude']
        except Exception as e:
            logger.debug("Failed to decode DIGIPIN %s: %s", clean_digi, e)

    if lat is None or lon is None:
        return None, {}

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None, {}

    wards_qs = Ward.objects.select_related('zone')
    if cluster:
        wards_qs = wards_qs.filter(zone__cluster=cluster)
    wards = list(wards_qs)

    if not wards:
        return None, {}

    # 1. Prefix match against Ward digipin_prefix
    if clean_digi and len(clean_digi) >= 4:
        for w in wards:
            pfx = (w.digipin_prefix or '').replace('-', '').upper()
            if pfx and clean_digi.startswith(pfx):
                return w, {
                    'match_type': 'DIGIPIN_PREFIX',
                    'ward_id': w.id,
                    'ward_number': w.number,
                    'ward_name': w.name,
                    'zone_id': w.zone.id,
                    'zone_number': w.zone.number,
                    'zone_name': w.zone.name,
                    'display_label': f"{w.name} (Zone {w.zone.number})",
                    'distance_meters': 0,
                    'latitude': lat,
                    'longitude': lon,
                }

    # 2. Nearest Centroid Distance via Haversine (with bounding box candidate pruning)
    best_ward = None
    min_dist = float('inf')

    # Prune candidates to nearby wards within ~15km bounding box, fallback to all wards
    candidates = [
        w for w in wards
        if abs(w.centroid_lat - lat) <= 0.15 and abs(w.centroid_lng - lon) <= 0.15
    ] or wards

    for w in candidates:
        d = haversine_distance_meters(lat, lon, w.centroid_lat, w.centroid_lng)
        if d < min_dist:
            min_dist = d
            best_ward = w

    if best_ward:
        return best_ward, {
            'match_type': 'GEOSPATIAL_CENTROID',
            'ward_id': best_ward.id,
            'ward_number': best_ward.number,
            'ward_name': best_ward.name,
            'zone_id': best_ward.zone.id,
            'zone_number': best_ward.zone.number,
            'zone_name': best_ward.zone.name,
            'display_label': f"{best_ward.name} (Zone {best_ward.zone.number})",
            'distance_meters': round(min_dist, 1),
            'distance_km': round(min_dist / 1000.0, 2),
            'latitude': lat,
            'longitude': lon,
        }

    return None, {}
