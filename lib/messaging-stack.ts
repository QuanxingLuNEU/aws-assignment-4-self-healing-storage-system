import * as cdk from 'aws-cdk-lib'
import { Construct } from 'constructs'
import * as sns from 'aws-cdk-lib/aws-sns'
import * as subs from 'aws-cdk-lib/aws-sns-subscriptions'
import * as s3 from 'aws-cdk-lib/aws-s3'
import * as s3n from 'aws-cdk-lib/aws-s3-notifications'
import * as sqs from 'aws-cdk-lib/aws-sqs'

/**
 * MessagingStackProps: Uses strings (Names/ARNs) instead of actual objects
 * to prevent circular dependencies between StorageStack and MessagingStack.
 */
interface MessagingStackProps extends cdk.StackProps {
  bucketName: string;
  sizeQueueArn: string;
  loggingQueueArn: string;
}

export class MessagingStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MessagingStackProps) {
    super(scope, id, props);

    /**
     * RESOURCE IMPORT:
     * Instead of passing the actual Bucket/Queue objects, we "import" them 
     * using static identifiers. This decouples the lifecycle of these stacks.
     */
    const bucket = s3.Bucket.fromBucketName(this, 'ImportedBucket', props.bucketName);
    const sizeQueue = sqs.Queue.fromQueueArn(this, 'ImportedSizeQueue', props.sizeQueueArn);
    const logQueue = sqs.Queue.fromQueueArn(this, 'ImportedLogQueue', props.loggingQueueArn);

    /**
     * FAN-OUT PATTERN:
     * One S3 event is published to one SNS Topic, which then broadcasts 
     * the message to multiple SQS queues (Size Tracking and Logging).
     */
    const topic = new sns.Topic(this, 'S3EventTopic', {
      displayName: 'S3 Event Fan-out Topic'
    });

    // Subscribe both SQS queues to the SNS Topic
    topic.addSubscription(new subs.SqsSubscription(sizeQueue));
    topic.addSubscription(new subs.SqsSubscription(logQueue));

    /**
     * S3 EVENT NOTIFICATIONS:
     * Configure the bucket to send alerts to the SNS topic.
     * We monitor both CREATED and REMOVED events to keep metrics accurate.
     */
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED, 
      new s3n.SnsDestination(topic)
    );

    // Crucial for the Logging Lambda to calculate negative deltas
    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED, 
      new s3n.SnsDestination(topic)
    );
  }
}