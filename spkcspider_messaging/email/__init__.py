import os
import ssl
import asyncio
from datetime import datetime as dt, timedelta as td

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from aiosmtpd.smtp import SMTP

from .cmd import parser
from .base import Email2SpiderHandler, load_priv_key


def main(argv):
    argv = parser.parse_args(argv)
    argv.cert = getattr(
        argv, "cert", "%s.cert" % argv.keys[0].rsplit(".", 1)[0]
    )
    argv.hash = getattr(hashes, argv.hash)()
    cert = None
    if not os.path.exists(argv.keys[0]) and not argv.no_gen:
        pkey = rsa.generate_private_key(
            public_exponent=65537,
            key_size=argv.keysize,
            backend=default_backend()
        )
        with open(argv.keys[0], "wb") as f:
            f.write(
                pkey.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        subject = x509.Name(
            [
                x509.NameAttribute(
                    NameOID.ORGANIZATION_NAME, "spkcspider"
                ),
                x509.NameAttribute(
                    NameOID.COMMON_NAME, argv.address
                ),
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(pkey.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.utcnow())
            .not_valid_after(dt.utcnow() + td(days=365*20))
        )
        # cert = cert.add_extension(
        #    x509.SubjectAlternativeName([x509.DNSName("localhost")]),
        #    critical=False
        # )

        cert = cert.sign(pkey, hashes.SHA512(), default_backend())
        del pkey

        pkey_file = argv.keys[0].rsplit(".", 1)[0]
        with open(pkey_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
    if not all(map(os.path.exists, argv.keys)):
        argv.exit(1, "invalid keys")
    keylist = {}
    pw = None
    for num, key_path in enumerate(argv.keys):
        data = None
        pkey = None
        with open(key_path, "rb") as f:
            if num == 0:
                pkey, pw = load_priv_key(f.read())
            else:
                pkey = load_priv_key(f.read())[0]

            if not pkey:
                argv.exit(1, "invalid key: %s" % key_path)
            pem_public = pkey.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            digest = hashes.Hash(argv.hash, backend=default_backend())
            digest.update(pem_public)
            keylist[digest.finalize().hex()] = pkey
        del data
        del pkey
    ctx = None
    if os.path.exists(argv.cert):
        ctx = ssl.SSLContext()
        try:
            ctx.load_cert_chain(argv.cert, argv.keys[0], pw)
        except ssl.SSLError:
            ctx = None

    loop = asyncio.new_event_loop()
    SMTP(
        Email2SpiderHandler(),
        hostname=":".join([argv.address, str(argv.port)]),
        tls_context=ctx,
        require_starttls=not argv.unencrypted,
        loop=loop
    )
    print("started")
    loop.run_forever()
