import boto3
import json
from datetime import datetime, timezone
import matplotlib
# Use 'Agg' backend for non-interactive environments like AWS Lambda
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
from decimal import Decimal
import os
import time

# Environment variables injected by CDK
BUCKET_NAME = os.environ['BUCKET_NAME']
TABLE_NAME = os.environ['TABLE_NAME']

# Initialize AWS resource clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-west-2'))
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

def lambda_handler(event, context):
    """
    Handler for Plotting Lambda.
    Generates a PNG chart of bucket size changes over the last 300 seconds 
    and adds a horizontal reference line for the historical maximum size.
    """
    now = time.time()
    time_window_start = Decimal(str(now - 300))

    # 1. Fetch recent records for the current bucket
    # We use the primary Partition Key (bucket_name) and Sort Key (timestamp)
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('bucket_name').eq(BUCKET_NAME) &
                               boto3.dynamodb.conditions.Key('timestamp').gte(time_window_start)
    )
    items = response.get('Items', [])
    # Ensure data points are sorted chronologically for the line plot
    items.sort(key=lambda x: float(x['timestamp']))
    
    if not items:
        return {
            'statusCode': 200, 
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps('No data points found in the last 10 seconds.')
        }

    # Prepare data for Matplotlib
    timestamps = [datetime.fromtimestamp(float(i['timestamp']), tz=timezone.utc) for i in items]
    # DynamoDB numeric types are returned as Decimal; convert to int for plotting
    # Note: Ensure key name matches your tracking lambda (e.g., 'total_size')
    sizes = [int(i['total_size']) if isinstance(i['total_size'], Decimal) else i.get('total_size', 0) for i in items]

    # 2. Retrieve the global maximum size recorded (across all buckets)
    # This uses the GSI with 'ScanIndexForward=False' to pick the single largest entry
    max_size = 0
    try:
        gsi_response = table.query(
            IndexName='size-index', 
            KeyConditionExpression=boto3.dynamodb.conditions.Key('gsi_pk').eq('all'),
            ScanIndexForward=False,
            Limit=1
        )
        
        gsi_items = gsi_response.get('Items', [])
        if gsi_items:
            max_size_ever = int(gsi_items[0]['total_size']) if isinstance(gsi_items[0]['total_size'], Decimal) else gsi_items[0].get('total_size', 0)
    except Exception as e:
        print(f"GSI Query for max_size failed: {e}")

    # 3. Visualization Logic
    plt.figure(figsize=(8, 5))
    plt.plot(timestamps, sizes, marker='o', linestyle='-', color='blue', label=f'Current: {BUCKET_NAME}')
    
    # Add a horizontal dashed line to show the historical peak for context
    plt.axhline(y=max_size_ever, color='red', linestyle='--', label='Global Max Size')
    
    plt.xlabel('Time (UTC)')
    plt.ylabel('Size (Bytes)')
    plt.title('Real-time Storage Monitor (Last 300s)')
    plt.legend(loc='upper left')
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.tight_layout()

    # 4. Output Processing
    # Save the plot to an in-memory byte buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    plt.close()
    buf.seek(0)

    # Persistence: Save the generated plot back to S3 for static access
    # Warning: Ensure the Tracking Lambda ignores 'plot.png' to prevent an infinite trigger loop!
    s3.put_object(Bucket=BUCKET_NAME, Key='plot.png', Body=buf, ContentType='image/png')

    # API Response: Encode the binary image as Base64 for transit via API Gateway
    buf.seek(0)
    img_bytes = buf.read()
    encoded_string = base64.b64encode(img_bytes).decode('utf-8')

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "image/png",
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
        "isBase64Encoded": True,
        "body": encoded_string
    }