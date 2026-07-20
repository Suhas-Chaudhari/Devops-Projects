# Automated EBS Snapshot Creation and Cleanup — AWS Console + CLI Guide

This guide walks through every step **both** via the AWS Management Console (click-by-click navigation) **and** the equivalent AWS CLI command, so you can follow whichever workflow you prefer.

---

## 1. EBS Volume Setup

### Console Navigation
1. Sign in to the **AWS Management Console**.
2. In the top search bar, type **EC2** and select it.
3. In the left sidebar, under **Elastic Block Store**, click **Volumes**.
4. To use an existing volume: note the **Volume ID** (starts with `vol-`) from the list.
5. To create a new test volume:
   - Click **Create volume** (top right).
   - **Volume type**: `gp3`
   - **Size**: `8` GiB
   - **Availability Zone**: pick one matching your test EC2 instance's AZ (e.g., `us-east-1a`)
   - Scroll to **Tags** → **Add tag** → Key: `Name`, Value: `lambda-backup-test`
   - Click **Create volume**.
6. Copy the new **Volume ID** — you'll need it for the Lambda environment variable.

### CLI Equivalent
```bash
# List existing volumes
aws ec2 describe-volumes --query "Volumes[*].{ID:VolumeId,State:State,Size:Size}" --output table

# Create a new test volume
aws ec2 create-volume \
    --availability-zone us-east-1a \
    --size 8 \
    --volume-type gp3 \
    --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=lambda-backup-test}]'
```

---

## 2. IAM Role for Lambda

### Console Navigation
1. Search bar → **IAM** → open the IAM console.
2. Left sidebar → **Roles** → **Create role**.
3. **Trusted entity type**: `AWS service`
4. **Use case**: select `Lambda` → **Next**.
5. On the **Add permissions** page, skip attaching a managed policy for now (you'll add an inline one after creation) → **Next**.
6. **Role name**: `LambdaEBSBackupRole` → **Create role**.
7. Open the newly created role → **Add permissions** dropdown → **Create inline policy**.
8. Click the **JSON** tab and paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "SnapshotLifecycle",
         "Effect": "Allow",
         "Action": [
           "ec2:CreateSnapshot",
           "ec2:DescribeSnapshots",
           "ec2:DeleteSnapshot",
           "ec2:CreateTags",
           "ec2:DescribeVolumes"
         ],
         "Resource": "*"
       },
       {
         "Sid": "Logging",
         "Effect": "Allow",
         "Action": [
           "logs:CreateLogGroup",
           "logs:CreateLogStream",
           "logs:PutLogEvents"
         ],
         "Resource": "arn:aws:logs:*:*:*"
       }
     ]
   }
   ```
9. Click **Next**, name it `EBSSnapshotInlinePolicy`, click **Create policy**.
10. Copy the **Role ARN** from the role's summary page (top of page) — needed for Lambda creation.

### CLI Equivalent
`trust-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

`ebs-snapshot-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SnapshotLifecycle",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateSnapshot",
        "ec2:DescribeSnapshots",
        "ec2:DeleteSnapshot",
        "ec2:CreateTags",
        "ec2:DescribeVolumes"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Logging",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

```bash
aws iam create-role \
    --role-name LambdaEBSBackupRole \
    --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
    --role-name LambdaEBSBackupRole \
    --policy-name EBSSnapshotInlinePolicy \
    --policy-document file://ebs-snapshot-policy.json

# Get the Role ARN
aws iam get-role --role-name LambdaEBSBackupRole --query "Role.Arn" --output text
```

---

## 3. Create the Lambda Function

### Console Navigation
1. Search bar → **Lambda** → open the Lambda console.
2. Click **Create function**.
3. Select **Author from scratch**.
4. **Function name**: `EBSBackupCleanup`
5. **Runtime**: `Python 3.12`
6. **Architecture**: `x86_64`
7. Expand **Change default execution role** → select **Use an existing role** → choose `LambdaEBSBackupRole`.
8. Click **Create function**.
9. In the **Code source** editor, delete the placeholder code and paste the script below (see full code in the next section).
10. Click **Deploy**.
11. Go to the **Configuration** tab → **General configuration** → **Edit**:
    - **Timeout**: set to `1 min 0 sec`
    - Save.
12. Configuration tab → **Environment variables** → **Edit** → **Add environment variable**:
    - Key: `VOLUME_ID`, Value: `vol-0123456789abcdef0` (your actual volume ID)
    - Key: `RETENTION_DAYS`, Value: `30`
    - Save.

### Lambda Function Code (`lambda_function.py`)
```python
import boto3
import datetime
import os

ec2 = boto3.client('ec2')

VOLUME_ID = os.environ.get('VOLUME_ID', 'vol-03fb1ddae64ddfed9')
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '30'))
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
```

### CLI Equivalent
```bash
# Save the code above as lambda_function.py, then:
zip function.zip lambda_function.py

aws lambda create-function \
    --function-name EBSBackupCleanup \
    --runtime python3.12 \
    --role arn:aws:iam::<ACCOUNT_ID>:role/LambdaEBSBackupRole \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://function.zip \
    --timeout 60 \
    --environment "Variables={VOLUME_ID=vol-0123456789abcdef0,RETENTION_DAYS=2}"

# If you need to update the code later
aws lambda update-function-code \
    --function-name EBSBackupCleanup \
    --zip-file fileb://function.zip
```

---

## 4. EventBridge Weekly Schedule

### Console Navigation
1. Search bar → **EventBridge** → open the EventBridge console.
2. Left sidebar → **Rules** → **Create rule**.
3. **Name**: `WeeklyEBSBackup`
4. **Rule type**: `Schedule` → **Next**.
5. **Schedule pattern**: select **A fine-grained schedule that runs at a specific time** → choose **Cron-based schedule**.
6. Enter cron expression: `0 3 ? * SUN *` (runs every Sunday at 03:00 UTC) → **Next**.
7. **Target type**: `AWS service`.
8. **Select a target**: `Lambda function`.
9. **Function**: select `EBSBackupCleanup` → **Next**.
10. Review and click **Create rule**.
    - EventBridge automatically adds the required invoke permission to the Lambda when created through the console.

### CLI Equivalent
```bash
aws events put-rule \
    --name WeeklyEBSBackup \
    --schedule-expression "cron(0 3 ? * SUN *)"

aws lambda add-permission \
    --function-name EBSBackupCleanup \
    --statement-id EventBridgeInvoke \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:<REGION>:<ACCOUNT_ID>:rule/WeeklyEBSBackup

aws events put-targets \
    --rule WeeklyEBSBackup \
    --targets "Id"="1","Arn"="arn:aws:lambda:<REGION>:<ACCOUNT_ID>:function:EBSBackupCleanup"
```

---

## 5. Testing

### Console Navigation — Manual Trigger
1. Open the **Lambda** console → select `EBSBackupCleanup`.
2. Click the **Test** tab.
3. **Event name**: `manual-test`
4. Leave the default JSON `{}` (no input needed) → **Save**.
5. Click **Test**.
6. Check the **Execution results** panel at the top — expand **Details** to see the returned JSON (`created` and `deleted` snapshot IDs) and the **Log output** with printed statements.

### Console Navigation — Verify in EC2 Console
1. Go to **EC2** console → **Elastic Block Store** → **Snapshots** (left sidebar).
2. Use the search/filter bar: filter by tag `CreatedBy` = `Lambda-Backup`.
3. Confirm the new snapshot appears with **Started** timestamp matching your test run and status `completed`.
4. To test cleanup: go back to Lambda → **Configuration** → **Environment variables** → temporarily set `RETENTION_DAYS` to `0` → **Save** → re-run **Test** tab.
5. Refresh the Snapshots list in EC2 console — older tagged snapshots should disappear.
6. Reset `RETENTION_DAYS` back to `30` in Lambda configuration afterward.

### Console Navigation — View Logs
1. Lambda console → `EBSBackupCleanup` → **Monitor** tab → **View CloudWatch logs**.
2. Click the most recent **Log stream** to see the printed created/deleted snapshot IDs.

### CLI Equivalent
```bash
# Manual invoke
aws lambda invoke \
    --function-name EBSBackupCleanup \
    --cli-binary-format raw-in-base64-out \
    --payload '{}' \
    response.json

cat response.json

# Verify snapshots
aws ec2 describe-snapshots \
    --owner-ids self \
    --filters "Name=tag:CreatedBy,Values=Lambda-Backup" \
    --query "Snapshots[*].{ID:SnapshotId,Start:StartTime,Vol:VolumeId}" \
    --output table

# Test cleanup with 0-day retention
aws lambda update-function-configuration \
    --function-name EBSBackupCleanup \
    --environment "Variables={VOLUME_ID=vol-0123456789abcdef0,RETENTION_DAYS=0}"

aws lambda invoke --function-name EBSBackupCleanup --payload '{}' response2.json

# Reset retention back to 30
aws lambda update-function-configuration \
    --function-name EBSBackupCleanup \
    --environment "Variables={VOLUME_ID=vol-0123456789abcdef0,RETENTION_DAYS=30}"

# Tail logs
aws logs tail /aws/lambda/EBSBackupCleanup --follow
```

---

## 6. Lambda vs. AWS Data Lifecycle Manager (DLM)

**DLM Console Navigation (for comparison/reference):**
1. EC2 console → left sidebar (bottom, under **Elastic Block Store**) → **Lifecycle Manager**.
2. **Create lifecycle policy** → choose **EBS snapshot policy**.
3. Select target volumes by tag, set schedule frequency and retention count/days, assign an IAM role (DLM has an AWS-managed service-linked role option).
4. No code required — this is DLM's core appeal for simple schedules.

**When DLM is enough:**
- Straightforward "snapshot on a schedule, keep last N / keep N days" policies for tagged volumes.
- No custom logic, no cross-account requirements, no notifications needed.

**When Lambda is the better choice:**
- **Custom retention logic** — e.g., keep monthly snapshots for a year, vary retention by environment tag, grandfather-father-son schemes.
- **Cross-account or cross-region copies** integrated into the same workflow (`ModifySnapshotAttribute`, copy to another account/region as part of the run).
- **Notifications/integrations** — SNS/Slack/email alerts on failure, writing to a DynamoDB audit table, triggering downstream pipelines after snapshot completion.
- **Conditional/event-driven backups** — snapshot only after a batch job finishes, on-demand via API Gateway, or triggered by a CloudWatch alarm rather than strictly on a schedule.
- **Multi-resource orchestration** — coordinating EBS snapshots alongside RDS snapshots, AMI creation, or other steps in one workflow.

For a plain "snapshot weekly, delete after 30 days" requirement with no extra logic, DLM is lower-maintenance since there's no code, IAM inline policy, or EventBridge rule to maintain. Lambda earns its keep once you need the fine-grained behavior above.