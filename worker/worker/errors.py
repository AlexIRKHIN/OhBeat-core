"""Two kinds of failure, handled differently (RabbitMQ_Worker.md §5)."""


class RejectError(Exception):
    """A file did not pass a check. Not a failure of the worker: the beat becomes `rejected`
    with this reason, the command is acknowledged and never retried."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class TransientError(Exception):
    """A temporary failure (S3 timeout, network, antivirus down): retried after 30 s, 2 min, 10 min,
    then the message goes to the DLQ."""
