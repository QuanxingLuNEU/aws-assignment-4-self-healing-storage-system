import boto3
import os
import json

# Initialize AWS SDK clients
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

# Environment variables injected via LambdaStack
TABLE_NAME = os.environ['TABLE_NAME']
BUCKET_NAME = os.environ['BUCKET_NAME']
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Auto-Cleanup Handler triggered by CloudWatch Alarm.
    Purpose: When the bucket exceeds the 20Bytes threshold (defined in MonitoringStack),
    this function identifies and deletes the largest recorded file to free up space.
    """
    print("CloudWatch Alarm triggered: Starting storage cleanup process...")
    
    try:
        # 1. Query the Global Secondary Index (GSI) 'size-index'
        # We query the static partition key 'all' to look across all recorded objects.
        # ScanIndexForward=False ensures we get the largest 'size' values first (Descending).
        response = table.query(
            IndexName='size-index',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('gsi_pk').eq('all'),
            ScanIndexForward=False, # False = Descending (Largest first)
            Limit=1
        )
        
        items = response.get('Items', [])
        if not items:
            print("Cleanup aborted: No file records found in DynamoDB.")
            return {
                'statusCode': 200,
                'body': 'No items to clean'
            }
        
        # Extract the record for the largest object
        target_record = items[0]
        object_key = target_record.get('object_name')
        
        # 2. Delete the target object from S3
        # This action will trigger a new S3 event, which will eventually update the metrics again.
        print(f"Cleanup Action: Deleting largest object '{object_key}' from bucket '{BUCKET_NAME}'.")
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=object_key)
        
        # 3. Synchronize DynamoDB: Remove the metadata entry for the deleted object
        # Note: We use the Table's primary keys (bucket_name and timestamp) for the delete operation.
        table.delete_item(
            Key={
                'bucket_name': target_record['bucket_name'], 
                'timestamp': target_record['timestamp']
            }
        )

    except Exception as e:
        print(f"Critical error during cleanup execution: {str(e)}")
        # Re-raising ensures the Lambda execution is marked as failed in CloudWatch metrics
        raise e
    
    return {
        'statusCode': 200,
        'body': json.dumps(f"Successfully deleted {object_key}")
    }