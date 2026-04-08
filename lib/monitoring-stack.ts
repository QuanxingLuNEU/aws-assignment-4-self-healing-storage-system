import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cw_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as iam from 'aws-cdk-lib/aws-iam';

/**
 * MonitoringStack: Implements the self-healing logic using CloudWatch.
 * It tracks storage metrics via log parsing and triggers the Cleaner Lambda 
 * when thresholds are breached.
 */
interface MonitoringStackProps extends cdk.StackProps {
  targetLambdaName: string;
  cleanerLambdaArn: string; 
}

export class MonitoringStack extends cdk.Stack {
  public readonly alarm: cloudwatch.Alarm;

  constructor(scope: Construct, id: string, props: MonitoringStackProps) {
    super(scope, id, props);

    // Custom metric constants used to bridge Logs and Alarms
    const metricNamespace = 'Assignment4App';
    const metricName = 'TotalObjectSize';

    // 1. IMPORT RESOURCES:
    // We use Names and ARNs to reference resources from LambdaStack.
    // This technique breaks the circular dependency between Lambda and Monitoring.
    const loggingLambda = lambda.Function.fromFunctionName(this, 'ImportedLogLambda', props.targetLambdaName);
    
    // The Log Group name for any Lambda follows a standard AWS pattern
    const loggingLogGroup = logs.LogGroup.fromLogGroupName(
      this, 
      'ImportedLogGroup', 
      `/aws/lambda/${props.targetLambdaName}`
    );
    const cleanerLambda = lambda.Function.fromFunctionArn(this, 'ImportedCleanerLambda', props.cleanerLambdaArn);

    /**
     * 2. METRIC FILTER:
     * This filter scans the JSON logs produced by size-tracking lambda.
     * It extracts the 'total_size' value and transforms it into a CloudWatch Metric.
     */
    new logs.MetricFilter(this, 'SizeMetricFilter', {
      logGroup: loggingLogGroup,
      metricNamespace: metricNamespace,
      metricName: metricName,
      filterPattern: logs.FilterPattern.exists('$.total_size'),
      metricValue: '$.total_size', 
    });

    /**
     * 3. STORAGE ALARM:
     * Monitors the 'Sum' of size_delta over a 1-minute period.
     * If the total exceeds 20 bytes (simulated threshold), the Alarm fires.
     */
    this.alarm = new cloudwatch.Alarm(this, 'TotalSizeAlarm', {
      metric: new cloudwatch.Metric({
        namespace: metricNamespace,
        metricName: metricName,
        statistic: 'Maximum', 
        period: cdk.Duration.minutes(1),
      }),
      threshold: 20,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    cleanerLambda.addPermission('AllowCloudWatchAlarm', {
      action: 'lambda:InvokeFunction',
      principal: new iam.ServicePrincipal('lambda.alarms.cloudwatch.amazonaws.com'),
      sourceArn: this.alarm.alarmArn,
    });

    /**
     * 4. ALARM ACTION:
     * Connects the Alarm to the Cleaner Lambda.
     * When the state becomes 'ALARM', CloudWatch invokes the Cleaner automatically.
     */
    this.alarm.addAlarmAction(new cw_actions.LambdaAction(cleanerLambda));

    // 5. SECONDARY ALARM: Monitors the health of the Logging Lambda itself
    new cloudwatch.Alarm(this, 'LoggingLambdaErrorAlarm', {
      metric: loggingLambda.metricErrors(),
      threshold: 1,
      evaluationPeriods: 1,
    });
  }
}