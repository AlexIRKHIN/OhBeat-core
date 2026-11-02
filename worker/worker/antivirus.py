"""Mock antivirus for the ZIP with stems (FR-9, ADR 0006).

Finds:
* the standard EICAR test string — what real antiviruses use for testing;
* our own test marker. Sample files on the host use it instead of EICAR, otherwise
  the antivirus of the developer's computer would quarantine them.

ANTIVIRUS_MODE=unavailable makes every scan fail as if the scanner were down:
a temporary error that shows retries and the DLQ.
"""

from worker.errors import TransientError

# Assembled from parts so this source file itself does not look like the test virus
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
OHBEAT_TEST_SIGNATURE = b"OHBEAT-ANTIVIRUS-TEST-SIGNATURE"


class MockAntivirus:
    def __init__(self, mode: str = "normal"):
        self.mode = mode

    def is_infected(self, path: str) -> bool:
        if self.mode == "unavailable":
            raise TransientError("antivirus is unavailable")
        # Read in chunks (a stem may weigh hundreds of MB); the overlap catches a signature split between chunks
        overlap = max(len(EICAR), len(OHBEAT_TEST_SIGNATURE))
        tail = b""
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                window = tail + chunk
                if EICAR in window or OHBEAT_TEST_SIGNATURE in window:
                    return True
                tail = window[-overlap:]
        return False
