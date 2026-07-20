# Project 1: Automated S3 Bucket Cleanup (Objects Older Than 30 Days)

## Objective
Automatically delete stale objects (older than 30 days) from an S3 bucket using a scheduled/manually-triggered Lambda function, with least-privilege IAM permissions.

## Architecture
```
[Manual Trigger / EventBridge Schedule] → [Lambda Function] → [S3 Bucket]
                                                ↓
                                          CloudWatch Logs
```

---

## Step 1: S3 Bucket Setup

### AWS Console Navigation
1. Sign in to the **AWS Management Console**.
2. In the top search bar, type **S3** and open the **S3** service.
3. Click **Create bucket**.
4. **Bucket name:** `my-cleanup-demo-bucket` (must be globally unique — add your own suffix, e.g. initials or numbers).
5. **AWS Region:** choose your working region (e.g., `us-east-1`).
6. Leave **Block all public access** checked (default — keep it on).
7. Leave other settings default, scroll down, click **Create bucket**.
8. Open the bucket → click **Upload** → **Add files** → select 3–4 test files (e.g., `file1.txt`, `file2.txt`, `file3.txt`,`file4.txt`,`file5.txt`) → click **Upload**.

### CLI Equivalent
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

## Step 2: Lambda IAM Role

### AWS Console Navigation
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

### Trust Policy (created automatically by console; shown here for CLI users)
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

### Inline Permissions Policy — scoped to one bucket
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

### CLI Equivalent
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

## Step 3: Lambda Function (Python 3.12, Boto3)

### AWS Console Navigation
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

### `lambda_function.py`
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

### CLI Equivalent (package + deploy)
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

## Step 4: Testing

### Phase A — Test with minutes threshold

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

### Phase B — Reset to production threshold

**Console:** Configuration → Environment variables → **Edit** → delete the `AGE_THRESHOLD_MINUTES` variable entirely (leave `AGE_THRESHOLD_DAYS=30`) → **Save**.

**CLI:**
```bash
aws lambda update-function-configuration \
  --function-name s3-stale-object-cleanup \
  --environment "Variables={BUCKET_NAME=my-cleanup-demo-bucket,AGE_THRESHOLD_DAYS=1}"
```

### Checking CloudWatch Logs (Console)
1. Search bar → **CloudWatch** → **Log groups**.
2. Find `/aws/lambda/s3-stale-object-cleanup`.
3. Open the latest **Log stream** to view scanned/deleted counts and the list of deleted keys.

---

## Step 5 (Optional): Schedule with EventBridge instead of manual trigger

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

## Step 6: Discussion Point — Lambda vs. S3 Lifecycle Rules

**S3 Lifecycle Rules** (Bucket → Management tab → Create lifecycle rule) handle plain age-based expiration natively — no code, no compute cost, no maintenance, and AWS runs the sweep on your behalf on a nightly-ish schedule. For a simple "delete everything older than N days" requirement, this is almost always the right default.

**Use Lambda instead when you need:**
1. **Conditional logic** lifecycle rules can't express — e.g., "delete only if there's no matching entry in a DynamoDB table" or "keep the 5 newest versions per customer regardless of age."
2. **Naming-pattern or metadata-driven filtering** beyond lifecycle's prefix/tag filters — e.g., regex-based key matching or logic based on tags set dynamically by another system.
3. **Cross-service actions** tied to the deletion — e.g., delete the object *and* publish an SNS alert, write an audit log entry, or update a search index — since lifecycle rules can only delete/transition, not fan out to other services.

---

## Cleanup (avoid ongoing charges)
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