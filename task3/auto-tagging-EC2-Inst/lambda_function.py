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