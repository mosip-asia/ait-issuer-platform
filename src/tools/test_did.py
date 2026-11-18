"""Unit tests for tools.did module."""

import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from did import generate_new_keystore, pubkey_to_did_key, extract_from_pem, extract_from_p12


def test_pubkey_to_did_key_known_vector():
    """Verify conversion of raw public key to did:key against known test vector."""
    # Known public key from AIT dev keystore (base64url from JWKS OKP key)
    x = "MrRueEByiXyJAPUT4pPGyg8qnDV8dLyzEwd8UD_8kv0"
    pad = len(x) % 4
    if pad:
        x += "=" * (4 - pad)
    raw_pub = base64.urlsafe_b64decode(x)
    did = pubkey_to_did_key(raw_pub)
    assert did == "did:key:z6MkhsC1EojKdBoLzPY2kL2mFLSMJbQVC83M2CsnYGwghcsE"
    print("PASS test_pubkey_to_did_key_known_vector")


def test_generate_new_keystore_and_pem_extraction():
    """Verify generating a keystore produces valid did:key and PKCS12 file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p12_path = Path(tmpdir) / "test_keystore.p12"
        did = generate_new_keystore(p12_path, password="secret")

        assert p12_path.exists()
        assert p12_path.stat().st_size > 0
        assert (p12_path.stat().st_mode & 0o777) == 0o644
        assert did.startswith("did:key:z6Mk")

        # Verify extract_from_p12 extracts the exact same did:key
        did_from_p12 = extract_from_p12(p12_path, password="secret")
        assert did_from_p12 == did
        print("PASS test_generate_new_keystore_and_pem_extraction")


if __name__ == "__main__":
    test_pubkey_to_did_key_known_vector()
    test_generate_new_keystore_and_pem_extraction()
    print("All did tests passed.")
