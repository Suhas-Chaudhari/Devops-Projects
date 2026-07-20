# Task 5: Restore an EC2 Instance from the Latest Snapshot

## Architecture Summary

```
[Manual trigger / EventBridge]
            |
            v
     [Lambda: RestoreEC2FromSnapshot]
            |
   1. describe_snapshots (sorted by StartTime, latest first)
   2. register_image (from snapshot, root device mapping)
   3. wait: image_available
   4. run_instances (t3.micro)
   5. create_tags (RestoredFrom=<snapshot-id>)
            |
            v
      [New EC2 instance running, restored from latest snapshot]
```



## Objective
Automate disaster-recovery: rebuild an EC2 instance from its most recent EBS snapshot using a Lambda function.

---

## Prerequisites
- At least one EBS snapshot exists for the source instance's root volume (pairs well with a "Graded 2" scheduled-snapshot task).
- AWS CLI configured with sufficient permissions to create IAM roles and Lambda functions.

### Step 0a — Create a Snapshot of the Source Instance's Root Volume (Console)

1. Open the **AWS Console** → search for and open **EC2**.
2. In the left sidebar, under **Instances**, click **Instances** → select the source instance (the one you want to protect).
3. In the **Storage** tab (bottom panel), note the **Volume ID** of the root device (e.g. `/dev/xvda` or `/dev/sda1`).
4. In the left sidebar, under **Elastic Block Store**, click **Volumes**.
5. Select the checkbox next to that root volume.
6. Click **Actions** (top right) → **Create snapshot**.
7. In the **Description** field, enter something identifiable, e.g. `root-vol-backup-<instance-id>`.
8. (Optional but recommended) Add a tag: Key = `Name`, Value = `<instance-id>-root-snapshot` — makes it easy to filter later.
9. Click **Create snapshot**.
10. Go to **Elastic Block Store → Snapshots** in the left sidebar and confirm the new snapshot shows status **completed** before moving on (large volumes can take a few minutes).

### Step 0a — Create a Snapshot (CLI equivalent)

```bash
# 1. Find the root volume ID attached to the source instance
aws ec2 describe-instances \
  --instance-ids i-0123456789abcdef0 \
  --query "Reservations[].Instances[].BlockDeviceMappings[?DeviceName=='/dev/xvda'].Ebs.VolumeId" \
  --output text

# 2. Create the snapshot from that volume
aws ec2 create-snapshot \
  --volume-id vol-0123456789abcdef0 \
  --description "root-vol-backup-i-0123456789abcdef0" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=i-0123456789abcdef0-root-snapshot}]'

# 3. Confirm it's completed
aws ec2 describe-snapshots --snapshot-ids snap-0123456789abcdef0 --query "Snapshots[].State"
```

> Tip: if this is meant to run on a schedule ("Graded 2" task), wire step 2 into an EventBridge scheduled rule invoking a small Lambda that calls `create_snapshot` on a timer, so a fresh snapshot always exists before this restore workflow runs.

### Step 0b — Configure the AWS CLI (if not already done)

1. Open a terminal on your local machine or CloudShell.
2. Run:
   ```bash
   aws configure
   ```
3. When prompted, enter:
   - **AWS Access Key ID**
   - **AWS Secret Access Key**
   - **Default region name** (e.g. `us-east-1`)
   - **Default output format** (e.g. `json`)
4. Verify it's working:
   ```bash
   aws sts get-caller-identity
   ```
   This should return your Account ID, User ID, and ARN — confirming credentials are valid.
5. Confirm the IAM user/role you're using has permission to create IAM roles and Lambda functions (either `AdministratorAccess` for testing, or a scoped policy covering `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy`, `lambda:CreateFunction`, `lambda:UpdateFunctionCode`, `lambda:InvokeFunction`).

---

## Step 1 — IAM Role for Lambda

### Custom policy (`ec2-restore-policy.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2RestorePermissions",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeSnapshots",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:RegisterImage",
        "ec2:CreateImage",
        "ec2:DescribeImages",
        "ec2:RunInstances",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    }
  ]
}
```

### Console steps (detailed navigation)

**Create the custom policy:**
1. Open the **AWS Console** → search for and open **IAM**.
2. In the left sidebar, click **Policies**.
3. Click **Create policy** (top right).
4. Click the **JSON** tab.
5. Delete the placeholder text and paste the policy JSON shown above.
6. Click **Next**.
7. In **Policy name**, enter `EC2RestoreFromSnapshotPolicy`.
8. (Optional) Add a description, e.g. "Permissions for Lambda to restore EC2 from snapshot."
9. Click **Create policy**.

**Create the role and attach policies:**
10. In the left sidebar, click **Roles**.
11. Click **Create role** (top right).
12. Under **Trusted entity type**, select **AWS service**.
13. Under **Use case**, select **Lambda** from the dropdown.
14. Click **Next**.
15. In the policy search box, type `EC2RestoreFromSnapshotPolicy` → check its box.
16. In the same search box, type `AWSLambdaBasicExecutionRole` → check its box.
17. Click **Next**.
18. In **Role name**, enter `EC2RestoreLambdaRole`.
19. Scroll down and review the attached policies (both should be listed) → click **Create role**.
20. Click into the newly created role and copy the **ARN** from the top of the summary page (you'll need it in Step 3) — it looks like `arn:aws:iam::<account-id>:role/EC2RestoreLambdaRole`.

### CLI equivalent

```bash
cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name EC2RestoreLambdaRole \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name EC2RestoreLambdaRole \
  --policy-name EC2RestoreFromSnapshotPolicy \
  --policy-document file://ec2-restore-policy.json

aws iam attach-role-policy \
  --role-name EC2RestoreLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

---

## Step 2 — Lambda Function (Boto3)

`lambda_function.py`:

```python
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
```

### Design notes
- Accepts either `instance_id` (auto-detects the root volume/device) or an explicit `volume_id` + `root_device_name`.
- `VirtualizationType: hvm` is required for current-gen instance types such as `t3.micro`.
- Uses the `image_available` waiter to block until the registered AMI is ready before calling `run_instances` — this can take 1-3 minutes, so **the Lambda timeout must be set to at least 300 seconds** (well above the 3-second default).
- Tags the new instance with `RestoredFrom=<snapshot-id>` for traceability, as required.

---

## Step 3 — Package and Deploy

### Console steps (detailed navigation)

1. Open the **AWS Console** → search for and open **Lambda**.
2. Click **Create function** (top right).
3. Select **Author from scratch**.
4. **Function name**: `RestoreEC2FromSnapshot`.
5. **Runtime**: select `Python 3.12`.
6. **Architecture**: leave as `x86_64`.
7. Expand **Change default execution role**.
8. Select **Use an existing role**.
9. From the **Existing role** dropdown, select `EC2RestoreLambdaRole` (created in Step 1).
10. Click **Create function** (bottom right).
11. On the function's page, scroll to the **Code source** panel. Delete the default boilerplate in `lambda_function.py` and paste in the code from Step 2.
12. Click **Deploy** (above the code editor) to save.
13. Go to the **Configuration** tab → **General configuration** → click **Edit**.
14. Set **Timeout** to `5 min 0 sec` (300 seconds — required for the AMI-availability wait).
15. Leave **Memory** at `128 MB` (sufficient for this workload).
16. Click **Save**.

### CLI equivalent

```bash
mkdir ec2-restore-lambda && cd ec2-restore-lambda
# place lambda_function.py in this directory
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name RestoreEC2FromSnapshot \
  --runtime python3.12 \
  --role arn:aws:iam::<YOUR_ACCOUNT_ID>:role/EC2RestoreLambdaRole \
  --handler lambda_function.lambda_handler \
  --timeout 300 \
  --memory-size 128 \
  --zip-file fileb://function.zip
```

Redeploy after edits:

```bash
zip function.zip lambda_function.py
aws lambda update-function-code \
  --function-name RestoreEC2FromSnapshot \
  --zip-file fileb://function.zip
```

---

## Step 4 — Testing

### Console
Lambda → `RestoreEC2FromSnapshot` → **Test** tab → create a new test event:

```json
{
  "instance_id": "i-0123456789abcdef0"
}
```

Run **Test**, then check the execution output and CloudWatch Logs for the printed new instance ID.

### CLI

```bash
aws lambda invoke \
  --function-name RestoreEC2FromSnapshot \
  --payload '{"instance_id":"i-0123456789abcdef0"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
```

### Verification

**Console:**
1. Open **EC2** → left sidebar → **Instances**.
2. In the search/filter bar, filter by tag: `RestoredFrom` (or just look for the instance named `Restored-<snapshot-id>`).
3. Confirm **Instance state** shows `Running`.
4. Select the instance → **Status checks** tab → wait until both checks show `2/2 checks passed`.
5. To confirm data: select the instance → click **Connect** (top right) → choose **EC2 Instance Connect** or **Session Manager** → **Connect**.
6. In the resulting terminal session, verify the expected files/data from the snapshot are present.

**CLI:**

```bash
aws ec2 describe-instances \
  --filters "Name=tag:RestoredFrom,Values=*" \
  --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,AMI:ImageId}"
```

- Confirm the instance transitions to `running`.
- Connect (SSH or SSM Session Manager) and confirm the disk contents match the source volume at snapshot time.

---

## Step 5 — Cleanup

### Console steps (detailed navigation)

**Terminate the test instance:**
1. Open **EC2** → **Instances**.
2. Select the checkbox next to the restored test instance.
3. Click **Instance state** (top right) → **Terminate instance**.
4. Confirm by clicking **Terminate**.
5. Wait for **Instance state** to show `Terminated`.

**Deregister the test AMI:**
6. In the left sidebar, under **Images**, click **AMIs**.
7. Select the checkbox next to the AMI named `Restored-AMI-<snapshot-id>-...`.
8. Click **Actions** → **Deregister AMI**.
9. Confirm by clicking **Deregister AMI**.

**(Optional) Delete the snapshot copy, if one was made just for testing — not the original source snapshot:**
10. In the left sidebar, under **Elastic Block Store**, click **Snapshots**.
11. Select the test snapshot (verify it is NOT your original source-of-truth snapshot).
12. Click **Actions** → **Delete snapshot** → confirm.

### CLI equivalent

```bash
# Terminate the test instance
aws ec2 terminate-instances --instance-ids <NEW_INSTANCE_ID>

# Deregister the AMI created for the test
aws ec2 deregister-image --image-id <AMI_ID>
```

Terminating promptly avoids ongoing EC2 charges from test restores.

---

