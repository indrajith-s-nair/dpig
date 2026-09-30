"""
Feature Permission Matrix for DPIG:
Allows SuperAdmins to toggle, monitor, and enforce platform subsystems.
Persisted in JSON storage with automatic fallback defaults.
"""
import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'feature_matrix.json')

DEFAULT_FEATURES = {
    'ai_auto_triage': {
        'name': 'AI Auto-Triage & Classification',
        'desc': 'Google Gemini 3.8 Flash language detection, urgency scoring, and automated department routing.',
        'subsystem': 'AI Intelligence',
        'enabled': True,
    },
    'digipin_geocoding': {
        'name': 'India Post DIGIPIN Engine',
        'desc': 'National 4m×4m alphanumeric geospatial grid encoding, decoding, and bounding box validation.',
        'subsystem': 'Spatial Intelligence',
        'enabled': True,
    },
    'duplicate_clustering': {
        'name': 'Spatial Duplicate Clustering',
        'desc': 'PostGIS 350m / 14-day proximity grouping to prevent ticket duplication and officer fatigue.',
        'subsystem': 'Spatial Intelligence',
        'enabled': True,
    },
    'audit_hash_chain': {
        'name': 'Tamper-Evident Audit Hash Chain',
        'desc': 'Cryptographic SHA-256 blockchain-style state transition ledgers and Merkle proofs for every ticket.',
        'subsystem': 'Audit & Governance',
        'enabled': True,
    },
    'sla_escalation_watchdog': {
        'name': 'Automated SLA Breach Watchdog',
        'desc': 'Celery Beat background watchdog monitoring countdowns and triggering multi-tier escalation.',
        'subsystem': 'Case Lifecycle',
        'enabled': True,
    },
    'citizen_notifications': {
        'name': 'Citizen Lifecycle Notifications',
        'desc': 'Automated transactional email and SMS dispatches upon submission, inspection, and resolution.',
        'subsystem': 'Citizen Outcomes',
        'enabled': True,
    },
    'ai_capital_projects': {
        'name': 'Civic Digital Twin Synthesis',
        'desc': 'Synthesizes recurring grievance clusters into prioritized capital infrastructure projects with INR budgets.',
        'subsystem': 'Policy Intelligence',
        'enabled': True,
    },
    'open311_feed': {
        'name': 'Open311 & GeoJSON Public Feeds',
        'desc': 'Publicly queryable GeoJSON endpoint compliant with Open311 municipal data interoperability standards.',
        'subsystem': 'Interoperability',
        'enabled': True,
    },
}


def load_feature_matrix() -> Dict[str, Any]:
    """Loads the feature matrix configuration or returns default configuration."""
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, 'r') as f:
                saved = json.load(f)
                # Merge with defaults in case new keys exist
                config = {}
                for k, v in DEFAULT_FEATURES.items():
                    config[k] = v.copy()
                    if k in saved:
                        config[k]['enabled'] = bool(saved[k].get('enabled', v['enabled']))
                return config
        except Exception as e:
            logger.error("Failed to read feature matrix config: %s", e)
    return DEFAULT_FEATURES.copy()


def save_feature_matrix(config_data: Dict[str, bool]) -> Dict[str, Any]:
    """Updates feature matrix toggles and persists to disk atomically."""
    os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
    current = load_feature_matrix()
    for key, enabled in config_data.items():
        if key in current:
            current[key]['enabled'] = bool(enabled)
    try:
        with open(CONFIG_FILE_PATH, 'w') as f:
            json.dump(current, f, indent=2)
    except Exception as e:
        logger.error("Failed to save feature matrix: %s", e)
    return current


def is_feature_enabled(feature_key: str) -> bool:
    """Check if a specific feature is enabled."""
    matrix = load_feature_matrix()
    feat = matrix.get(feature_key)
    return feat['enabled'] if feat else True
