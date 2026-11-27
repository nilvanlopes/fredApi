"""Provision the Fred-only private bucket using the API's configured credentials.

Run explicitly with `python -m app.profile_storage_setup` on floci-internal.
This never modifies the FichasRPG buckets or policies.
"""
from botocore.exceptions import ClientError

from app.profile_photos import bucket, storage


def main():
    client = storage()
    name = bucket()
    if name != "fred-profile-images":
        raise SystemExit("Este provisionador aceita somente o bucket fred-profile-images.")
    try:
        client.head_bucket(Bucket=name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=name)
    client.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
    })
    try:
        client.delete_bucket_policy(Bucket=name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchBucketPolicy", "404", "NotFound"}:
            raise
    print(f"Bucket privado do Fred configurado: {name}")


if __name__ == "__main__":
    main()
