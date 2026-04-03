import boto3
import json
from datetime import datetime, timezone
import os

# Environment variables provided by CDK LambdaStack
BUCKET_NAME = os.environ['BUCKET_NAME']
TABLE_NAME = os.environ['TABLE_NAME']

# Initialize AWS clients
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-west-2'))
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Main handler for Size Tracking Lambda.
    Triggered by SQS which receives fan-out events from SNS via S3.
    """
    try:
        # SQS events contain a 'body' string which is the SNS message
        body = json.loads(event['Records'][0]['body'])
        # SNS 'Message' field contains the actual S3 event notification
        message = json.loads(body['Message'])
        s3_record = message['Records'][0]
        key = s3_record['s3']['object']['key']

        # Prevent feedback loop: 
        # If the tracking logic generates a plot and saves it back to the same bucket,
        # it could trigger itself indefinitely.
        if key == 'plot.png':
            print("Ignore plot.png update to avoid feedback loop")
            return
        
    except Exception as e:
        print(f"Error parsing S3 event: {e}")
        return {'statusCode': 400, 'body': 'Parsing Error'}

    # Recalculate the current state of the bucket
    total_size = 0
    total_objects = 0

    # List all objects to compute total metrics
    # Note: list_objects_v2 has a 1000 object limit; for larger buckets, use paginator
    response = s3.list_objects_v2(Bucket=BUCKET_NAME)

    if 'Contents' in response:
        for obj in response['Contents']:
            total_size += obj['Size']
            total_objects += 1

    # Generate UTC timestamp for DynamoDB Sort Key
    timestamp = int(datetime.now(timezone.utc).timestamp())

    # Persistence layer: Store metadata in DynamoDB
    # 'gsi_pk' is used for the Global Secondary Index to allow sorting across all records
    table.put_item(
        Item={
            'bucket_name': BUCKET_NAME,
            'timestamp': timestamp,
            'total_size': total_size,
            'total_objects': total_objects,
            'object_name': key,
            "gsi_pk": "all"
        }
    )

    print(f'Update successful: {total_size} bytes across {total_objects} objects.')

    return {
        'statusCode': 200,
        'body': json.dumps({
            'bucket': BUCKET_NAME,
            'total_size': total_size,
            'last_object': key
        })
    }
