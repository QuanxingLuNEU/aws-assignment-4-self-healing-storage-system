import * as cdk from 'aws-cdk-lib'
import { Construct } from 'constructs'
import * as s3 from 'aws-cdk-lib/aws-s3'
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb'
import * as sqs from 'aws-cdk-lib/aws-sqs'
import * as iam from 'aws-cdk-lib/aws-iam';

/**
 * StorageStack: Defines the persistent data layer of the application.
 * Contains S3 for file storage, DynamoDB for metadata, and SQS for decoupled messaging.
 */
export class StorageStack extends cdk.Stack {

  // Expose resources as public properties to allow cross-stack referencing in main.ts  
  public readonly bucket: s3.Bucket
  public readonly table: dynamodb.Table
  public readonly loggingQueue: sqs.Queue
  public readonly sizeQueue: sqs.Queue

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props)

    // 1. S3 Bucket: Stores user-uploaded files and generated plots.
    this.bucket = new s3.Bucket(this, 'TestBucket', {
      // Automatically clean up files when the stack is deleted (Experimental/Lab use)
      autoDeleteObjects: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    })

    // 2. DynamoDB Table: Tracks historical storage metrics.
    this.table = new dynamodb.Table(this, 'SizeHistoryTable', {
      // Partition Key: The name of the bucket (allows multi-bucket support if needed)
      partitionKey: { name: 'bucket_name', type: dynamodb.AttributeType.STRING },
      // Sort Key: Unix timestamp to track changes over time
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    })

    /**
     * Global Secondary Index (GSI): Enables efficient querying across the entire table.
     * We use a static partition key 'gsi_pk' (set to "all") and sort by 'size'.
     * This allows the Cleaner Lambda to find the largest file with a single O(1) query.
     */
    this.table.addGlobalSecondaryIndex({
      indexName: 'size-index',
      partitionKey: { name: 'gsi_pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'total_size', type: dynamodb.AttributeType.NUMBER }
    })

    /**
     * SQS Queues: Act as buffers for the SNS fan-out pattern.
     * visibilityTimeout is set to 180s to account for Lambda retry attempts 
     * and potential processing delays.
     */
    this.sizeQueue = new sqs.Queue(this, 'SizeTrackingQueue', {
      queueName: 'size-tracking-queue',
      visibilityTimeout: cdk.Duration.seconds(180),
    })

    this.loggingQueue = new sqs.Queue(this, 'LoggingQueue', {
      queueName: 'logging-queue',
      visibilityTimeout: cdk.Duration.seconds(180),
    })

    const queues = [this.sizeQueue, this.loggingQueue];

    queues.forEach((queue) => {
      queue.addToResourcePolicy(new iam.PolicyStatement({
        sid: 'AllowSNSPublish',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('sns.amazonaws.com')],
        actions: ['sqs:SendMessage'],
        resources: [queue.queueArn],
        conditions: {
          ArnLike: {
            'aws:SourceArn': `arn:aws:sns:${this.region}:${this.account}:*`,
          },
        },
      }));
    })
    
  }
}