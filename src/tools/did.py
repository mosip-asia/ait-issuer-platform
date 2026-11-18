"""Cryptographic DID Derivation and Keystore Generation for Inji Certify.

Provides functions and CLI commands to:
1. Query a live Certify instance (did.json or jwks.json) to extract its genuine did:key.
2. Extract did:key from an Ed25519 public key or X.509 certificate PEM.
3. Pre-generate a brand-new Ed25519 keypair and package it into a PKCS12 keystore (local.p12).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

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
    # Multicodec prefix for Ed25519 public key is 0xed01
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
            req = urllib.request.Request(target, headers={"User-Agent": "ait-tools-did/1.0"})
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
        req = urllib.request.Request(jwks_url, headers={"User-Agent": "ait-tools-did/1.0"})
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


def extract_from_pem(pem_path: str | Path) -> str:
    """Extract did:key from PEM public key or certificate."""
    pem_path = str(pem_path)
    with open(pem_path, "r", encoding="utf-8") as f:
        content = f.read()

    cmd = ["openssl", "pkey", "-pubin", "-in", pem_path, "-pubout", "-outform", "DER"]
    if "CERTIFICATE" in content:
        p1 = subprocess.run(["openssl", "x509", "-in", pem_path, "-pubkey", "-noout"], capture_output=True, check=True)
        p2 = subprocess.run(["openssl", "pkey", "-pubin", "-pubout", "-outform", "DER"],
                            input=p1.stdout, capture_output=True, check=True)
        der = p2.stdout
    else:
        p = subprocess.run(cmd, capture_output=True, check=True)
        der = p.stdout

    raw_pub = der[-32:]
    return pubkey_to_did_key(raw_pub)


def generate_new_keystore(output_path: str | Path, password: str = "local") -> str:
    """Generate a new Ed25519 keypair and package as PKCS12 keystore."""
    output_path = Path(output_path).resolve()

    # Pre-flight check: ensure parent directory exists and is writable
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise PermissionError(
            f"Cannot create directory '{output_path.parent}': Permission denied. "
            f"If created by Docker, run: sudo chown -R $(id -u):$(id -g) {output_path.parent}"
        ) from e

    if not os.access(output_path.parent, os.W_OK):
        raise PermissionError(
            f"Directory '{output_path.parent}' is not writable by current user (UID {os.getuid()}). "
            f"If created by Docker as root, run: sudo chown -R $(id -u):$(id -g) {output_path.parent}"
        )

    if output_path.exists() and not os.access(output_path, os.W_OK):
        raise PermissionError(
            f"Existing keystore '{output_path}' is not writable by current user (UID {os.getuid()}). "
            f"Run: sudo rm -f {output_path} (or sudo chown $(id -u):$(id -g) {output_path})"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        key_pem = os.path.join(tmpdir, "ed25519-key.pem")
        cert_pem = os.path.join(tmpdir, "ed25519-cert.pem")

        def run_ssl(cmd: list[str], step_name: str) -> subprocess.CompletedProcess:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                err = res.stderr.strip() or res.stdout.strip() or "Unknown error"
                raise RuntimeError(f"OpenSSL failed during {step_name}: {err}")
            return res

        # 1. Generate Ed25519 private key
        run_ssl(["openssl", "genpkey", "-algorithm", "ED25519", "-out", key_pem], "private key generation")

        # 2. Extract public key to compute did:key
        p_pub = subprocess.run(
            ["openssl", "pkey", "-in", key_pem, "-pubout", "-outform", "DER"],
            check=True,
            capture_output=True,
        )
        raw_pub = p_pub.stdout[-32:]
        did_key = pubkey_to_did_key(raw_pub)

        # 3. Create self-signed X.509 certificate (valid 10 years)
        run_ssl(
            [
                "openssl", "req", "-new", "-x509", "-key", key_pem, "-out", cert_pem,
                "-days", "3650", "-subj", "/C=TH/ST=Bangkok/O=AIT/CN=CERTIFY_VC_SIGN_ED25519"
            ],
            "certificate generation",
        )

        # 4. Package as PKCS12 keystore with alias CERTIFY_VC_SIGN_ED25519
        run_ssl(
            [
                "openssl", "pkcs12", "-export", "-in", cert_pem, "-inkey", key_pem,
                "-out", str(output_path), "-name", "CERTIFY_VC_SIGN_ED25519",
                "-passout", f"pass:{password}"
            ],
            "PKCS12 export",
        )

    # Ensure keystore permissions allow Inji Certify (running as container user inji UID 1001) to read it
    try:
        output_path.chmod(0o644)
    except OSError:
        pass

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
