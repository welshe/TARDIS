import hashlib, json

def stable_hash(obj) -> str:
    try:
        s = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode()).hexdigest()[:16]
