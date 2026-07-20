# Devops-Projects

# AWS Automation Projects — README

This README merges all six AWS Lambda automation tasks into a single reference document. Each task includes the objective, architecture, IAM policy, full Boto3 Lambda code, AWS Console navigation (click-by-click), the equivalent AWS CLI commands, testing steps, and cleanup instructions.

## Overview

| # | Task | Trigger | Key AWS Services | Objective |
|---|------|---------|-------------------|-----------|
| 1 | Automated S3 Bucket Cleanup | Manual / EventBridge (optional) | S3, Lambda, IAM, CloudWatch | Delete objects older than 30 days from an S3 bucket |
| 2 | Automated EBS Snapshot Creation and Cleanup | EventBridge (weekly) | EC2/EBS, Lambda, IAM | Create EBS snapshots on a schedule and delete ones past retention |
| 3 | Auto-Tagging EC2 Instances on Launch | EventBridge (event pattern) | EC2, Lambda, CloudTrail, IAM | Tag new EC2 instances automatically with LaunchDate/Environment/Owner |
| 4 | Daily AWS Cost Alert | EventBridge (daily) | Cost Explorer, SNS, Lambda, IAM | Alert via email when month-to-date spend exceeds a threshold |
| 5 | Restore an EC2 Instance from the Latest Snapshot | Manual / EventBridge (optional) | EC2, EBS, Lambda, IAM | Disaster recovery: rebuild an instance from its latest snapshot |
| 6 | Audit S3 Buckets for Public Access and Notify | EventBridge (daily) | S3, SNS, Lambda, IAM | Detect publicly accessible buckets and alert via SNS |

## Table of Contents

- [Task 1: Automated S3 Bucket Cleanup (Objects Older Than 30 Days)](#task-1-automated-s3-bucket-cleanup-objects-older-than-30-days)
- [Task 2: Automated EBS Snapshot Creation and Cleanup](#task-2-automated-ebs-snapshot-creation-and-cleanup)
- [Task 3: Auto-Tagging EC2 Instances on Launch](#task-3-auto-tagging-ec2-instances-on-launch)
- [Task 4: Daily AWS Cost Alert Using Cost Explorer API and SNS](#task-4-daily-aws-cost-alert-using-cost-explorer-api-and-sns)
- [Task 5: Restore an EC2 Instance from the Latest Snapshot](#task-5-restore-an-ec2-instance-from-the-latest-snapshot)
- [Task 6: Audit S3 Buckets for Public Access and Notify](#task-6-audit-s3-buckets-for-public-access-and-notify)

---

## Task 1: Automated S3 Bucket Cleanup (Objects Older Than 30 Days)

### Objective
Automatically delete stale objects (older than 30 days) from an S3 bucket using a scheduled/manually-triggered Lambda function, with least-privilege IAM permissions.

### Architecture
```
[Manual Trigger / EventBridge Schedule] → [Lambda Function] → [S3 Bucket]
                                                ↓
                                          CloudWatch Logs
```

---

### Step 1: S3 Bucket Setup

#### AWS Console Navigation
1. Sign in to the **AWS Management Console**.
2. In the top search bar, type **S3** and open the **S3** service.
3. Click **Create bucket**.
4. **Bucket name:** `my-cleanup-demo-bucket` (must be globally unique — add your own suffix, e.g. initials or numbers).
5. **AWS Region:** choose your working region (e.g., `us-east-1`).
6. Leave **Block all public access** checked (default — keep it on).
7. Leave other settings default, scroll down, click **Create bucket**.
8. Open the bucket → click **Upload** → **Add files** → select 3–4 test files (e.g., `file1.txt`, `file2.txt`, `file3.txt`,`file4.txt`,`file5.txt`) → click **Upload**.

#### CLI Equivalent
```bash
aws s3 mb s3://my-cleanup-demo-bucket --region us-east-1

# Create test files
echo "test file 1" > file1.txt
echo "test file 2" > file2.txt
echo "test file 3" > file3.txt
echo "test file 3" > file4.txt
echo "test file 3" > file5.txt

# Upload
aws s3 cp file1.txt s3://my-cleanup-demo-bucket/
aws s3 cp file2.txt s3://my-cleanup-demo-bucket/
aws s3 cp file3.txt s3://my-cleanup-demo-bucket/
aws s3 cp file4.txt s3://my-cleanup-demo-bucket/
aws s3 cp file5.txt s3://my-cleanup-demo-bucket/

# Verify
aws s3 ls s3://my-cleanup-demo-bucket/
```

> **Note on testing "old" files:** S3 sets `LastModified` automatically at upload time — you cannot backdate it. So for testing, temporarily lower the age threshold to a few minutes (via a Lambda environment variable), upload files, wait past that window, run the function, and confirm deletion. Then switch the threshold back to 30 days for the "production" version.

---

### Step 2: Lambda IAM Role

#### AWS Console Navigation
1. Search bar → type **IAM** → open **IAM** service.
2. Left sidebar → **Roles** → **Create role**.
3. **Trusted entity type:** AWS service.
4. **Use case:** select **Lambda** → click **Next**.
5. On the **Add permissions** page, skip attaching a managed policy for now (we'll add an inline policy after creation) → click **Next**.
6. **Role name:** `s3-cleanup-lambda-role` → click **Create role**.
7. Open the newly created role → **Add permissions** dropdown → **Create inline policy**.
8. Switch to the **JSON** tab and paste the policy below (see JSON block).
9. Click **Next**, name it `s3-cleanup-inline-policy`, click **Create policy**.
10. Also attach the AWS managed policy **AWSLambdaBasicExecutionRole** (Add permissions → Attach policies → search and select it) so the function can write to CloudWatch Logs.

#### Trust Policy (created automatically by console; shown here for CLI users)
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

#### Inline Permissions Policy — scoped to one bucket
`s3-cleanup-policy.json`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-cleanup-demo-bucket"
    },
    {
      "Effect": "Allow",
      "Action": "s3:DeleteObject",
      "Resource": "arn:aws:s3:::my-cleanup-demo-bucket/*"
    },
    {
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

> **Important:** `s3:ListBucket` applies to the **bucket ARN** (no trailing `/*`), while `s3:DeleteObject` applies to **object ARNs** (with `/*`). Mixing these up is the most common cause of `AccessDenied` errors.

#### CLI Equivalent
```bash
aws iam create-role \
  --role-name s3-cleanup-lambda-role \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name s3-cleanup-lambda-role \
  --policy-name s3-cleanup-inline-policy \
  --policy-document file://s3-cleanup-policy.json
```

---

### Step 3: Lambda Function (Python 3.12, Boto3)

#### AWS Console Navigation
1. Search bar → type **Lambda** → open **Lambda** service.
2. Click **Create function**.
3. Choose **Author from scratch**.
4. **Function name:** `s3-stale-object-cleanup`.
5. **Runtime:** Python 3.12.
6. **Architecture:** x86_64 (default is fine).
7. Expand **Change default execution role** → select **Use an existing role** → choose `s3-cleanup-lambda-role`.
8. Click **Create function**.
9. In the **Code** tab, delete the placeholder code in `lambda_function.py` and paste the code below.
10. Click **Deploy** (top left of the code editor) to save.
11. Go to the **Configuration** tab → **Environment variables** → **Edit** → **Add environment variable**:
    - Key: `BUCKET_NAME`, Value: `my-cleanup-demo-bucket`
    - Key: `AGE_THRESHOLD_DAYS`, Value: `1`
    - Save.
12. Still under **Configuration** → **General configuration** → **Edit** → set **Timeout** to `1 min 0 sec` (default 3 sec is too short) → **Save**.

#### `lambda_function.py`
```python
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
```

**Key implementation notes:**
- Uses the **paginator** (`get_paginator('list_objects_v2')`) so buckets with more than 1000 objects are fully scanned, not just the first page.
- `LastModified` returned by S3 is already **timezone-aware UTC**, so it compares directly and safely against `datetime.now(timezone.utc)` — no manual `tzinfo` conversion needed.
- Uses the **batch** `delete_objects` API (up to 1000 keys per call) instead of looping single `delete_object` calls — fewer API calls, faster, cheaper.
- Deleted key names are printed to CloudWatch Logs as required.

#### CLI Equivalent (package + deploy)
```bash
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name s3-stale-object-cleanup \
  --runtime python3.12 \
  --role arn:aws:iam::<YOUR_ACCOUNT_ID>:role/s3-cleanup-lambda-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --timeout 60 \
  --environment "Variables={BUCKET_NAME=my-cleanup-demo-bucket-12345,AGE_THRESHOLD_DAYS=30}"
```

To update code after edits:
```bash
zip function.zip lambda_function.py
aws lambda update-function-code \
  --function-name s3-stale-object-cleanup \
  --zip-file fileb://function.zip
```

---

### Step 4: Testing

#### Phase A — Test with minutes threshold

**Console:**
1. Go to Lambda function → **Configuration** → **Environment variables** → **Edit**.
2. Add a new variable: Key `AGE_THRESHOLD_MINUTES`, Value `2` → **Save**.
3. Upload a couple of test files to the bucket now (S3 console → Upload).
4. Wait 2–3 minutes.
5. Go to the **Test** tab → **Create new event** → Event name: `manualTest` → keep the default empty JSON `{}` (the function doesn't need event input) → **Save** → click **Test**.
6. Check the **Execution results** panel for output, and check **Monitor** tab → **View CloudWatch logs** to see the printed deleted key names.

**CLI:**
```bash
aws lambda update-function-configuration \
  --function-name s3-stale-object-cleanup \
  --environment "Variables={BUCKET_NAME=my-cleanup-demo-bucket-12345,AGE_THRESHOLD_DAYS=30,AGE_THRESHOLD_MINUTES=2}"

aws lambda invoke \
  --function-name s3-stale-object-cleanup \
  --cli-binary-format raw-in-base64-out \
  output.json

cat output.json

aws s3 ls s3://my-cleanup-demo-bucket/
```

Confirm the files uploaded before the wait window are gone, and any files uploaded after remain.

#### Phase B — Reset to production threshold

**Console:** Configuration → Environment variables → **Edit** → delete the `AGE_THRESHOLD_MINUTES` variable entirely (leave `AGE_THRESHOLD_DAYS=30`) → **Save**.

**CLI:**
```bash
aws lambda update-function-configuration \
  --function-name s3-stale-object-cleanup \
  --environment "Variables={BUCKET_NAME=my-cleanup-demo-bucket,AGE_THRESHOLD_DAYS=1}"
```

#### Checking CloudWatch Logs (Console)
1. Search bar → **CloudWatch** → **Log groups**.
2. Find `/aws/lambda/s3-stale-object-cleanup`.
3. Open the latest **Log stream** to view scanned/deleted counts and the list of deleted keys.

---

### Step 5 (Optional): Schedule with EventBridge instead of manual trigger

If you want this to run automatically (e.g., daily) rather than being manually invoked:

**Console:**
1. Go to the Lambda function → **Add trigger**.
2. Select **EventBridge (CloudWatch Events)**.
3. Choose **Create a new rule**.
4. Rule name: `daily-s3-cleanup-schedule`.
5. Rule type: **Schedule expression** → enter `rate(1 day)` (or a cron expression like `cron(0 3 * * ? *)` for 3 AM daily or `rate(10 minutes)`).
6. Click **Add**.

**CLI:**
```bash
aws events put-rule \
  --name daily-s3-cleanup-schedule \
  --schedule-expression "rate(1 day)"

aws lambda add-permission \
  --function-name s3-stale-object-cleanup \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:<YOUR_ACCOUNT_ID>:rule/daily-s3-cleanup-schedule

aws events put-targets \
  --rule daily-s3-cleanup-schedule \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:<YOUR_ACCOUNT_ID>:function:s3-stale-object-cleanup"
```

---

### Step 6: Discussion Point — Lambda vs. S3 Lifecycle Rules

**S3 Lifecycle Rules** (Bucket → Management tab → Create lifecycle rule) handle plain age-based expiration natively — no code, no compute cost, no maintenance, and AWS runs the sweep on your behalf on a nightly-ish schedule. For a simple "delete everything older than N days" requirement, this is almost always the right default.

**Use Lambda instead when you need:**
1. **Conditional logic** lifecycle rules can't express — e.g., "delete only if there's no matching entry in a DynamoDB table" or "keep the 5 newest versions per customer regardless of age."
2. **Naming-pattern or metadata-driven filtering** beyond lifecycle's prefix/tag filters — e.g., regex-based key matching or logic based on tags set dynamically by another system.
3. **Cross-service actions** tied to the deletion — e.g., delete the object *and* publish an SNS alert, write an audit log entry, or update a search index — since lifecycle rules can only delete/transition, not fan out to other services.

---

### Cleanup (avoid ongoing charges)
```bash
# Delete the Lambda function
aws lambda delete-function --function-name s3-stale-object-cleanup

# Delete the EventBridge rule (if created)
aws events remove-targets --rule daily-s3-cleanup-schedule --ids "1"
aws events delete-rule --name daily-s3-cleanup-schedule

# Delete the IAM role
aws iam delete-role-policy --role-name s3-cleanup-lambda-role --policy-name s3-cleanup-inline-policy
aws iam detach-role-policy --role-name s3-cleanup-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name s3-cleanup-lambda-role

# Empty and delete the bucket
aws s3 rm s3://my-cleanup-demo-bucket --recursive
aws s3 rb s3://my-cleanup-demo-bucket
```

---

## Task 2: Automated EBS Snapshot Creation and Cleanup

This section walks through every step **both** via the AWS Management Console (click-by-click navigation) **and** the equivalent AWS CLI command, so you can follow whichever workflow you prefer.

---

### 1. EBS Volume Setup

#### Console Navigation
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

#### CLI Equivalent
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

### 2. IAM Role for Lambda

#### Console Navigation
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

#### CLI Equivalent
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

### 3. Create the Lambda Function

#### Console Navigation
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

#### Lambda Function Code (`lambda_function.py`)
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

#### CLI Equivalent
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

### 4. EventBridge Weekly Schedule

#### Console Navigation
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

#### CLI Equivalent
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

### 5. Testing

#### Console Navigation — Manual Trigger
1. Open the **Lambda** console → select `EBSBackupCleanup`.
2. Click the **Test** tab.
3. **Event name**: `manual-test`
4. Leave the default JSON `{}` (no input needed) → **Save**.
5. Click **Test**.
6. Check the **Execution results** panel at the top — expand **Details** to see the returned JSON (`created` and `deleted` snapshot IDs) and the **Log output** with printed statements.

#### Console Navigation — Verify in EC2 Console
1. Go to **EC2** console → **Elastic Block Store** → **Snapshots** (left sidebar).
2. Use the search/filter bar: filter by tag `CreatedBy` = `Lambda-Backup`.
3. Confirm the new snapshot appears with **Started** timestamp matching your test run and status `completed`.
4. To test cleanup: go back to Lambda → **Configuration** → **Environment variables** → temporarily set `RETENTION_DAYS` to `0` → **Save** → re-run **Test** tab.
5. Refresh the Snapshots list in EC2 console — older tagged snapshots should disappear.
6. Reset `RETENTION_DAYS` back to `30` in Lambda configuration afterward.

#### Console Navigation — View Logs
1. Lambda console → `EBSBackupCleanup` → **Monitor** tab → **View CloudWatch logs**.
2. Click the most recent **Log stream** to see the printed created/deleted snapshot IDs.

#### CLI Equivalent
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

### 6. Lambda vs. AWS Data Lifecycle Manager (DLM)

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

---

## Task 3: Auto-Tagging EC2 Instances on Launch

**Objective:** Automatically tag newly launched EC2 instances for resource tracking, ownership, and cost allocation using EventBridge + Lambda.

**Architecture:**

```
EC2 Instance Launch → State changes to "running"
        │
        ▼
EventBridge Rule (pattern match: aws.ec2 / running)
        │
        ▼
Lambda Function (boto3) → ec2:CreateTags
        │
        ▼
Instance tagged: LaunchDate, Environment, Owner (via CloudTrail lookup)
```

---

### Step 1: Create the IAM Role for Lambda

#### Console Navigation
1. Search **IAM** in the top search bar → open it.
2. Left sidebar → **Roles** → **Create role**.
3. Trusted entity type: **AWS service**.
4. Use case: search and select **Lambda** → **Next**.
5. Skip attaching managed policies → **Next**.
6. Role name: `ec2-autotag-lambda-role` → **Create role**.
7. Click into the new role → **Add permissions** → **Create inline policy**.
8. Switch to the **JSON** tab, paste the policy below.
9. **Next** → Policy name: `ec2-autotag-inline-policy` → **Create policy**.

#### Trust Policy

`trust-policy.json`
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

#### Inline Permissions Policy

`ec2-autotag-policy.json`
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2TaggingPermissions",
      "Effect": "Allow",
      "Action": ["ec2:CreateTags", "ec2:DescribeInstances"],
      "Resource": "*"
    },
    {
      "Sid": "CloudTrailLookup",
      "Effect": "Allow",
      "Action": ["cloudtrail:LookupEvents"],
      "Resource": "*"
    },
    {
      "Sid": "Logging",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

> The `CloudTrailLookup` statement is only needed for the Bonus (Owner-from-IAM-user) feature. Remove it if you don't need that.

#### CLI Commands

```bash
cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole" }
  ]
}
EOF

aws iam create-role \
  --role-name ec2-autotag-lambda-role \
  --assume-role-policy-document file://trust-policy.json

aws iam attach-role-policy \
  --role-name ec2-autotag-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name ec2-autotag-lambda-role \
  --policy-name ec2-autotag-inline-policy \
  --policy-document file://ec2-autotag-policy.json

# Save the ARN — needed in Step 2
aws iam get-role --role-name ec2-autotag-lambda-role --query 'Role.Arn' --output text
```

---

### Step 2: Create the Lambda Function

#### Console Navigation
1. Search **Lambda** → **Functions** → **Create function**.
2. Choose **Author from scratch**.
3. Function name: `ec2-autotag-on-launch`.
4. Runtime: **Python 3.12**.
5. Permissions → **Use an existing role** → select `ec2-autotag-lambda-role`.
6. **Create function**.
7. In the **Code** tab, click `lambda_function.py` in the file tree, select all (Ctrl+A), delete, and paste the full code below.
8. Click **Deploy**.
9. Go to **Configuration → General configuration → Edit** → set **Timeout** to `30 sec` → **Save**.

#### Full `lambda_function.py`

```python
import boto3
import datetime
import json

ec2_client = boto3.client("ec2")
cloudtrail_client = boto3.client("cloudtrail")

DEFAULT_ENVIRONMENT = "Dev"


def get_launching_iam_user(instance_id, region=None):
    """
    BONUS: Look up CloudTrail for the RunInstances event that
    launched this instance and extract the IAM identity that did it.
    """
    try:
        response = cloudtrail_client.lookup_events(
            LookupAttributes=[
                {"AttributeKey": "EventName", "AttributeValue": "RunInstances"}
            ],
            MaxResults=20,
        )
        for event in response.get("Events", []):
            cloudtrail_event = json.loads(event["CloudTrailEvent"])
            instances = (
                cloudtrail_event.get("responseElements", {})
                .get("instancesSet", {})
                .get("items", [])
            )
            for inst in instances:
                if inst.get("instanceId") == instance_id:
                    identity = cloudtrail_event.get("userIdentity", {})
                    return (
                        identity.get("arn")
                        or identity.get("userName")
                        or identity.get("principalId")
                        or "Unknown"
                    )
        return "Unknown"
    except Exception as e:
        print(f"CloudTrail lookup failed: {e}")
        return "Unknown"


def lambda_handler(event, context):
    print("Received event:", json.dumps(event))

    # 1. Extract instance ID from the EventBridge event
    try:
        instance_id = event["detail"]["instance-id"]
    except KeyError:
        print("ERROR: instance-id not found in event detail")
        return {"statusCode": 400, "body": "Missing instance-id in event"}

    # 2. Build tag values
    launch_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    owner = get_launching_iam_user(instance_id)

    tags = [
        {"Key": "LaunchDate", "Value": launch_date},
        {"Key": "Environment", "Value": DEFAULT_ENVIRONMENT},
        {"Key": "Owner", "Value": owner},
    ]

    # 3. Apply tags
    try:
        ec2_client.create_tags(Resources=[instance_id], Tags=tags)
        print(
            f"SUCCESS: Tagged instance {instance_id} with "
            f"LaunchDate={launch_date}, Environment={DEFAULT_ENVIRONMENT}, Owner={owner}"
        )
    except Exception as e:
        print(f"ERROR: Failed to tag instance {instance_id}: {e}")
        raise

    return {"statusCode": 200, "body": f"Tagged {instance_id} successfully"}
```

#### CLI Commands (create + deploy directly, avoids console paste errors)

```bash
zip -j lambda_function.zip lambda_function.py

aws lambda create-function \
  --function-name ec2-autotag-on-launch \
  --runtime python3.12 \
  --role ROLE_ARN \
  --handler lambda_function.lambda_handler \
  --timeout 30 \
  --memory-size 128 \
  --zip-file fileb://lambda_function.zip

# To push updated code later
aws lambda update-function-code \
  --function-name ec2-autotag-on-launch \
  --zip-file fileb://lambda_function.zip
```

---

### Step 3: Create the EventBridge Rule

#### Console Navigation
1. Search **EventBridge** → **Rules** → **Create rule**.
2. Name: `ec2-autotag-on-running-rule`. Event bus: **default**. Rule type: **Rule with an event pattern** → **Next**.
3. Event source: **AWS events or EventBridge partner events**.
4. Under **Event pattern**, click **Custom pattern (JSON editor)** and paste the pattern below.
5. **Next** → Target type: **AWS service** → **Select a target: Lambda function** → choose `ec2-autotag-on-launch` → **Next** → **Next** → **Create rule**.

#### Event Pattern

`event-pattern.json`
```json
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["running"] }
}
```

#### CLI Commands

```bash
cat > event-pattern.json << 'EOF'
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["running"] }
}
EOF

aws events put-rule \
  --name ec2-autotag-on-running-rule \
  --event-pattern file://event-pattern.json \
  --state ENABLED

LAMBDA_ARN=$(aws lambda get-function \
  --function-name ec2-autotag-on-launch \
  --query 'Configuration.FunctionArn' --output text)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)

aws lambda add-permission \
  --function-name ec2-autotag-on-launch \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:$REGION:$ACCOUNT_ID:rule/ec2-autotag-on-running-rule

aws events put-targets \
  --rule ec2-autotag-on-running-rule \
  --targets "Id"="1","Arn"="$LAMBDA_ARN"
```

---

### Step 4: Testing

#### 4.1 Launch a Test Instance

Console:
1. **EC2 → Launch instance** → pick any free-tier AMI (e.g., Amazon Linux 2023) and `t2.micro`/`t3.micro`.
2. Launch with default settings.

CLI:
```bash
aws ec2 run-instances \
  --image-id ami-0abcdef1234567890 \
  --instance-type t2.micro \
  --count 1 \
  --key-name YOUR_KEY_PAIR
```

#### 4.2 Confirm Tags Appear

Wait 30–90 seconds after the instance reaches **running**, then check:

Console: **EC2 → Instances** → select the instance → **Tags** tab.

CLI:
```bash
aws ec2 describe-tags \
  --filters "Name=resource-id,Values=i-0123456789abcdef0"
```

#### 4.3 Verify Lambda Execution

Console: **CloudWatch → Log groups → /aws/lambda/ec2-autotag-on-launch** → open latest log stream → confirm `SUCCESS: Tagged instance ...`.

CLI:
```bash
aws logs tail /aws/lambda/ec2-autotag-on-launch --follow
```

#### 4.4 Manual Test with a Synthetic Event (console Test tab)

Go to your function → **Test** tab → **Create new event** → use this payload instead of the default `{}`:

```json
{
  "version": "0",
  "id": "test-event-id",
  "detail-type": "EC2 Instance State-change Notification",
  "source": "aws.ec2",
  "account": "123456789012",
  "time": "2026-07-14T10:00:00Z",
  "region": "us-east-1",
  "resources": ["arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0"],
  "detail": {
    "instance-id": "i-0123456789abcdef0",
    "state": "running"
  }
}
```

Or via CLI:
```bash
aws lambda invoke \
  --function-name ec2-autotag-on-launch \
  --payload '{"detail":{"instance-id":"i-0123456789abcdef0","state":"running"}}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
aws logs tail /aws/lambda/ec2-autotag-on-launch --since 2m
```

---

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ERROR: instance-id not found in event detail` on manual test | Ran the default blank `{}` test event | Use the synthetic event JSON in section 4.4 |
| No Lambda invocation at all | EventBridge rule pattern mismatch, or missing invoke permission | Re-check `event-pattern.json`; re-run `aws lambda add-permission` |
| Lambda runs but tags don't appear | IAM role missing `ec2:CreateTags`, or wrong instance ID | Check inline policy; check `detail.instance-id` in the logged event |
| `Owner` tag is always `Unknown` | CloudTrail lookup ran before the `RunInstances` event was indexed, or CloudTrail isn't logging management events in this region | Increase timeout / add retry, or check CloudTrail trail configuration |
| Lambda times out | `lookup_events` call is slow | Increase timeout to 30–60s, or restrict `LookupAttributes` further |
| **`NameError: name 'get_launching_iam_user' is not defined`** | The deployed `lambda_function.py` only has `lambda_handler` — the helper function got dropped during a console copy-paste, or **Deploy** wasn't clicked after pasting the full file | See dedicated fix below |

#### Fixing the `NameError: get_launching_iam_user is not defined`

This means the live code in Lambda doesn't match the intended file — almost always a partial console paste. The most reliable fix is to bypass the console editor and push the exact file via CLI.

**1. Verify what's actually deployed:**
```bash
aws lambda get-function --function-name ec2-autotag-on-launch --query 'Code.Location' --output text
```
Open that URL (or `curl -o current_code.zip "URL"`), unzip, and inspect `lambda_function.py` — confirm whether `get_launching_iam_user` is missing.

**2. Recreate the file locally exactly (CLI / CloudShell):**
```bash
cat > lambda_function.py << 'EOF'
<paste the full code from Step 2 above>
EOF

# Sanity check — should print BOTH function definitions
grep -n "^def " lambda_function.py
```
Expected output:
```
20:def get_launching_iam_user(instance_id, region=None):
55:def lambda_handler(event, context):
```

**3. Zip and push directly to Lambda:**
```bash
zip -j lambda_function.zip lambda_function.py

aws lambda update-function-code \
  --function-name ec2-autotag-on-launch \
  --zip-file fileb://lambda_function.zip
```

**4. Confirm the update landed**, then re-run the test in section 4.4.

If only the console editor is available, refresh the Lambda page (F5) before pasting, paste the entire block in one action, verify the line count at the bottom-left of the editor matches ~60 lines, then click **Deploy**.

---

### Bonus: Owner Tag from CloudTrail (Launching IAM User)

Already implemented in `lambda_function.py` via `get_launching_iam_user()`. Key points:

- **How it works:** EC2 API calls like `RunInstances` are logged as management events in CloudTrail, including a `userIdentity` block and a `responseElements.instancesSet.items[]` array of the created instance IDs.
- **Matching logic:** The Lambda searches recent `RunInstances` CloudTrail events for one whose `instancesSet` contains the target instance ID, then reads `userIdentity.arn` (falling back to `userName` or `principalId`).
- **Caveats:**
  - CloudTrail indexing lag can cause a miss on very fast invocations.
  - `lookup_events` has a default search window and rate limits; high launch volume may need CloudTrail Lake or an S3/Athena-based approach instead.
  - Auto Scaling Group launches often show the ASG service-linked role as the "user," not a human.

#### Alternative (more efficient) Bonus Pattern

Trigger directly off the CloudTrail `RunInstances` event instead of doing a separate `lookup_events` call:

`cloudtrail-event-pattern.json`
```json
{
  "source": ["aws.ec2"],
  "detail-type": ["AWS API Call via CloudTrail"],
  "detail": {
    "eventSource": ["ec2.amazonaws.com"],
    "eventName": ["RunInstances"]
  }
}
```

Here, `event["detail"]["userIdentity"]["arn"]` gives you the Owner directly, and instance IDs come from `event["detail"]["responseElements"]["instancesSet"]["items"]` — no extra API call needed. Requires CloudTrail management events delivered to EventBridge (default in most modern accounts).

---

### Summary of Resources Created

| Resource | Name |
|---|---|
| IAM Role | `ec2-autotag-lambda-role` |
| IAM Inline Policy | `ec2-autotag-inline-policy` |
| Lambda Function | `ec2-autotag-on-launch` |
| EventBridge Rule | `ec2-autotag-on-running-rule` |

### Cleanup

```bash
aws events remove-targets --rule ec2-autotag-on-running-rule --ids "1"
aws events delete-rule --name ec2-autotag-on-running-rule
aws lambda delete-function --function-name ec2-autotag-on-launch
aws iam delete-role-policy --role-name ec2-autotag-lambda-role --policy-name ec2-autotag-inline-policy
aws iam detach-role-policy --role-name ec2-autotag-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name ec2-autotag-lambda-role
```

---

## Task 4: Daily AWS Cost Alert Using Cost Explorer API and SNS

### Objective
Build an automated alert when AWS spend exceeds a threshold.

### Note
The old CloudWatch "Billing" metric is legacy — it only exists in
`us-east-1` and must be manually enabled. The modern, interview-relevant
approach uses the **Cost Explorer API** (`ce:GetCostAndUsage`) instead.

### Instructions (as given)
1. **SNS Setup** — create a topic and subscribe your email (confirm the
   subscription email).
2. **Lambda IAM Role** — inline policy with `ce:GetCostAndUsage` and
   `sns:Publish` (scoped to your topic).
3. **Lambda Function (Boto3)**:
   1. Initialize `ce` and `sns` clients.
   2. Query month-to-date `UnblendedCost` with `get_cost_and_usage`.
   3. Compare against a threshold (e.g., $50).
   4. If exceeded, publish an SNS alert with the current spend.
   5. Print the retrieved amount for logging.
4. **EventBridge** — schedule daily.
5. **Testing** — trigger manually with a low threshold (e.g., $0.01) to
   force an alert.
6. **Discussion point** — mention AWS Budgets as the managed alternative
   and when custom Lambda logic wins (per-service breakdowns,
   Slack/Teams delivery, anomaly logic).

### Architecture

```
EventBridge (daily cron)
        │
        ▼
   Lambda function ──► ce.get_cost_and_usage()  (month-to-date UnblendedCost)
        │
        ▼ (if spend > threshold)
   sns.publish() ──► SNS Topic ──► Email subscriber
```

---

### STEP 0 — Enable Cost Explorer (one-time)

**Console navigation:**
1. Sign in to the AWS Console at `https://console.aws.amazon.com`.
2. Click the **search bar** at the top center.
3. Type `Billing and Cost Management` → click the matching result.
4. Left sidebar → click **Cost Explorer**.
5. If shown, click **Enable Cost Explorer**.
6. Wait up to 24 hours for the first-time historical backfill. After
   that, data refreshes roughly every 24 hours.

*(No CLI equivalent — one-time console-only toggle. This is why the
Lambda's month-to-date figure can lag by up to a day.)*

---

### STEP 1 — SNS Setup: Topic + Email Subscription

**Console navigation:**
1. Search bar → type `SNS` → click **Simple Notification Service**.
2. Left sidebar → **Topics** → click **Create topic**.
3. **Type** → select **Standard**.
4. **Name** → type `cost-alert-topic`.
5. Leave all other fields default → click **Create topic**.
6. Copy the **Topic ARN** shown at the top of the detail page.
7. On the same page, go to the **Subscriptions** tab → **Create
   subscription**.
8. **Protocol** → select **Email**.
9. **Endpoint** → type your email address → **Create subscription**.
10. Open your inbox → open the email from **AWS Notifications** →
    click **Confirm subscription**.
11. Back in the console, click the refresh icon on the Subscriptions
    table → confirm status is now `Confirmed`.

**CLI equivalent:**
```bash
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

TOPIC_ARN=$(aws sns create-topic --name cost-alert-topic --query TopicArn --output text)
echo $TOPIC_ARN

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "you@example.com"

# after clicking the confirmation link in your email:
aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN"
```

---

### STEP 2 — Lambda IAM Role

**Console navigation — create the role:**
1. Search bar → type `IAM` → click **IAM**.
2. Left sidebar → **Roles** → click **Create role**.
3. **Trusted entity type** → **AWS service**.
4. **Use case** → select **Lambda** → click **Next**.
5. Leave all managed policy checkboxes unchecked → click **Next**.
6. **Role name** → type `cost-alert-lambda-role` → click **Create
   role**.

**Console navigation — attach the inline policy:**
1. Click into `cost-alert-lambda-role`.
2. **Permissions** tab → **Add permissions** dropdown → **Create
   inline policy**.
3. Click the **JSON** tab in the policy editor.
4. Delete the placeholder and paste the JSON below (with your real
   region/account ID substituted).
5. Click **Next** → **Policy name** → type `cost-alert-inline-policy` →
   **Create policy**.
6. Copy the **Role ARN** from the role summary page (top of screen).

**Inline policy JSON** (`ce:GetCostAndUsage` + `sns:Publish` scoped to
your topic + basic Lambda logging):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerReadOnly",
      "Effect": "Allow",
      "Action": "ce:GetCostAndUsage",
      "Resource": "*"
    },
    {
      "Sid": "PublishToCostAlertTopic",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:REGION:ACCOUNT_ID:cost-alert-topic"
    },
    {
      "Sid": "BasicLambdaLogging",
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

**Trust policy JSON** (lets Lambda assume the role):
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

> `ce:GetCostAndUsage` requires `Resource: "*"` — Cost Explorer has no
> resource-level IAM permissions. `sns:Publish` is scoped to just your
> topic ARN, which is the real least-privilege boundary here.

**CLI equivalent:**
```bash
cat > trust-policy.json << 'EOF'
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
EOF

cat > inline-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerReadOnly",
      "Effect": "Allow",
      "Action": "ce:GetCostAndUsage",
      "Resource": "*"
    },
    {
      "Sid": "PublishToCostAlertTopic",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:REGION:ACCOUNT_ID:cost-alert-topic"
    },
    {
      "Sid": "BasicLambdaLogging",
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
EOF

sed -i.bak \
  -e "s/REGION/${AWS_REGION}/" \
  -e "s/ACCOUNT_ID/${ACCOUNT_ID}/" \
  inline-policy.json

aws iam create-role \
  --role-name cost-alert-lambda-role \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name cost-alert-lambda-role \
  --policy-name cost-alert-inline-policy \
  --policy-document file://inline-policy.json

ROLE_ARN=$(aws iam get-role --role-name cost-alert-lambda-role \
  --query Role.Arn --output text)
```

⏱️ Wait ~10 seconds after role creation — IAM is eventually consistent,
and Lambda creation may fail with an assume-role error if done too
fast.

---

### STEP 3 — Lambda Function (Boto3)

**Console navigation — create the function:**
1. Search bar → type `Lambda` → click **Lambda** → **Create function**.
2. Select **Author from scratch**.
3. **Function name** → `cost-alert-check`.
4. **Runtime** → **Python 3.12**.
5. Expand **Change default execution role** → **Use an existing role**
   → select `cost-alert-lambda-role`.
6. Click **Create function**.

**Console navigation — add the code:**
1. On the **Code** tab, select all boilerplate in the editor and
   delete it.
2. Paste in the code below.
3. Click **Deploy**.

**Console navigation — environment variables:**
1. **Configuration** tab → **Environment variables** → **Edit**.
2. **Add environment variable**: Key `SNS_TOPIC_ARN`, Value = your
   topic ARN from Step 1.
3. **Add environment variable**: Key `THRESHOLD`, Value `50`.
4. Click **Save**.

**Console navigation — timeout:**
1. **Configuration** tab → **General configuration** → **Edit**.
2. **Timeout** → change to `0 min 30 sec` (Cost Explorer calls can be
   slow).
3. Click **Save**.

**Full Lambda code** — satisfies all five sub-requirements: initialize
`ce`/`sns` clients, query month-to-date `UnblendedCost`, compare to
threshold, publish SNS alert if exceeded, print the retrieved amount:

```python
"""
AWS Cost Alert Lambda
----------------------
Queries month-to-date UnblendedCost via Cost Explorer (ce:GetCostAndUsage)
and publishes an SNS alert if spend exceeds a configured threshold.

Environment variables:
    SNS_TOPIC_ARN  - ARN of the SNS topic to publish alerts to (required)
    THRESHOLD      - Dollar threshold to alert above (default: "50")
"""

import os
import json
import datetime
import boto3

# 3.1 Initialize ce and sns clients
ce = boto3.client("ce")
sns = boto3.client("sns")


def _month_to_date_range(today=None):
    """Return (start, end) ISO date strings for the current month so far.

    Cost Explorer requires End to be strictly after Start, so if today is
    the 1st of the month we roll End forward by one day.
    """
    today = today or datetime.date.today()
    start = today.replace(day=1)
    end = today

    if start == end:
        end = start + datetime.timedelta(days=1)

    return start.isoformat(), end.isoformat()


def lambda_handler(event, context):
    threshold = float(os.environ.get("THRESHOLD", "50"))
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    start, end = _month_to_date_range()

    # 3.2 Query month-to-date UnblendedCost
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )

    result = response["ResultsByTime"][0]["Total"]["UnblendedCost"]
    amount = float(result["Amount"])
    unit = result["Unit"]

    # 3.5 Print the retrieved amount for logging (always, alert or not)
    print(f"Month-to-date spend: {amount:.2f} {unit} "
          f"(period {start} to {end}, threshold {threshold:.2f})")

    alert_sent = False

    # 3.3 Compare against threshold
    if amount > threshold:
        message = (
            "AWS Cost Alert\n"
            "==============\n\n"
            f"Month-to-date spend: {amount:.2f} {unit}\n"
            f"Threshold:           {threshold:.2f} {unit}\n"
            f"Billing period:      {start} to {end}\n\n"
            "This alert was generated by the ce:GetCostAndUsage Lambda check."
        )

        # 3.4 Publish SNS alert with current spend
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"AWS Cost Alert: ${amount:.2f} exceeds ${threshold:.2f}",
            Message=message,
        )
        alert_sent = True
        print("Threshold exceeded — alert published to SNS.")
    else:
        print("Spend is within threshold — no alert sent.")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "amount": amount,
            "unit": unit,
            "threshold": threshold,
            "period_start": start,
            "period_end": end,
            "alert_sent": alert_sent,
        }),
    }
```

**CLI equivalent:**
```bash
mkdir -p lambda && cd lambda
# paste the code above into lambda_function.py, then:
zip cost_alert.zip lambda_function.py
cd ..

aws lambda create-function \
  --function-name cost-alert-check \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --timeout 30 \
  --zip-file fileb://lambda/cost_alert.zip \
  --environment "Variables={SNS_TOPIC_ARN=$TOPIC_ARN,THRESHOLD=50}"
```

To change the threshold later without redeploying code:
```bash
aws lambda update-function-configuration \
  --function-name cost-alert-check \
  --environment "Variables={SNS_TOPIC_ARN=$TOPIC_ARN,THRESHOLD=100}"
```

---

### STEP 4 — EventBridge: Schedule Daily

**Console navigation:**
1. Search bar → type `EventBridge` → click **Amazon EventBridge**.
2. Left sidebar → **Rules** → confirm **Event bus** = `default` →
   click **Create rule**.
3. **Name** → `cost-alert-daily`.
4. **Rule type** → **Schedule** → **Next**.
5. **Schedule pattern**:
   - Rate-based: select **A schedule that runs at a regular rate** →
     `1` `Day(s)`, OR
   - Fixed time: select cron-based → enter `0 8 * * ? *` for daily at
     08:00 UTC.
6. Click **Next**.
7. **Target types** → **AWS service**.
8. **Select a target** → **Lambda function**.
9. **Function** → select `cost-alert-check` → **Next** → **Next** →
   **Create rule**.

   (The console auto-grants EventBridge permission to invoke the
   function — no manual step needed.)

10. Verify: Lambda → `cost-alert-check` → **Configuration → Triggers**
    tab → confirm `cost-alert-daily` is listed.

**CLI equivalent:**
```bash
aws events put-rule \
  --name cost-alert-daily \
  --schedule-expression "rate(1 day)"

aws lambda add-permission \
  --function-name cost-alert-check \
  --statement-id cost-alert-eventbridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/cost-alert-daily"

LAMBDA_ARN=$(aws lambda get-function --function-name cost-alert-check \
  --query Configuration.FunctionArn --output text)

aws events put-targets \
  --rule cost-alert-daily \
  --targets "Id"="1","Arn"="$LAMBDA_ARN"
```

---

### STEP 5 — Testing: Force an Alert with a Low Threshold

**Console navigation:**
1. Lambda → `cost-alert-check` → **Configuration → Environment
   variables → Edit** → change `THRESHOLD` to `0.01` → **Save**.
2. **Test** tab → **Create new test event** → name `manual-test` →
   leave body as `{}` → **Save**.
3. Click **Test**.
4. Confirm **Status: Succeeded**, `statusCode: 200` in the response.
5. Expand the **Function Logs** section → confirm you see the printed
   spend amount and `"Threshold exceeded — alert published to SNS."`
6. Check your email inbox for the alert (usually within 1–2 minutes).
7. Go back to **Configuration → Environment variables → Edit** → reset
   `THRESHOLD` to `50` → **Save**.

**CLI equivalent:**
```bash
aws lambda update-function-configuration \
  --function-name cost-alert-check \
  --environment "Variables={SNS_TOPIC_ARN=$TOPIC_ARN,THRESHOLD=0.01}"

aws lambda invoke \
  --function-name cost-alert-check \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json

aws logs tail /aws/lambda/cost-alert-check --since 5m --follow

# reset afterward
aws lambda update-function-configuration \
  --function-name cost-alert-check \
  --environment "Variables={SNS_TOPIC_ARN=$TOPIC_ARN,THRESHOLD=50}"
```

---

### STEP 6 — Discussion Point: AWS Budgets vs. Custom Lambda

**AWS Budgets** is the managed, no-code alternative — set a monthly
budget and threshold percentages, and AWS handles scheduling and
notification for you:

```bash
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget file://budget.json \
  --notifications-with-subscribers file://notifications.json
```

**Default to AWS Budgets** for a simple threshold alert — it's fully
managed, no Lambda cold starts, no IAM surface to maintain.

**Custom Lambda logic wins when you need:**
- **Per-service/tag breakdowns** — e.g. alert only if *EC2* specifically
  exceeds $X, using `GroupBy` in `get_cost_and_usage`, rather than total
  account spend.
- **Slack/Teams delivery** — Budgets only natively integrates with
  SNS/email/chatbot; a Lambda can `POST` directly to a Slack/Teams
  webhook with custom formatting.
- **Custom anomaly logic** — comparing today's spend against a trailing
  average or day-over-day delta, instead of a flat static threshold
  (AWS Cost Anomaly Detection covers some of this, but a Lambda gives
  full control over the statistical method).
- **Composite conditions** — e.g. alert only if total spend is high
  **and** a specific service crossed a limit **and** it's a weekday.

**Interview-ready framing:** *"I'd default to AWS Budgets for a simple
threshold alert — it's fully managed. I'd reach for a custom Lambda +
Cost Explorer setup when I need custom routing (Slack), granular
breakdowns, or non-trivial anomaly logic that Budgets can't express."*

---

### Common Pitfalls Checklist

- [ ] Subscription stuck on `Pending confirmation` → check spam folder.
- [ ] Lambda creation fails with assume-role error → wait longer after
      IAM role creation (eventual consistency).
- [ ] Test invocation times out → confirm timeout was set to 30 sec,
      not left at the 3-sec default.
- [ ] No test email received → confirm `THRESHOLD=0.01` was actually
      saved and `SNS_TOPIC_ARN` matches the confirmed topic.
- [ ] `AccessDenied` on `ce:GetCostAndUsage` → confirm the inline policy
      uses `Resource: "*"` for that specific action.
- [ ] Daily schedule doesn't fire → check **Configuration → Triggers**
      tab on the Lambda to confirm EventBridge is attached.

### Quick Reference — Console Search Terms

| Task                     | Search this in the AWS Console top bar |
|---------------------------|-----------------------------------------|
| Enable Cost Explorer      | `Billing and Cost Management`          |
| Create SNS topic          | `SNS`                                  |
| Create IAM role/policy    | `IAM`                                  |
| Create/edit Lambda        | `Lambda`                               |
| Create schedule           | `EventBridge`                          |
| View logs                 | `CloudWatch`                           |
| Managed alternative       | `AWS Budgets` (under Billing)          |

---

## Task 5: Restore an EC2 Instance from the Latest Snapshot

### Architecture Summary

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

### Objective
Automate disaster-recovery: rebuild an EC2 instance from its most recent EBS snapshot using a Lambda function.

---

### Prerequisites
- At least one EBS snapshot exists for the source instance's root volume (pairs well with a "Graded 2" scheduled-snapshot task).
- AWS CLI configured with sufficient permissions to create IAM roles and Lambda functions.

#### Step 0a — Create a Snapshot of the Source Instance's Root Volume (Console)

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

#### Step 0a — Create a Snapshot (CLI equivalent)

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

#### Step 0b — Configure the AWS CLI (if not already done)

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

### Step 1 — IAM Role for Lambda

#### Custom policy (`ec2-restore-policy.json`)

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

#### Console steps (detailed navigation)

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

#### CLI equivalent

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

### Step 2 — Lambda Function (Boto3)

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

#### Design notes
- Accepts either `instance_id` (auto-detects the root volume/device) or an explicit `volume_id` + `root_device_name`.
- `VirtualizationType: hvm` is required for current-gen instance types such as `t3.micro`.
- Uses the `image_available` waiter to block until the registered AMI is ready before calling `run_instances` — this can take 1-3 minutes, so **the Lambda timeout must be set to at least 300 seconds** (well above the 3-second default).
- Tags the new instance with `RestoredFrom=<snapshot-id>` for traceability, as required.

---

### Step 3 — Package and Deploy

#### Console steps (detailed navigation)

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

#### CLI equivalent

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

### Step 4 — Testing

#### Console
Lambda → `RestoreEC2FromSnapshot` → **Test** tab → create a new test event:

```json
{
  "instance_id": "i-0123456789abcdef0"
}
```

Run **Test**, then check the execution output and CloudWatch Logs for the printed new instance ID.

#### CLI

```bash
aws lambda invoke \
  --function-name RestoreEC2FromSnapshot \
  --payload '{"instance_id":"i-0123456789abcdef0"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
```

#### Verification

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

### Step 5 — Cleanup

#### Console steps (detailed navigation)

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

#### CLI equivalent

```bash
# Terminate the test instance
aws ec2 terminate-instances --instance-ids <NEW_INSTANCE_ID>

# Deregister the AMI created for the test
aws ec2 deregister-image --image-id <AMI_ID>
```

Terminating promptly avoids ongoing EC2 charges from test restores.

---

## Task 6: Audit S3 Buckets for Public Access and Notify

### Objective
Detect any S3 bucket that is publicly accessible and alert via SNS — checking **Block Public Access (BPA) configuration**, **bucket policy status**, and **ACL grants**, since new buckets have BPA enabled and ACLs disabled by default (as of April 2023).

### Architecture Diagram

```
                    ┌──────────────────────────┐
                    │  EventBridge Rule         │
                    │  (Scheduled: rate(1 day)) │
                    └────────────┬──────────────┘
                                 │ triggers
                                 v
                    ┌──────────────────────────┐
                    │  Lambda: AuditS3PublicAccess │
                    │                              │
                    │  1. list_buckets()           │
                    │  2. For each bucket:         │
                    │     - get_public_access_block│
                    │     - get_bucket_policy_status│
                    │     - get_bucket_acl         │
                    │  3. Flag public buckets      │
                    └────────────┬──────────────┘
                                 │ if public buckets found
                                 v
                    ┌──────────────────────────┐
                    │  SNS Topic:               │
                    │  S3PublicAccessAlerts     │
                    └────────────┬──────────────┘
                                 │ publish
                                 v
                    ┌──────────────────────────┐
                    │  Email Subscription       │
                    │  (security team inbox)    │
                    └──────────────────────────┘
```

### Prerequisites
- AWS CLI configured (`aws configure`) with permissions to create SNS topics, IAM roles, Lambda functions, and EventBridge rules.
- At least one S3 bucket in the account to audit (for meaningful test results).

---

### Step 1 — SNS Setup (Topic + Email Subscription)

#### Console steps (detailed navigation)

1. Open the **AWS Console** → search for and open **SNS**.
2. In the left sidebar, click **Topics**.
3. Click **Create topic** (top right).
4. **Type**: select **Standard**.
5. **Name**: `S3PublicAccessAlerts`.
6. (Optional) **Display name**: `S3-Public-Alert`.
7. Leave other settings default → click **Create topic**.
8. On the topic's detail page, click **Create subscription**.
9. **Protocol**: select **Email**.
10. **Endpoint**: enter your email address (e.g. `you@example.com`).
11. Click **Create subscription**.
12. Check your email inbox for a message titled **"AWS Notification - Subscription Confirmation"** → click **Confirm subscription** in that email.
13. Back in the SNS console, refresh the **Subscriptions** tab and confirm status shows `Confirmed`.
14. Copy the **Topic ARN** from the topic detail page (top of page) — you'll need it for the Lambda environment variable in Step 3.

#### CLI equivalent

```bash
# Create the topic
aws sns create-topic --name S3PublicAccessAlerts
# Note the TopicArn returned, e.g.:
# arn:aws:sns:us-east-1:123456789012:S3PublicAccessAlerts

# Subscribe your email
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:123456789012:S3PublicAccessAlerts \
  --protocol email \
  --notification-endpoint you@example.com

# Check your inbox and click "Confirm subscription", then verify:
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-east-1:123456789012:S3PublicAccessAlerts
```

---

### Step 2 — IAM Role for Lambda

#### Custom policy (`s3-audit-policy.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3AuditPermissions",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketPolicyStatus",
        "s3:GetBucketAcl"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SNSPublishPermission",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:123456789012:S3PublicAccessAlerts"
    }
  ]
}
```

> Replace the SNS `Resource` ARN with the one you copied in Step 1.

#### Console steps (detailed navigation)

**Create the custom policy:**
1. Open **IAM** → left sidebar → **Policies**.
2. Click **Create policy** (top right).
3. Click the **JSON** tab → delete placeholder → paste the policy JSON above (with your real SNS ARN).
4. Click **Next**.
5. **Policy name**: `S3AuditPolicy`.
6. Click **Create policy**.

**Create the role:**
7. Left sidebar → **Roles** → **Create role**.
8. **Trusted entity type**: **AWS service**.
9. **Use case**: **Lambda** → **Next**.
10. Search and check `S3AuditPolicy`.
11. Search and check `AWSLambdaBasicExecutionRole`.
12. Click **Next**.
13. **Role name**: `S3AuditLambdaRole`.
14. Click **Create role**.
15. Open the role and copy its **ARN** (needed in Step 3).

#### CLI equivalent

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
  --role-name S3AuditLambdaRole \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name S3AuditLambdaRole \
  --policy-name S3AuditPolicy \
  --policy-document file://s3-audit-policy.json

aws iam attach-role-policy \
  --role-name S3AuditLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

---

### Step 3 — Lambda Function (Boto3)

`lambda_function.py`:

```python
import boto3
import os

s3 = boto3.client('s3')
sns = boto3.client('sns')

SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

PUBLIC_ACL_URIS = (
    'http://acs.amazonaws.com/groups/global/AllUsers',
    'http://acs.amazonaws.com/groups/global/AuthenticatedUsers'
)

def lambda_handler(event, context):
    public_buckets = []

    buckets = s3.list_buckets()['Buckets']
    print(f"Auditing {len(buckets)} bucket(s)...")

    for bucket in buckets:
        name = bucket['Name']
        reasons = []

        # 1. Check Block Public Access configuration
        try:
            pab = s3.get_public_access_block(Bucket=name)['PublicAccessBlockConfiguration']
            if not all([
                pab.get('BlockPublicAcls'),
                pab.get('IgnorePublicAcls'),
                pab.get('BlockPublicPolicy'),
                pab.get('RestrictPublicBuckets')
            ]):
                reasons.append('Block Public Access is NOT fully enabled')
        except s3.exceptions.ClientError as e:
            code = e.response['Error']['Code']
            if code == 'NoSuchPublicAccessBlockConfiguration':
                reasons.append('No Block Public Access configuration set (defaults to open)')
            else:
                print(f"[{name}] Error checking public access block: {e}")

        # 2. Check bucket policy status (IsPublic flag)
        try:
            policy_status = s3.get_bucket_policy_status(Bucket=name)['PolicyStatus']
            if policy_status.get('IsPublic'):
                reasons.append('Bucket policy evaluates as PUBLIC (IsPublic=True)')
        except s3.exceptions.ClientError as e:
            code = e.response['Error']['Code']
            if code != 'NoSuchBucketPolicy':
                print(f"[{name}] Error checking policy status: {e}")

        # 3. Check ACL grants for AllUsers / AuthenticatedUsers
        try:
            acl = s3.get_bucket_acl(Bucket=name)
            for grant in acl.get('Grants', []):
                uri = grant.get('Grantee', {}).get('URI', '')
                if uri in PUBLIC_ACL_URIS:
                    grp = uri.rsplit('/', 1)[-1]
                    reasons.append(f"Public ACL grant: {grant['Permission']} to {grp}")
        except s3.exceptions.ClientError as e:
            print(f"[{name}] Error checking ACL: {e}")

        if reasons:
            public_buckets.append({'name': name, 'reasons': reasons})

    if public_buckets:
        lines = ["The following S3 bucket(s) are PUBLICLY ACCESSIBLE:\n"]
        for b in public_buckets:
            lines.append(f"• {b['name']}")
            for r in b['reasons']:
                lines.append(f"    - {r}")
        message = "\n".join(lines)

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="⚠️ S3 Public Access Alert",
            Message=message
        )
        print(message)
    else:
        print("No publicly accessible buckets found.")

    return {
        'statusCode': 200,
        'public_bucket_count': len(public_buckets),
        'public_buckets': [b['name'] for b in public_buckets]
    }
```

#### Design notes
- A bucket is flagged public if **any** of the three checks trip: BPA not fully enabled, bucket policy `IsPublic=True`, or an ACL grant to `AllUsers`/`AuthenticatedUsers` — matching the "or has Block Public Access disabled" requirement.
- Handles the case where a bucket has **no** public access block config at all (older buckets) — treated as public since it defaults to unrestricted.
- Handles the case where a bucket has **no** bucket policy (`NoSuchBucketPolicy`) — silently skipped, not an error.
- The SNS topic ARN is read from an environment variable rather than hardcoded, so the function is portable across accounts/regions.

#### Console steps (detailed navigation)

1. Open **Lambda** → **Create function**.
2. Select **Author from scratch**.
3. **Function name**: `AuditS3PublicAccess`.
4. **Runtime**: `Python 3.12`.
5. Expand **Change default execution role** → **Use an existing role** → select `S3AuditLambdaRole`.
6. Click **Create function**.
7. In **Code source**, replace the boilerplate with the code above → click **Deploy**.
8. Go to **Configuration** tab → **Environment variables** → **Edit**.
9. Click **Add environment variable**: Key = `SNS_TOPIC_ARN`, Value = your topic ARN from Step 1.
10. Click **Save**.
11. Still in **Configuration** → **General configuration** → **Edit** → set **Timeout** to `1 min 0 sec` (listing/checking many buckets can take longer than the 3-second default) → **Save**.

#### CLI equivalent

```bash
mkdir s3-audit-lambda && cd s3-audit-lambda
# place lambda_function.py in this directory
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name AuditS3PublicAccess \
  --runtime python3.12 \
  --role arn:aws:iam::<YOUR_ACCOUNT_ID>:role/S3AuditLambdaRole \
  --handler lambda_function.lambda_handler \
  --timeout 60 \
  --memory-size 128 \
  --environment "Variables={SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:S3PublicAccessAlerts}" \
  --zip-file fileb://function.zip
```

Redeploy after edits:

```bash
zip function.zip lambda_function.py
aws lambda update-function-code \
  --function-name AuditS3PublicAccess \
  --zip-file fileb://function.zip
```

---

### Step 4 — EventBridge: Schedule Daily

#### Console steps (detailed navigation)

1. Open **Amazon EventBridge** → left sidebar → **Rules**.
2. Click **Create rule**.
3. **Name**: `DailyS3PublicAccessAudit`.
4. **Event bus**: `default`.
5. **Rule type**: select **Schedule**.
6. Click **Next**.
7. **Schedule pattern**: select **A schedule that runs at a regular rate**.
8. Set **Rate expression**: `1` **Day(s)** (or use a Cron expression for a specific time, e.g. `cron(0 8 * * ? *)` for 8 AM UTC daily).
9. Click **Next**.
10. **Target type**: **AWS service**.
11. **Select a target**: **Lambda function**.
12. **Function**: select `AuditS3PublicAccess`.
13. Click **Next** → review → **Create rule**.

#### CLI equivalent

```bash
# Create the schedule rule (runs daily at 08:00 UTC)
aws events put-rule \
  --name DailyS3PublicAccessAudit \
  --schedule-expression "cron(0 8 * * ? *)" \
  --state ENABLED

# Grant EventBridge permission to invoke the Lambda
aws lambda add-permission \
  --function-name AuditS3PublicAccess \
  --statement-id AllowEventBridgeInvoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:123456789012:rule/DailyS3PublicAccessAudit

# Attach the Lambda as the rule's target
aws events put-targets \
  --rule DailyS3PublicAccessAudit \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:123456789012:function:AuditS3PublicAccess"
```

---

### Step 5 — Testing

> ⚠️ This step intentionally exposes a bucket publicly. Use a disposable test bucket with no sensitive data, and re-secure it immediately after confirming the alert.

#### Console steps (detailed navigation)

**Create/select a test bucket:**
1. Open **S3** → **Create bucket** (or select an existing empty test bucket).
2. **Bucket name**: e.g. `my-test-public-audit-bucket-<random>`.
3. Leave **Block all public access** checked for now → **Create bucket**.

**Disable Block Public Access:**
4. Open the test bucket → **Permissions** tab.
5. Under **Block public access (bucket settings)**, click **Edit**.
6. Uncheck **Block all public access**.
7. Type `confirm` in the field → click **Confirm**.

**Attach a public-read bucket policy:**
8. Still on the **Permissions** tab, scroll to **Bucket policy** → click **Edit**.
9. Paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "PublicReadTest",
         "Effect": "Allow",
         "Principal": "*",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::my-test-public-audit-bucket-<random>/*"
       }
     ]
   }
   ```
10. Click **Save changes**. AWS will show an "This bucket has public access" warning banner — expected for this test.

**Run the Lambda manually:**
11. Open **Lambda** → `AuditS3PublicAccess` → **Test** tab.
12. Create a test event (empty JSON `{}` is fine, the function doesn't require input) → click **Test**.
13. Check the execution results / **Monitor** → **View CloudWatch logs** — confirm the test bucket appears in the `public_buckets` list.
14. Check your email inbox for the SNS alert listing the bucket and the reason(s) it was flagged.

#### CLI equivalent

```bash
# Create a test bucket
aws s3api create-bucket --bucket my-test-public-audit-bucket-12345 --region us-east-1

# Disable Block Public Access
aws s3api put-public-access-block \
  --bucket my-test-public-audit-bucket-12345 \
  --public-access-block-configuration \
  BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false

# Attach a public-read bucket policy
cat > public-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadTest",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::my-test-public-audit-bucket-12345/*"
    }
  ]
}
EOF

aws s3api put-bucket-policy \
  --bucket my-test-public-audit-bucket-12345 \
  --policy file://public-policy.json

# Invoke the Lambda manually
aws lambda invoke \
  --function-name AuditS3PublicAccess \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
# Expect "public_buckets" to include my-test-public-audit-bucket-12345
```

#### Re-secure the test bucket immediately after confirming the alert

**Console:**
1. Test bucket → **Permissions** → **Bucket policy** → **Edit** → delete the policy JSON → **Save changes**.
2. **Permissions** → **Block public access (bucket settings)** → **Edit** → check **Block all public access** → type `confirm` → **Confirm**.
3. (Optional) Delete the test bucket entirely: **S3** → select bucket → **Delete** → type the bucket name to confirm.

**CLI:**

```bash
# Remove the public bucket policy
aws s3api delete-bucket-policy --bucket my-test-public-audit-bucket-12345

# Re-enable full Block Public Access
aws s3api put-public-access-block \
  --bucket my-test-public-audit-bucket-12345 \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Optional: delete the test bucket entirely
aws s3api delete-bucket --bucket my-test-public-audit-bucket-12345
```

---

### Cleanup Checklist
- [ ] Test bucket re-secured (BPA re-enabled, public policy removed) or deleted.
- [ ] Confirmed SNS email subscription is `Confirmed` (not `PendingConfirmation`).
- [ ] EventBridge rule `DailyS3PublicAccessAudit` is `ENABLED` for ongoing monitoring.
- [ ] Lambda timeout is sufficient for the number of buckets in the account (increase if you have hundreds of buckets — consider paginating `list_buckets` results for very large accounts).
