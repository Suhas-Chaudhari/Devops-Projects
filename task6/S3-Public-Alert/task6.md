# Task 6: Audit S3 Buckets for Public Access and Notify

## Objective
Detect any S3 bucket that is publicly accessible and alert via SNS — checking **Block Public Access (BPA) configuration**, **bucket policy status**, and **ACL grants**, since new buckets have BPA enabled and ACLs disabled by default (as of April 2023).

---

## Architecture Diagram

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

---

## Prerequisites
- AWS CLI configured (`aws configure`) with permissions to create SNS topics, IAM roles, Lambda functions, and EventBridge rules.
- At least one S3 bucket in the account to audit (for meaningful test results).

---

## Step 1 — SNS Setup (Topic + Email Subscription)

### Console steps (detailed navigation)

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

### CLI equivalent

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

## Step 2 — IAM Role for Lambda

### Custom policy (`s3-audit-policy.json`)

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

### Console steps (detailed navigation)

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

## Step 3 — Lambda Function (Boto3)

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

### Design notes
- A bucket is flagged public if **any** of the three checks trip: BPA not fully enabled, bucket policy `IsPublic=True`, or an ACL grant to `AllUsers`/`AuthenticatedUsers` — matching the "or has Block Public Access disabled" requirement.
- Handles the case where a bucket has **no** public access block config at all (older buckets) — treated as public since it defaults to unrestricted.
- Handles the case where a bucket has **no** bucket policy (`NoSuchBucketPolicy`) — silently skipped, not an error.
- The SNS topic ARN is read from an environment variable rather than hardcoded, so the function is portable across accounts/regions.

### Console steps (detailed navigation)

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

### CLI equivalent

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

## Step 4 — EventBridge: Schedule Daily

### Console steps (detailed navigation)

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

### CLI equivalent

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

## Step 5 — Testing

> ⚠️ This step intentionally exposes a bucket publicly. Use a disposable test bucket with no sensitive data, and re-secure it immediately after confirming the alert.

### Console steps (detailed navigation)

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

### CLI equivalent

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

### Re-secure the test bucket immediately after confirming the alert

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

## Cleanup Checklist
- [ ] Test bucket re-secured (BPA re-enabled, public policy removed) or deleted.
- [ ] Confirmed SNS email subscription is `Confirmed` (not `PendingConfirmation`).
- [ ] EventBridge rule `DailyS3PublicAccessAudit` is `ENABLED` for ongoing monitoring.
- [ ] Lambda timeout is sufficient for the number of buckets in the account (increase if you have hundreds of buckets — consider paginating `list_buckets` results for very large accounts).