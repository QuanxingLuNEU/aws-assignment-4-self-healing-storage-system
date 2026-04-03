#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { StorageStack } from '../lib/storage-stack';
import { MessagingStack } from '../lib/messaging-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { MonitoringStack } from '../lib/monitoring-stack';

/**
 * Main Entry Point: Orchestrates the deployment of four independent stacks.
 * * DESIGN PATTERN: Loose Coupling via String Injection.
 * To avoid circular dependencies (DependencyCycle), we pass resource identifiers 
 * (Names/ARNs) between stacks instead of passing the actual CDK resource objects 
 * where necessary.
 */
const app = new cdk.App();

// Common environment configuration
const env = { 
  account: process.env.CDK_DEFAULT_ACCOUNT, 
  region: 'us-west-2' 
};

// 1. STORAGE STACK: The foundation (S3, DynamoDB, SQS).
// This stack is the primary producer of resource identifiers.
const storage = new StorageStack(app, 'StorageStack', { env });

// 2. MESSAGING STACK: The event bus (SNS & S3 Notifications).
// We pass identifiers (strings) to decouple it from StorageStack's lifecycle.
const messaging = new MessagingStack(app, 'MessagingStack', {
  env,
  bucketName: storage.bucket.bucketName,
  sizeQueueArn: storage.sizeQueue.queueArn,
  loggingQueueArn: storage.loggingQueue.queueArn,
});

// 3. LAMBDA STACK: The compute layer (Business Logic & API Gateway).
// Uses direct object references for standard one-way dependency flow.
const lambdas = new LambdaStack(app, 'LambdaStack', {
  env,
  bucket: storage.bucket,
  table: storage.table,
  sizeQueue: storage.sizeQueue,
  loggingQueue: storage.loggingQueue,
});

// 4. MONITORING STACK: The self-healing layer (Alarms & Metric Filters).
// We pass function names and ARNs to break potential back-references to LambdaStack.
new MonitoringStack(app, 'MonitoringStack', {
  env,
  loggingLambdaName: lambdas.loggingLambda.functionName,
  // Note: Cleaner requires the ARN for the Alarm Action to work correctly
  cleanerLambdaArn: lambdas.cleanerLambda.functionArn,
});

// Finalize the synthesis into CloudFormation templates
app.synth();