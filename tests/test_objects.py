import os
import random
import pytest
from aerocore.objects import ObjectStore, NullCipher, StreamCipher


def _blob(n, seed=1):
    return random.Random(seed).randbytes(n)


def test_roundtrip_various_sizes(tmp_path):
    with ObjectStore(tmp_path, "tickets") as s:
        for size in (0, 1, 3999, 4000, 4001, 12345, 200_000):
            data = _blob(size, size)
            s.put(f"ticket:{size}", data, "application/pdf")
            assert s.get(f"ticket:{size}") == data
        assert s.info("ticket:200000")["size"] == 200_000
        assert s.info("ticket:200000")["content_type"] == "application/pdf"


def test_replace_delete_exists_and_list(tmp_path):
    with ObjectStore(tmp_path, "tickets") as s:
        s.put("ticket:1", b"old")
        s.put("ticket:1", b"new version")
        assert s.get("ticket:1") == b"new version"
        s.put("ticket:2", b"b"); s.put("manifest:7", b"m")
        assert s.list("ticket:") == ["ticket:1", "ticket:2"]
        assert s.list() == ["manifest:7", "ticket:1", "ticket:2"]
        assert s.delete("ticket:1") is True and s.delete("ticket:1") is False
        assert not s.exists("ticket:1") and s.exists("ticket:2")
        with pytest.raises(KeyError):
            s.get("ticket:1")


def test_persistence_after_reopen(tmp_path):
    data = _blob(50_000)
    s = ObjectStore(tmp_path, "tickets")
    s.put("manifest:flight-12", data)
    s.close()
    s = ObjectStore(tmp_path, "tickets")
    assert s.get("manifest:flight-12") == data
    s.close()


def test_many_objects(tmp_path):
    with ObjectStore(tmp_path, "tickets", capacity=8) as s:
        blobs = {f"ticket:{i}": _blob(500 + i, i) for i in range(300)}
        for k, v in blobs.items():
            s.put(k, v)
        for k in random.Random(5).sample(sorted(blobs), 50):
            assert s.get(k) == blobs[k]
        assert len(s.list("ticket:")) == 300


def test_encryption_hook_roundtrip_and_ciphertext_on_disk(tmp_path):
    secret = b"PASSENGER=Farah Ahmed;SEAT=12A;" * 20
    s = ObjectStore(tmp_path, "enc", cipher=StreamCipher("correct horse"))
    s.put("ticket:1", secret)
    assert s.get("ticket:1") == secret
    s.close()
    raw = (tmp_path / "enc.objects").read_bytes()
    assert b"PASSENGER" not in raw and b"Farah" not in raw      # only ciphertext reaches the file
    s = ObjectStore(tmp_path, "enc", cipher=StreamCipher("correct horse"))
    assert s.get("ticket:1") == secret
    s.close()


def test_wrong_key_wrong_cipher_and_tampering_are_detected(tmp_path):
    s = ObjectStore(tmp_path, "enc", cipher=StreamCipher("k1"))
    s.put("t", b"hello world" * 50)
    s.close()
    s = ObjectStore(tmp_path, "enc", cipher=StreamCipher("k2"))
    with pytest.raises(ValueError):
        s.get("t")                                             # wrong key: HMAC fails
    s.close()
    s = ObjectStore(tmp_path, "enc", cipher=NullCipher())
    with pytest.raises(ValueError):
        s.get("t")                                             # stored encrypted, store has no cipher
    s.close()
    c = StreamCipher("k")
    blob = bytearray(c.encrypt(b"abc" * 100))
    blob[20] ^= 1
    with pytest.raises(ValueError):
        c.decrypt(bytes(blob))


def test_limits_and_validation(tmp_path):
    with ObjectStore(tmp_path, "x") as s:
        with pytest.raises(ValueError):
            s.put("big", b"x" * 1_000_001)
        with pytest.raises(ValueError):
            s.put("", b"x")