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