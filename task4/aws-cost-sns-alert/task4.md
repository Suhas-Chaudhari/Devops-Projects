# Task 4: Daily AWS Cost Alert Using Cost Explorer API and SNS

## Objective
Build an automated alert when AWS spend exceeds a threshold.

## Note
The old CloudWatch "Billing" metric is legacy — it only exists in
`us-east-1` and must be manually enabled. The modern, interview-relevant
approach uses the **Cost Explorer API** (`ce:GetCostAndUsage`) instead.

## Instructions (as given)
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

---

## Architecture

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

# STEP 0 — Enable Cost Explorer (one-time)

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

# STEP 1 — SNS Setup: Topic + Email Subscription

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

# STEP 2 — Lambda IAM Role

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

# STEP 3 — Lambda Function (Boto3)

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

# STEP 4 — EventBridge: Schedule Daily

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

# STEP 5 — Testing: Force an Alert with a Low Threshold

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

# STEP 6 — Discussion Point: AWS Budgets vs. Custom Lambda

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

## Common Pitfalls Checklist

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

## Quick Reference — Console Search Terms

| Task                     | Search this in the AWS Console top bar |
|---------------------------|-----------------------------------------|
| Enable Cost Explorer      | `Billing and Cost Management`          |
| Create SNS topic          | `SNS`                                  |
| Create IAM role/policy    | `IAM`                                  |
| Create/edit Lambda        | `Lambda`                               |
| Create schedule           | `EventBridge`                          |
| View logs                 | `CloudWatch`                           |
| Managed alternative       | `AWS Budgets` (under Billing)          |