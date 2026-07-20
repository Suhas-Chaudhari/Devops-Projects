import boto3
import datetime
import os

ec2 = boto3.client('ec2')

VOLUME_ID = os.environ.get('VOLUME_ID', 'vol-03fb1ddae64ddfed9')
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '1'))
TAG_KEY = 'CreatedBy'
TAG_VALUE = 'Lambda-Backup'


def lambda_handler(event, context):
    created_id = create_snapshot(VOLUME_ID)
    deleted_ids = cleanup_old_snapshots(RETENTION_DAYS)

    print(f"Created snapshot: {created_id}")
    print(f"Deleted snapshots ({len(deleted_ids)}): {deleted_ids}")

    return {
        "created": created_id,
        "deleted": deleted_ids
    }


def create_snapshot(volume_id):
    timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    response = ec2.create_snapshot(
        VolumeId=volume_id,
        Description=f"Automated snapshot of {volume_id} on {timestamp}",
        TagSpecifications=[
            {
                'ResourceType': 'snapshot',
                'Tags': [
                    {'Key': TAG_KEY, 'Value': TAG_VALUE},
                    {'Key': 'SourceVolume', 'Value': volume_id},
                    {'Key': 'CreatedAt', 'Value': timestamp},
                ]
            }
        ]
    )
    snapshot_id = response['SnapshotId']

    ec2.create_tags(
        Resources=[snapshot_id],
        Tags=[{'Key': TAG_KEY, 'Value': TAG_VALUE}]
    )
    return snapshot_id


def cleanup_old_snapshots(retention_days):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)

    response = ec2.describe_snapshots(
        OwnerIds=['self'],
        Filters=[
            {'Name': f'tag:{TAG_KEY}', 'Values': [TAG_VALUE]}
        ]
    )

    deleted = []
    for snap in response['Snapshots']:
        if snap['StartTime'] < cutoff:
            snapshot_id = snap['SnapshotId']
            try:
                ec2.delete_snapshot(SnapshotId=snapshot_id)
                deleted.append(snapshot_id)
            except Exception as e:
                print(f"Failed to delete {snapshot_id}: {e}")

    return deleted