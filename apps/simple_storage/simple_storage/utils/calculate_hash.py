import hashlib


def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
