import hashlib
import json


def stable_hash(obj) -> str:
    """Content-addressed hash (16 hex chars). Good for dedup/change detection."""
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def secure_hash(obj) -> str:
    """Full-strength SHA-256 hash (64 hex chars). Use for security-sensitive hashing."""
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode()).hexdigest()
