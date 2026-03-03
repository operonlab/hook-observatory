#!/usr/bin/env python3
"""Generate VAPID key pair for Web Push notifications.

Stores keys at ~/.workshop/vapid/private_key.pem and public_key.txt.
Add to .env:
  CORE_VAPID_PRIVATE_KEY=~/.workshop/vapid/private_key.pem
  CORE_VAPID_PUBLIC_KEY=<contents of public_key.txt>
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

VAPID_DIR = Path.home() / ".workshop" / "vapid"


def main():
    if (VAPID_DIR / "private_key.pem").exists():
        print(f"VAPID keys already exist at {VAPID_DIR}")
        print("Delete them first if you want to regenerate.")
        sys.exit(1)

    VAPID_DIR.mkdir(parents=True, exist_ok=True)

    # Generate ECDSA P-256 key pair (required by Web Push / VAPID)
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Save private key (PEM)
    pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    (VAPID_DIR / "private_key.pem").write_bytes(pem)
    (VAPID_DIR / "private_key.pem").chmod(0o600)

    # Save public key (uncompressed point, base64url for applicationServerKey)
    import base64

    pub_bytes = private_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
    (VAPID_DIR / "public_key.txt").write_text(pub_b64)

    print(f"VAPID keys generated at {VAPID_DIR}")
    print(f"Public key (applicationServerKey): {pub_b64}")
    print()
    print("Add to your .env:")
    print(f'  CORE_VAPID_PRIVATE_KEY="{VAPID_DIR / "private_key.pem"}"')
    print(f'  CORE_VAPID_PUBLIC_KEY="{pub_b64}"')
    print('  CORE_VAPID_CONTACT="mailto:admin@joneshong.com"')


if __name__ == "__main__":
    main()
