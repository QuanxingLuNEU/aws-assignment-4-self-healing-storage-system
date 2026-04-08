import * as cdk from 'aws-cdk-lib'
import { Construct } from 'constructs'
import * as lambda from 'aws-cdk-lib/aws-lambda'
import * as sqs from 'aws-cdk-lib/aws-sqs'
import * as s3 from 'aws-cdk-lib/aws-s3'
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb'
import * as apigateway from 'aws-cdk-lib/aws-apigateway'
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources'
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';

/**
 * LambdaStack: Defines all compute resources, API Gateway, and IAM permissions.
 */
interface LambdaStackProps extends cdk.StackProps {
  bucket: s3.IBucket
  table: dynamodb.ITable
  sizeQueue: sqs.IQueue
  loggingQueue: sqs.IQueue
}

export class LambdaStack extends cdk.Stack {
  // Expose functions for MonitoringStack to create Alarms
  public readonly driverLambda: lambda.Function
  public readonly sizeLambda: lambda.Function;
  public readonly plotLambda: lambda.Function
  public readonly cleanerLambda: lambda.Function
  public readonly api: apigateway.RestApi

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props)

    const sizeLambdaName = 'Assignment4-SizeTrackingLambda';
    
    const sizeLogGroup = new logs.LogGroup(this, 'SizeTrackingLogGroup', {
      logGroupName: `/aws/lambda/${sizeLambdaName}`, 
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: cdk.RemovalPolicy.DESTROY, 
    });


    // 1. SIZE TRACKING LAMBDA: Triggered by SQS to update DynamoDB metrics.
    this.sizeLambda = new lambda.Function(this, 'SizeTrackingLambda', {
      functionName: sizeLambdaName,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'size-tracking_lambda.lambda_handler',
      code: lambda.Code.fromAsset('lambda'),
      environment: {
        TABLE_NAME: props.table.tableName,
        BUCKET_NAME: props.bucket.bucketName,
      },
      logGroup: sizeLogGroup,
      timeout: cdk.Duration.seconds(30)
    })

    this.sizeLambda.addEventSource(new lambdaEventSources.SqsEventSource(props.sizeQueue))
    props.table.grantReadWriteData(this.sizeLambda)
    props.bucket.grantRead(this.sizeLambda)

    // 2. CLEANER LAMBDA: Triggered by CloudWatch Alarms to delete the largest file.
    this.cleanerLambda = new lambda.Function(this, 'CleanerLambda', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'cleaner_lambda.lambda_handler',
      code: lambda.Code.fromAsset('lambda'),
      environment: {
        TABLE_NAME: props.table.tableName,
        BUCKET_NAME: props.bucket.bucketName,
      }
    })

    this.cleanerLambda.addPermission('AllowCloudWatchInvocation', {
      principal: new iam.ServicePrincipal('lambda.alarms.cloudwatch.amazonaws.com'),
      action: 'lambda:InvokeFunction',
    });

    props.table.grantReadWriteData(this.cleanerLambda);
    props.bucket.grantReadWrite(this.cleanerLambda);

    // 3. PLOTTING LAMBDA: Generates storage visualization using Matplotlib.
    this.plotLambda = new lambda.Function(this, 'PlotLambda', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'plotting_lambda.lambda_handler',
      code: lambda.Code.fromAsset('lambda'),
      architecture: lambda.Architecture.X86_64,
      environment: {
        BUCKET_NAME: props.bucket.bucketName,
        TABLE_NAME: props.table.tableName
      },
      memorySize: 1024, // Higher memory for image processing speed
      timeout: cdk.Duration.seconds(30)
    })

    // External Layer for Matplotlib dependencies (K-Layers)
    const matplotlibLayer = lambda.LayerVersion.fromLayerVersionArn(
      this,
      'MatplotlibLayer',
      'arn:aws:lambda:us-west-2:770693421928:layer:Klayers-p311-matplotlib:17'
    )

    this.plotLambda.addLayers(matplotlibLayer)
    props.table.grantReadData(this.plotLambda)
    props.bucket.grantWrite(this.plotLambda) // Permission to save plot.png
    
    // 4. API GATEWAY: Exposes the Plotting Lambda to the web.
    this.api = new apigateway.RestApi(this, 'PlotApi', {
      restApiName: 'PlotLambdaAPI',
      description: 'API to trigger plot Lambda',
      // Required to correctly serve PNG image data
      binaryMediaTypes: ['*/*']
    })

    const plotResource = this.api.root.addResource('plot')
    plotResource.addMethod('GET', new apigateway.LambdaIntegration(this.plotLambda))

    // 6. DRIVER LAMBDA: Orchestrates the end-to-end test simulation.
    const requestsLayer = lambda.LayerVersion.fromLayerVersionArn(
      this,
      'RequestsLayer',
      'arn:aws:lambda:us-west-2:336392948345:layer:AWSSDKPandas-Python311:12'
    );

    this.driverLambda = new lambda.Function(this, 'DriverLambda', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'driver_lambda.lambda_handler',
      code: lambda.Code.fromAsset('lambda'),
      architecture: lambda.Architecture.X86_64,
      layers: [requestsLayer],
      environment: {
        BUCKET_NAME: props.bucket.bucketName,
        TABLE_NAME: props.table.tableName,
        PLOTTING_API_URL: this.api.url + 'plot'
      },
      timeout: cdk.Duration.seconds(300) // Long timeout to wait for Alarms
    })

    props.bucket.grantReadWrite(this.driverLambda)
  }
}