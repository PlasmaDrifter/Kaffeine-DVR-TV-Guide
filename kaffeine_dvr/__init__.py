"""
Kaffeine DVR & TV Guide Package.

Provides modern TV Guide scheduling, automated rules-based recording,
and just-in-time recording management for Kaffeine DVB.
"""

__version__ = "0.9.0"


def setup_ssl_certificates():
    """
    Ensure SSL_CERT_FILE and OpenSSL default contexts point to valid CA certificates
    across all Linux distributions (Ubuntu, Debian, Fedora, Arch, openSUSE, etc.)
    and standalone AppImage environments.
    """
    import os
    import ssl
    import sys
    from pathlib import Path

    ca_candidates = [
        "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Kubuntu, Mint
        "/etc/pki/tls/certs/ca-bundle.crt",                  # Fedora, RHEL, CentOS
        "/etc/ssl/ca-bundle.pem",                             # openSUSE
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Nobara, modern Fedora
        "/etc/ca-certificates/extracted/tls-ca-bundle.pem",   # Arch, Manjaro
        "/etc/ssl/cert.pem",                                  # Alpine, BSD, macOS
    ]

    # Check AppImage runtime path
    appdir = os.environ.get("APPDIR")
    if appdir:
        ca_candidates.append(f"{appdir}/usr/share/kaffeine-dvr/cacert.pem")
        ca_candidates.append(f"{appdir}/usr/bin/assets/cacert.pem")
        ca_candidates.append(f"{appdir}/usr/bin/cacert.pem")

    # Check PyInstaller bundle directory
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = getattr(sys, "_MEIPASS")
        ca_candidates.append(f"{meipass}/assets/cacert.pem")
        ca_candidates.append(f"{meipass}/cacert.pem")

    # Local package source fallback
    here = Path(__file__).resolve().parent
    ca_candidates.append(str(here.parent / "assets" / "cacert.pem"))
    ca_candidates.append(str(here / "assets" / "cacert.pem"))

    valid_ca = None
    env_ca = os.environ.get("SSL_CERT_FILE")
    if env_ca and Path(env_ca).is_file():
        valid_ca = env_ca
    else:
        for cand in ca_candidates:
            if cand and Path(cand).is_file():
                valid_ca = cand
                os.environ["SSL_CERT_FILE"] = cand
                break

    if not os.environ.get("SSL_CERT_DIR") or not Path(os.environ["SSL_CERT_DIR"]).is_dir():
        for d in ["/etc/ssl/certs", "/etc/pki/tls/certs", "/system/etc/security/cacerts"]:
            if Path(d).is_dir():
                os.environ["SSL_CERT_DIR"] = d
                break

    if valid_ca:
        orig_create = ssl.create_default_context

        def _safe_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None, capath=None, cadata=None):
            if cafile is None and capath is None and cadata is None:
                try:
                    return orig_create(purpose=purpose, cafile=valid_ca)
                except Exception:
                    pass
            return orig_create(purpose=purpose, cafile=cafile, capath=capath, cadata=cadata)

        ssl.create_default_context = _safe_create_default_context
        ssl._create_default_https_context = _safe_create_default_context


setup_ssl_certificates()

