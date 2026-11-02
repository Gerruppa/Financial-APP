"""What the sources tell the user when a download fails without an HTTP status: a missing connection, or a server
certificate Windows does not trust (issue #309), which no check of the connection fixes."""

import ssl
from urllib.error import URLError

CONNECTION_HINT = "Sprawdź połączenie z internetem."
CERTIFICATE_HINT = (
    "Windows nie ufa certyfikatowi bezpieczeństwa tej strony; sprawdź datę i godzinę komputera "
    "oraz czy program antywirusowy nie skanuje połączeń HTTPS."
)


def network_hint(error: OSError) -> str:
    """The Polish advice for ``error``, raised by urlopen itself or by urllib wrapped in a URLError."""
    wrapped = isinstance(error, URLError) and isinstance(error.reason, ssl.SSLCertVerificationError)
    if wrapped or isinstance(error, ssl.SSLCertVerificationError):
        return CERTIFICATE_HINT
    return CONNECTION_HINT
