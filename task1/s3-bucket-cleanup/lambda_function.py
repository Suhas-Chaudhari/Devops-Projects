import boto3
import os
from datetime import datetime, timezone, timedelta

s3 = boto3.client('s3')

BUCKET_NAME = os.environ['BUCKET_NAME']
AGE_THRESHOLD_DAYS = int(os.environ.get('AGE_THRESHOLD_DAYS', '1'))
# Optional override for quick testing (e.g. "2" = 2 minutes)
AGE_THRESHOLD_MINUTES = os.environ.get('AGE_THRESHOLD_MINUTES')


def lambda_handler(event, context):
    if AGE_THRESHOLD_MINUTES:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(AGE_THRESHOLD_MINUTES))
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=AGE_THRESHOLD_DAYS)

    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=BUCKET_NAME)

    deleted = []
    scanned = 0

    for page in page_iterator:
        contents = page.get('Contents', [])
        objects_to_delete = []

        for obj in contents:
            scanned += 1
            key = obj['Key']
            last_modified = obj['LastModified']  # timezone-aware, UTC

            if last_modified < cutoff:
                objects_to_delete.append({'Key': key})

        # Batch delete (S3 allows up to 1000 keys per call)
        if objects_to_delete:
            response = s3.delete_objects(
                Bucket=BUCKET_NAME,
                Delete={'Objects': objects_to_delete, 'Quiet': True}
            )
            deleted.extend([o['Key'] for o in objects_to_delete])

            errors = response.get('Errors', [])
            if errors:
                print(f"Errors during delete: {errors}")

    print(f"Scanned {scanned} objects. Deleted {len(deleted)} objects.")
    for key in deleted:
        print(f"Deleted: {key}")

    return {
        'statusCode': 200,
        'scanned': scanned,
        'deleted_count': len(deleted),
        'deleted_keys': deleted
    }