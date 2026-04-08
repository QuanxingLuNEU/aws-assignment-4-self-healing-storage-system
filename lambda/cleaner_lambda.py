import boto3
import os
import json
import time

# Initialize AWS SDK clients
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

# Environment variables injected via LambdaStack
BUCKET_NAME = os.environ['BUCKET_NAME']

def lambda_handler(event, context):
    """
    Auto-Cleanup Handler triggered by CloudWatch Alarm.
    Purpose: When the bucket exceeds the 20Bytes threshold (defined in MonitoringStack),
    this function identifies and deletes the largest recorded file to free up space.
    """
    print("CloudWatch Alarm triggered: Starting storage cleanup process...")
    
    try:
        # 1. List objects currently in the bucket to get real-time state
        response = s3_client.list_objects_v2(Bucket=BUCKET_NAME)
        
        if 'Contents' not in response or not response['Contents']:
            print("Cleanup aborted: No files found in S3 bucket.")
            return {'statusCode': 200, 'body': 'Bucket is empty'}
        
        # 2. Sort objects by actual size in descending order to find the largest
        # This ensures we pick assignment1 (18B) even if old 45B records exist in DDB
        sorted_items = sorted(response['Contents'], key=lambda x: x['Size'], reverse=True)
        target_obj = sorted_items[0]
        object_key = target_obj['Key']

        # 3. Artificial delay to allow Tracking Lambda to record the high-water mark
        print(f"DEBUG: Delaying 2s to capture peak before deleting {object_key}")
        time.sleep(2)

        # 4. Perform the deletion from S3
        print(f"Cleanup Action: Deleting largest object '{object_key}' ({target_obj['Size']} bytes)")
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=object_key)
        
        # 5. DO NOT delete from DynamoDB here. 
        # Keeping DDB records is essential for the Plotting Lambda to show history.

    except Exception as e:
        print(f"Critical error during cleanup execution: {str(e)}")
        # Re-raising ensures the Lambda execution is marked as failed in CloudWatch metrics
        raise e
    
    return {
        'statusCode': 200,
        'body': json.dumps(f"Successfully deleted {object_key}")
    }