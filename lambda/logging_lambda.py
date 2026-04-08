import json
import boto3
from datetime import datetime, timedelta
import os

# Initialize CloudWatch Logs client to search historical logs
# This is used to recover the size of deleted objects for accurate metrics
logs_client = boto3.client('logs', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

def lambda_handler(event, context):
    """
    Main handler that processes S3 events delivered via SQS.
    It logs object metadata in JSON format so CloudWatch Metric Filters can 
    calculate the 'TotalObjectSize' across the bucket.
    """
    for record in event['Records']:
        try:
            # SQS body is a string containing the SNS message
            sqs_body = json.loads(record['body'])
            
            # SNS wraps the S3 event notification inside the 'Message' field
            if 'Message' in sqs_body:
                s3_event_wrap = json.loads(sqs_body['Message'])
            else:
                s3_event_wrap = sqs_body

            # Validate if the message contains valid S3 records
            if 'Records' not in s3_event_wrap:
                continue

            for s3_record in s3_event_wrap['Records']:
                event_name = s3_record['eventName']
                object_name = s3_record['s3']['object']['key']

                if object_name == 'plot.png':
                    print(f"Skipping monitoring for system file: {object_name}")
                    continue
                
                # We calculate 'size_delta' to represent the change in bucket storage
                size_delta = 0

                # Case A: Object Created (S3 event provides the positive size)
                if 'ObjectCreated' in event_name:
                    size_delta = s3_record['s3']['object'].get('size', 0)
                
                # Case B: Object Removed (S3 removal events do NOT include the object size)
                elif 'ObjectRemoved' in event_name:
                    # To keep the 'TotalSize' metric accurate, we must subtract the original size.
                    # We query historical logs to find the size when this object was first uploaded.
                    historical_size = get_historical_size(object_name, context.log_group_name)
                    # For deletions, the delta must be negative
                    size_delta = -historical_size

                # Log output in structured JSON format. 
                # The Metric Filter in CDK will look for the $.size_delta key.
                log_output = {
                    "object_name": object_name,
                    "size_delta": size_delta,
                    "event_type": event_name,
                    "timestamp": datetime.now().isoformat()
                }

                # Standard print goes to CloudWatch Logs where it is parsed by the Filter
                print(json.dumps(log_output))

        except Exception as e:
            print(f"Error processing individual SQS record: {e}")

    return {'statusCode': 200}

def get_historical_size(object_name, log_group_name):
    """
    Queries the current Lambda's Log Group to find the previous 'ObjectCreated' 
    log for this specific object name to retrieve its size.
    """
    try:
        # Define search window (e.g., last 1 hour to find the original upload size)
        # Note: In production, a longer window or a DB lookup would be safer.
        start_time = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        
        # Filter Pattern: Find logs where object_name matches and it was an upload (delta > 0)
        response = logs_client.filter_log_events(
            logGroupName=log_group_name,
            filterPattern=f'{{ $.object_name = "{object_name}" && $.size_delta > 0 }}',
            startTime=start_time
        )
        
        events = response.get('events', [])
        if events:
            # Parse the most recent matching log entry
            matched_log = json.loads(events[0]['message'])
            return matched_log.get('size_delta', 0)
            
    except Exception as e:
        # If lookup fails, we return 0 to avoid crashing, though the metric may drift slightly
        print(f"Lookup failed for {object_name}: {e}")
    
    return 0