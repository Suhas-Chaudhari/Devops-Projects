import boto3
from datetime import datetime

ec2 = boto3.client('ec2')

def lambda_handler(event, context):
    """
    Event input options:
      { "instance_id": "i-xxxxxxxx" }   -> auto-detects root volume
      OR
      { "volume_id": "vol-xxxxxxxx", "root_device_name": "/dev/xvda" }
    """
    instance_id = event.get('instance_id')
    volume_id = event.get('volume_id')
    root_device_name = event.get('root_device_name')

    # 1. Resolve the volume + root device if only an instance_id was given
    if not volume_id:
        if not instance_id:
            raise ValueError("Provide either 'instance_id' or 'volume_id' in the event.")
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        instance = resp['Reservations'][0]['Instances'][0]
        root_device_name = instance['RootDeviceName']
        for bdm in instance['BlockDeviceMappings']:
            if bdm['DeviceName'] == root_device_name:
                volume_id = bdm['Ebs']['VolumeId']
        if not volume_id:
            raise ValueError(f"Could not find root volume for instance {instance_id}")
    elif not root_device_name:
        root_device_name = '/dev/xvda'

    print(f"Using volume: {volume_id}, root device: {root_device_name}")

    # 2. Find the most recent snapshot for that volume
    snapshots = ec2.describe_snapshots(
        Filters=[{'Name': 'volume-id', 'Values': [volume_id]}],
        OwnerIds=['self']
    )['Snapshots']

    if not snapshots:
        raise Exception(f"No snapshots found for volume {volume_id}")

    latest_snapshot = sorted(snapshots, key=lambda s: s['StartTime'], reverse=True)[0]
    snapshot_id = latest_snapshot['SnapshotId']
    print(f"Latest snapshot: {snapshot_id} (created {latest_snapshot['StartTime']})")

    # 3. Register a new AMI from the snapshot
    ami_name = f"Restored-AMI-{snapshot_id}-{int(datetime.utcnow().timestamp())}"
    image_resp = ec2.register_image(
        Name=ami_name,
        Architecture='x86_64',
        RootDeviceName=root_device_name,
        BlockDeviceMappings=[{
            'DeviceName': root_device_name,
            'Ebs': {
                'SnapshotId': snapshot_id,
                'VolumeType': 'gp3',
                'DeleteOnTermination': True
            }
        }],
        VirtualizationType='hvm',
        EnaSupport=True
    )
    ami_id = image_resp['ImageId']
    print(f"Registered AMI: {ami_id}")

    # 4. Wait until the AMI is available before launching
    waiter = ec2.get_waiter('image_available')
    waiter.wait(ImageIds=[ami_id], WaiterConfig={'Delay': 15, 'MaxAttempts': 20})

    # 5. Launch a new t3.micro instance from the AMI
    run_resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType='t3.micro',
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [
                {'Key': 'Name', 'Value': f'Restored-{snapshot_id}'},
                {'Key': 'RestoredFrom', 'Value': snapshot_id}
            ]
        }]
    )
    new_instance_id = run_resp['Instances'][0]['InstanceId']
    print(f"New instance launched: {new_instance_id}")

    return {
        'statusCode': 200,
        'new_instance_id': new_instance_id,
        'ami_id': ami_id,
        'snapshot_id': snapshot_id
    }