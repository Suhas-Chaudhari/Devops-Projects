# Auto-Tagging EC2 Instances on Launch

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

## Step 1: Create the IAM Role for Lambda

### Console Navigation
1. Search **IAM** in the top search bar → open it.
2. Left sidebar → **Roles** → **Create role**.
3. Trusted entity type: **AWS service**.
4. Use case: search and select **Lambda** → **Next**.
5. Skip attaching managed policies → **Next**.
6. Role name: `ec2-autotag-lambda-role` → **Create role**.
7. Click into the new role → **Add permissions** → **Create inline policy**.
8. Switch to the **JSON** tab, paste the policy below.
9. **Next** → Policy name: `ec2-autotag-inline-policy` → **Create policy**.

### Trust Policy

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

### Inline Permissions Policy

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

### CLI Commands

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

## Step 2: Create the Lambda Function

### Console Navigation
1. Search **Lambda** → **Functions** → **Create function**.
2. Choose **Author from scratch**.
3. Function name: `ec2-autotag-on-launch`.
4. Runtime: **Python 3.12**.
5. Permissions → **Use an existing role** → select `ec2-autotag-lambda-role`.
6. **Create function**.
7. In the **Code** tab, click `lambda_function.py` in the file tree, select all (Ctrl+A), delete, and paste the full code below.
8. Click **Deploy**.
9. Go to **Configuration → General configuration → Edit** → set **Timeout** to `30 sec` → **Save**.

### Full `lambda_function.py`

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

### CLI Commands (create + deploy directly, avoids console paste errors)

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

## Step 3: Create the EventBridge Rule

### Console Navigation
1. Search **EventBridge** → **Rules** → **Create rule**.
2. Name: `ec2-autotag-on-running-rule`. Event bus: **default**. Rule type: **Rule with an event pattern** → **Next**.
3. Event source: **AWS events or EventBridge partner events**.
4. Under **Event pattern**, click **Custom pattern (JSON editor)** and paste the pattern below.
5. **Next** → Target type: **AWS service** → **Select a target: Lambda function** → choose `ec2-autotag-on-launch` → **Next** → **Next** → **Create rule**.

### Event Pattern

`event-pattern.json`
```json
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["running"] }
}
```

### CLI Commands

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

## Step 4: Testing

### 4.1 Launch a Test Instance

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

### 4.2 Confirm Tags Appear

Wait 30–90 seconds after the instance reaches **running**, then check:

Console: **EC2 → Instances** → select the instance → **Tags** tab.

CLI:
```bash
aws ec2 describe-tags \
  --filters "Name=resource-id,Values=i-0123456789abcdef0"
```

### 4.3 Verify Lambda Execution

Console: **CloudWatch → Log groups → /aws/lambda/ec2-autotag-on-launch** → open latest log stream → confirm `SUCCESS: Tagged instance ...`.

CLI:
```bash
aws logs tail /aws/lambda/ec2-autotag-on-launch --follow
```

### 4.4 Manual Test with a Synthetic Event (console Test tab)

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

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ERROR: instance-id not found in event detail` on manual test | Ran the default blank `{}` test event | Use the synthetic event JSON in section 4.4 |
| No Lambda invocation at all | EventBridge rule pattern mismatch, or missing invoke permission | Re-check `event-pattern.json`; re-run `aws lambda add-permission` |
| Lambda runs but tags don't appear | IAM role missing `ec2:CreateTags`, or wrong instance ID | Check inline policy; check `detail.instance-id` in the logged event |
| `Owner` tag is always `Unknown` | CloudTrail lookup ran before the `RunInstances` event was indexed, or CloudTrail isn't logging management events in this region | Increase timeout / add retry, or check CloudTrail trail configuration |
| Lambda times out | `lookup_events` call is slow | Increase timeout to 30–60s, or restrict `LookupAttributes` further |
| **`NameError: name 'get_launching_iam_user' is not defined`** | The deployed `lambda_function.py` only has `lambda_handler` — the helper function got dropped during a console copy-paste, or **Deploy** wasn't clicked after pasting the full file | See dedicated fix below |

### Fixing the `NameError: get_launching_iam_user is not defined`

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

## Bonus: Owner Tag from CloudTrail (Launching IAM User)

Already implemented in `lambda_function.py` via `get_launching_iam_user()`. Key points:

- **How it works:** EC2 API calls like `RunInstances` are logged as management events in CloudTrail, including a `userIdentity` block and a `responseElements.instancesSet.items[]` array of the created instance IDs.
- **Matching logic:** The Lambda searches recent `RunInstances` CloudTrail events for one whose `instancesSet` contains the target instance ID, then reads `userIdentity.arn` (falling back to `userName` or `principalId`).
- **Caveats:**
  - CloudTrail indexing lag can cause a miss on very fast invocations.
  - `lookup_events` has a default search window and rate limits; high launch volume may need CloudTrail Lake or an S3/Athena-based approach instead.
  - Auto Scaling Group launches often show the ASG service-linked role as the "user," not a human.

### Alternative (more efficient) Bonus Pattern

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

## Summary of Resources Created

| Resource | Name |
|---|---|
| IAM Role | `ec2-autotag-lambda-role` |
| IAM Inline Policy | `ec2-autotag-inline-policy` |
| Lambda Function | `ec2-autotag-on-launch` |
| EventBridge Rule | `ec2-autotag-on-running-rule` |

## Cleanup

```bash
aws events remove-targets --rule ec2-autotag-on-running-rule --ids "1"
aws events delete-rule --name ec2-autotag-on-running-rule
aws lambda delete-function --function-name ec2-autotag-on-launch
aws iam delete-role-policy --role-name ec2-autotag-lambda-role --policy-name ec2-autotag-inline-policy
aws iam detach-role-policy --role-name ec2-autotag-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name ec2-autotag-lambda-role
```