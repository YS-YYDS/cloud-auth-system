import hmac
import hashlib
import base64
import json
from typing import Optional
from .config import HMAC_SECRET_KEY, XOR_SALT

def derive_session_key(license_key: str, product_id: str) -> str:
    """LDK: 基于 license_key 和 product_id 派生会话 HMAC 密钥 (一人一码一钢印)"""
    return hmac.new(
        license_key.encode("utf-8"),
        product_id.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:32]

def encrypt_response(data: dict, device_id: str, dyn_armor_key: Optional[str] = None) -> dict:
    """
    1. 对原始 JSON 数据计算 HMAC 签名并注入 data。
    2. XOR 混淆 (防抓包): 
       v2.0: key = device_id[:8] + dyn_armor_key[:16]
       v1.0: key = device_id[:8] + XOR_SALT (全局盐)
    """
    json_payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sign_key = dyn_armor_key if dyn_armor_key else HMAC_SECRET_KEY

    signature = hmac.new(
        (sign_key or "").encode("utf-8"),
        json_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    data["signature"] = signature

    json_str = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    # [P0-FIX] XOR 盐值派生策略 (v2.0 协议):
    # 安全加固：确保 dyn_armor_key 有效且长度足够，否则强制使用全局 XOR_SALT
    xor_salt = dyn_armor_key[:16] if (dyn_armor_key and len(dyn_armor_key) >= 16) else XOR_SALT
    dyn_key = (device_id[:8] + xor_salt) if device_id else xor_salt
    key = dyn_key.encode("utf-8")
    
    encrypted = bytearray(b ^ key[i % len(key)] for i, b in enumerate(json_str.encode("utf-8")))
    b64_str = base64.b64encode(encrypted).decode("utf-8")
    return {"payload": b64_str}
