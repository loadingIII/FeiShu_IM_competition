import hashlib


def get_md5(text: str) -> str:
    """获取文本的 MD5 值"""
    md5_hash = hashlib.md5(text.encode('utf-8'))
    return md5_hash.hexdigest()