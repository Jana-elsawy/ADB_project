"""Encryption extension point for object storage (M2).

ObjectStore calls cipher.encrypt(bytes) before writing and cipher.decrypt(bytes)
after reading. Any class with those two methods and a `name` can be plugged in.

  NullCipher    : identity (default, no encryption)
  StreamCipher  : demo cipher built only from the standard library:
                  SHA-256 counter-mode keystream + HMAC-SHA256 tag (encrypt-then-MAC).
                  It shows the hook working end to end and detects tampering or a
                  wrong key. It is a teaching implementation: for real deployments
                  replace it with an audited AEAD such as AES-GCM (an adapter with
                  the same two methods is enough).
"""
import hashlib
import hmac
import os

NONCE_LEN, TAG_LEN = 16, 32


class Cipher:
    name = "abstract"

    def encrypt(self, data: bytes) -> bytes:
        raise NotImplementedError

    def decrypt(self, data: bytes) -> bytes:
        raise NotImplementedError


class NullCipher(Cipher):
    name = "none"

    def encrypt(self, data):
        return bytes(data)

    def decrypt(self, data):
        return bytes(data)


class StreamCipher(Cipher):
    name = "stream-sha256-hmac"

    def __init__(self, key):
        key = key.encode("utf-8") if isinstance(key, str) else bytes(key)
        if not key:
            raise ValueError("key must not be empty")
        self._enc_key = hashlib.sha256(b"enc" + key).digest()
        self._mac_key = hashlib.sha256(b"mac" + key).digest()

    def _keystream(self, nonce, n):
        out, counter = bytearray(), 0
        while len(out) < n:
            out += hashlib.sha256(self._enc_key + nonce + counter.to_bytes(8, "big")).digest()
            counter += 1
        return bytes(out[:n])

    @staticmethod
    def _xor(a, b):
        if not a:
            return b""
        return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")

    def encrypt(self, data):
        data = bytes(data)
        nonce = os.urandom(NONCE_LEN)
        ct = self._xor(data, self._keystream(nonce, len(data)))
        tag = hmac.new(self._mac_key, nonce + ct, hashlib.sha256).digest()
        return nonce + ct + tag

    def decrypt(self, data):
        data = bytes(data)
        if len(data) < NONCE_LEN + TAG_LEN:
            raise ValueError("ciphertext too short")
        nonce, ct, tag = data[:NONCE_LEN], data[NONCE_LEN:-TAG_LEN], data[-TAG_LEN:]
        good = hmac.new(self._mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, good):
            raise ValueError("authentication failed: wrong key or corrupted data")
        return self._xor(ct, self._keystream(nonce, len(ct)))