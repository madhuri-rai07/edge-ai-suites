#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Generates a local root CA + a leaf cert for 127.0.0.1/localhost.

This simulates approach (b) from the design doc, section 3.1.1:
"Pre-installed local root CA (Docker Desktop's approach): install a private
root CA into the OS/browser trust store during OXM imaging or OEP Installer
setup; Device Agent presents a cert signed by that CA for `localhost`."

Output (in ./pki/):
  ca.key, ca.crt        - the "pre-installed" root CA (client trusts this)
  agent.key, agent.crt  - Device Agent's loopback TLS cert, signed by ca.crt
"""
import datetime
import ipaddress
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT_DIR = os.path.join(os.path.dirname(__file__), "pki")
os.makedirs(OUT_DIR, exist_ok=True)


def _write_key(path, key):
    with open(path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )


def _write_cert(path, cert):
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def main():
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Root CA — represents the cert "pre-installed into the OS/browser
    #    trust store during OXM imaging or OEP Installer setup".
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Edge AI Catalog - Local Device Agent Root CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(os.path.join(OUT_DIR, "ca.key"), ca_key)
    _write_cert(os.path.join(OUT_DIR, "ca.crt"), ca_cert)

    # 2. Leaf cert for the Device Agent's loopback HTTPS listener.
    agent_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agent_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]
    )
    agent_cert = (
        x509.CertificateBuilder()
        .subject_name(agent_name)
        .issuer_name(ca_name)
        .public_key(agent_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(os.path.join(OUT_DIR, "agent.key"), agent_key)
    _write_cert(os.path.join(OUT_DIR, "agent.crt"), agent_cert)

    print(f"Wrote CA + Device Agent cert/key to {OUT_DIR}/")


if __name__ == "__main__":
    main()
