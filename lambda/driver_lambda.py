import boto3
import time
import requests
import os
import json

# Environment variables to target specific resources
BUCKET_NAME = os.environ['BUCKET_NAME']
PLOTTING_API_URL = os.environ['PLOTTING_API_URL']

print(f'Starting Driver Test. Target Plot API URL: {PLOTTING_API_URL}')

# Initialize S3 client for simulation
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

def lambda_handler(event, context):
    """
    Simulation Driver Lambda.
    This function automates the 'Upload -> Trigger Alarm -> Auto Cleanup' cycle
    to verify that the end-to-end infrastructure is functioning correctly.
    """

    # 1. First Upload: Small baseline file (approx 18 bytes)
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key="assignment1.txt",
        Body="Empty Assignment 1".encode('utf-8')
    )
    print("Step 1: Created assignment1.txt (18 bytes).")

    # Short sleep to ensure DynamoDB timestamps are distinct for plotting
    time.sleep(2)

    # 2. Second Upload: Larger file to push total size over the 20-byte threshold
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key="assignment2.txt",
        Body="Empty Assignment 2222222222".encode('utf-8')
    )
    print("Step 2: Created assignment2.txt (28 bytes). Total size > 20-byte Alarm limit.")

    # 3. Wait for Infrastructure Reaction
    time.sleep(100)

    # 4. Third Upload: Trigger a second cleanup cycle
    # At this point, assignment2.txt should have been deleted by the Cleaner.
    # Current bucket expected state: assignment1 (18 bytes) + assignment3 (2 bytes) = 20 bytes.
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key="assignment3.txt",
        Body="33".encode('utf-8')
    )
    print("Step 3: Created assignment3.txt (2 bytes). Pushing total size back over 20 bytes.")

    # Wait for the second Alarm/Cleanup cycle
    print("Waiting 75s for the second auto-cleanup cycle...")
    time.sleep(75)

    # 5. Final Verification: Invoke the Plotting API
    # This verifies that the API Gateway and Plotting Lambda can still generate
    # the chart after cleanup actions have occurred.
    try:
        print(f"Requesting visualization from: {PLOTTING_API_URL}")
        response = requests.get(PLOTTING_API_URL, timeout=10)

        if response.status_code == 200:
            print("Success: Plotting Lambda invoked and returned image data.")
        else:
            print(f"Warning: Plotting API returned status {response.status_code}. Details: {response.text}")
    except Exception as e:
        print(f"Error: Connection to Plotting API failed: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Simulation sequence completed.",
            "status": "Check S3/DynamoDB for final cleanup state."
        })
    }