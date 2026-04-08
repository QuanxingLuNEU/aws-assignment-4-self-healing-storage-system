import boto3
import time
import requests
import os
import json
import traceback

# Environment variables to target specific resources
BUCKET_NAME = os.environ['BUCKET_NAME']
PLOTTING_API_URL = os.environ['PLOTTING_API_URL']

print(f'Starting Driver Test. Target Plot API URL: {PLOTTING_API_URL}')

# Initialize S3 client for simulation
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

def wait_for_alarm_status(target_status, timeout):
    cw = boto3.client('cloudwatch')
    start = time.time()
    alarm_name = 'TotalSizeAlarm'

    while time.time() - start < timeout:
        res = cw.describe_alarms(AlarmNames=[alarm_name])

        if not res['MetricAlarms']:
            all_alarms = cw.describe_alarms(MaxRecords=10)
            names = [a['AlarmName'] for a in all_alarms['MetricAlarms']]
            print(f"Error: Alarm '{alarm_name}' not found. Available alarms: {names}")
            time.sleep(10)
            continue

        current = res['MetricAlarms'][0]['StateValue']
        if current == target_status:
            return True
        time.sleep(10)
    return False

def wait_for_s3_object_to_disappear(key, timeout):
    start = time.time()
    while time.time() - start < timeout:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        keys = [obj['Key'] for obj in response.get('Contents', [])]
        if key not in keys:
            return True
        time.sleep(5)
    return False

def lambda_handler(event, context):
    """
    Simulation Driver Lambda.
    This function automates the 'Upload -> Trigger Alarm -> Auto Cleanup' cycle
    to verify that the end-to-end infrastructure is functioning correctly.
    """

    # 1. First Upload: Small baseline file (approx 18 bytes)
    s3.put_object(Bucket=BUCKET_NAME, Key="assignment1.txt", Body="Empty Assignment 1".encode('utf-8'))
    print("Step 1: Created assignment1.txt (18 bytes).")

    # Short sleep to ensure DynamoDB timestamps are distinct for plotting
    time.sleep(5)

    # 2. Second Upload: Larger file to push total size over the 20-byte threshold
    s3.put_object(Bucket=BUCKET_NAME, Key="assignment2.txt", Body="Empty Assignment 2222222222".encode('utf-8'))
    print("Step 2: Created assignment2.txt (28 bytes). Total size > 20-byte Alarm limit.")

    # 3. Wait for Infrastructure Reaction
    print("Waiting for Alarm to trigger and Cleaner to delete the FIRST file...")
    if wait_for_s3_object_to_disappear("assignment2.txt", timeout=120):
        print("First cleanup confirmed.")
    
    print("Waiting for Alarm to return to OK status before next step...")
    wait_for_alarm_status("OK", timeout=120)

    s3.put_object(Bucket=BUCKET_NAME, Key="assignment3.txt", Body="33".encode('utf-8'))
    print("Step 3: Created assignment3.txt. Total is now exactly 20. Waiting for SECOND alarm...")
    
    if wait_for_s3_object_to_disappear("assignment1.txt", timeout=120):
        print("Second cleanup confirmed (assignment1 deleted).")

    # 4. Final Verification: Invoke the Plotting API
    # This verifies that the API Gateway and Plotting Lambda can still generate
    # the chart after cleanup actions have occurred.
    try:
        print(f"Requesting visualization from: {PLOTTING_API_URL}")
        headers = {'Accept': 'image/png'}
        response = requests.get(PLOTTING_API_URL, headers=headers, timeout=45, stream=True)
        print(f"API Response Status Code: {response.status_code}")


        if response.status_code == 200:
            print(f"Success: Received image data. Content length: {len(response.content)} bytes")
        else:
            print(f"Warning: API returned status {response.status_code}.")
            print(f"Response Body: {response.text[:200]}")
    except requests.exceptions.RequestException as e:
        print(f"Network error calling Plot API: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Simulation sequence completed.",
            "status": "Check S3/DynamoDB for final cleanup state."
        })
    }