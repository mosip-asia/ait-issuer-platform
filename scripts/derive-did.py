#!/usr/bin/env python3
"""
Derive or Generate did:key Identifiers for Inji Certify
======================================================
Utility to derive the canonical W3C did:key identifier for Inji Certify,
either by querying a running Certify instance, reading an existing Ed25519
public key / certificate, or generating a fresh PKCS12 keystore.

Usage:
    # 1. Query running Certify instance:
    python3 scripts/derive-did.py https://issuer-dev.ait-vc.dpi.ait.ac.th
    python3 scripts/derive-did.py http://localhost:9091

    # 2. Extract did:key from an Ed25519 public key or certificate PEM:
    python3 scripts/derive-did.py --pem path/to/public-key.pem

    # 3. Generate a brand new Ed25519 keypair and PKCS12 keystore (local.p12):
    python3 scripts/derive-did.py --generate deploy/ait/private_key/CERTIFY_PKCS12/local.p12
"""

import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    """Encode bytes using Base58btc (Bitcoin alphabet)."""
    n = int.from_bytes(b, "big")
    chars = []
    while n > 0:
        n, r = divmod(n, 58)
        chars.append(ALPHABET[r])
    for byte in b:
        if byte == 0:
            chars.append(ALPHABET[0])
        else:
            break
    return "".join(reversed(chars))


def pubkey_to_did_key(raw_pubkey_32_bytes: bytes) -> str:
    """Convert raw 32-byte Ed25519 public key into W3C did:key string."""
    if len(raw_pubkey_32_bytes) != 32:
        raise ValueError(f"Expected 32 bytes for Ed25519 public key, got {len(raw_pubkey_32_bytes)}")
    # Multicodec prefix for Ed25519 public key is 0xed01 (0xed, 0x01)
    multicodec = b"\xed\x01" + raw_pubkey_32_bytes
    return "did:key:z" + b58encode(multicodec)


def query_running_certify(url: str) -> str:
    """Fetch did:key from running Certify endpoint."""
    url = url.rstrip("/")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Try .well-known/did.json first
    did_urls = [
        f"{url}/.well-known/did.json",
        f"{url}/v1/certify/.well-known/did.json",
    ]
    for target in did_urls:
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "derive-did/1.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                methods = data.get("verificationMethod", [])
                for m in methods:
                    pub_multi = m.get("publicKeyMultibase")
                    if pub_multi:
                        return f"did:key:{pub_multi}"
        except Exception:
            continue

    # Fallback to JWKS endpoint
    jwks_url = f"{url}/v1/certify/.well-known/jwks.json"
    try:
        req = urllib.request.Request(jwks_url, headers={"User-Agent": "derive-did/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for k in data.get("keys", []):
                if k.get("kty") == "OKP" and k.get("crv") == "Ed25519":
                    x = k.get("x", "")
                    pad = len(x) % 4
                    if pad:
                        x += "=" * (4 - pad)
                    raw_pub = base64.urlsafe_b64decode(x)
                    return pubkey_to_did_key(raw_pub)
    except Exception as e:
        raise RuntimeError(f"Could not connect or fetch keys from {url}: {e}")

    raise RuntimeError(f"No Ed25519 signing key found at {url}")


def extract_from_pem(pem_path: str) -> str:
    """Extract did:key from PEM public key or certificate."""
    with open(pem_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Use openssl to extract raw public key bytes
    cmd = ["openssl", "pkey", "-pubin", "-in", pem_path, "-pubout", "-outform", "DER"]
    # If it's an X.509 certificate
    if "CERTIFICATE" in content:
        cmd = ["openssl", "x509", "-in", pem_path, "-pubkey", "-noout"]
        p1 = subprocess.run(cmd, capture_output=True, check=True)
        p2 = subprocess.run(["openssl", "pkey", "-pubin", "-pubout", "-outform", "DER"],
                            input=p1.stdout, capture_output=True, check=True)
        der = p2.stdout
    else:
        p = subprocess.run(cmd, capture_output=True, check=True)
        der = p.stdout

    # Ed25519 SubjectPublicKeyInfo is 44 bytes: 12-byte header + 32-byte raw key
    raw_pub = der[-32:]
    return pubkey_to_did_key(raw_pub)


def generate_new_keystore(output_path: str, password: str = "local") -> str:
    """Generate a new Ed25519 keypair and package as PKCS12 keystore."""
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        key_pem = os.path.join(tmpdir, "ed25519-key.pem")
        cert_pem = os.path.join(tmpdir, "ed25519-cert.pem")

        # 1. Generate Ed25519 private key
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", key_pem],
            check=True,
            capture_output=True,
        )

        # 2. Extract public key to compute did:key
        p_pub = subprocess.run(
            ["openssl", "pkey", "-in", key_pem, "-pubout", "-outform", "DER"],
            check=True,
            capture_output=True,
        )
        raw_pub = p_pub.stdout[-32:]
        did_key = pubkey_to_did_key(raw_pub)

        # 3. Create self-signed X.509 certificate (valid 10 years)
        subprocess.run(
            [
                "openssl", "req", "-new", "-x509", "-key", key_pem, "-out", cert_pem,
                "-days", "3650", "-subj", "/C=TH/ST=Bangkok/O=AIT/CN=CERTIFY_VC_SIGN_ED25519"
            ],
            check=True,
            capture_output=True,
        )

        # 4. Package as PKCS12 keystore with alias CERTIFY_VC_SIGN_ED25519
        subprocess.run(
            [
                "openssl", "pkcs12", "-export", "-in", cert_pem, "-inkey", key_pem,
                "-out", output_path, "-name", "CERTIFY_VC_SIGN_ED25519",
                "-passout", f"pass:{password}"
            ],
            check=True,
            capture_output=True,
        )

    return did_key


def main():
    parser = argparse.ArgumentParser(
        description="Derive or generate did:key identifiers for Inji Certify"
    )
    parser.add_argument("target", nargs="?", default="", help="Certify URL (e.g. http://localhost:9091)")
    parser.add_argument("--pem", help="Path to PEM public key or certificate file")
    parser.add_argument("--generate", help="Output path to generate a new PKCS12 keystore (e.g. deploy/ait/private_key/CERTIFY_PKCS12/local.p12)")
    parser.add_argument("--password", default="local", help="Keystore password (default: local)")

    args = parser.parse_args()

    if args.generate:
        print(f"Generating new Ed25519 keypair and PKCS12 keystore at: {args.generate}...")
        did = generate_new_keystore(args.generate, args.password)
        print(f"\n[OK] Keystore successfully created at: {args.generate}")
        print(f"     Keystore Password: {args.password}")
        print(f"     Derived CERTIFY_DID: {did}\n")
        print("Configure this value in your .env file:")
        print(f"  CERTIFY_DID={did}")
        return

    if args.pem:
        did = extract_from_pem(args.pem)
        print(did)
        return

    if args.target:
        did = query_running_certify(args.target)
        print(did)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
