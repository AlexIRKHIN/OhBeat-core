"""Prepares S3 (MinIO) buckets. Runs on every start of the environment; every step is idempotent.

* Three buckets from System_Architecture.md: temp-uploads, private-media, public-media.
* public-media is readable anonymously: locally MinIO plays the role of the CDN.
* FR-8: objects in temp-uploads expire after 1 day (the minimal lifecycle unit).

Plain S3 API calls are used instead of the `mc` utility, which is no longer distributed (ADR 0008).
"""

import json
import time

from botocore.exceptions import ClientError, EndpointConnectionError

from app.common.config import get_settings
from app.common.storage import _client


def wait_for_s3(client, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            client.list_buckets()
            return
        except (EndpointConnectionError, ClientError):
            time.sleep(1)
    raise RuntimeError("S3 is not reachable")


def ensure_bucket(client, name: str) -> None:
    try:
        client.head_bucket(Bucket=name)
    except ClientError:
        client.create_bucket(Bucket=name)
        print(f"created bucket {name}")


def main() -> None:
    settings = get_settings()
    client = _client(settings.s3_internal_endpoint)
    wait_for_s3(client)

    for bucket in (settings.bucket_temp, settings.bucket_private, settings.bucket_public):
        ensure_bucket(client, bucket)

    # Anonymous read of single objects (no listing) in the public bucket
    client.put_bucket_policy(
        Bucket=settings.bucket_public,
        Policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{settings.bucket_public}/*"],
                    }
                ],
            }
        ),
    )

    # FR-8: raw uploads are removed after 24 hours
    client.put_bucket_lifecycle_configuration(
        Bucket=settings.bucket_temp,
        LifecycleConfiguration={
            "Rules": [{"ID": "expire-raw-uploads", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": 1}}]
        },
    )
    print("S3 buckets are ready")


if __name__ == "__main__":
    main()
