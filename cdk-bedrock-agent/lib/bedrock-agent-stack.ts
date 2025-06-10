import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as path from 'path';
import { Construct } from 'constructs';

export class BedrockAgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);



    // Create IAM role for Lambda function
    const lambdaRole = new iam.Role(this, 'CodeScanningLambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Add Bedrock permissions to Lambda role
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream'
      ],
      resources: [
        `arn:aws:bedrock:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:foundation-model/us.anthropic.claude-sonnet-4-20250514-v1:0`,
        `arn:aws:bedrock:${cdk.Aws.REGION}:063953632432:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0`
      ]
    }));

    // Create Lambda function
    const codeScanningLambda = new lambda.Function(this, 'CodeScanningFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'lambda_function.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda')),
      role: lambdaRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 4096,
      environment: {
        GITHUB_TOKEN: process.env.GITHUB_TOKEN || 'REPLACE_WITH_YOUR_GITHUB_TOKEN',
        MODEL_ID: 'us.anthropic.claude-sonnet-4-20250514-v1:0',
        USE_CONVERSE_API: 'true'
      },
    });

    // Create IAM role for Bedrock Agent with maximum permissions
    const agentRole = new iam.Role(this, 'BedrockAgentExecutionRole', {
      roleName: 'BedrockAgentExecutionRole-' + cdk.Aws.STACK_NAME,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      managedPolicies: [
        // Add AWS managed policies
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonBedrockFullAccess'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AWSLambdaExecute'),
      ],
      inlinePolicies: {
        BedrockAgentMaxPermissionsPolicy: new iam.PolicyDocument({
          statements: [
            // All Bedrock permissions
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock:*',
                'bedrock-agent:*',
                'bedrock-runtime:*'
              ],
              resources: ['*']
            }),
            // All Lambda permissions
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'lambda:*'
              ],
              resources: ['*']
            }),
            // S3 permissions (if storage is needed)
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                's3:GetObject',
                's3:PutObject',
                's3:DeleteObject',
                's3:ListBucket'
              ],
              resources: ['*']
            }),
            // CloudWatch logs permissions
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
                'logs:DescribeLogGroups',
                'logs:DescribeLogStreams'
              ],
              resources: ['*']
            }),
            // IAM permissions (for service interactions)
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'iam:PassRole',
                'iam:GetRole',
                'iam:ListRoles'
              ],
              resources: ['*']
            }),
            // KMS permissions (for encryption)
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'kms:Decrypt',
                'kms:Encrypt',
                'kms:GenerateDataKey',
                'kms:DescribeKey'
              ],
              resources: ['*']
            })
          ]
        })
      }
    });

    // Grant Lambda invoke permissions to Bedrock
    codeScanningLambda.addPermission('AllowBedrockInvoke', {
      principal: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      action: 'lambda:InvokeFunction',
      sourceArn: `arn:aws:bedrock:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:agent/*`
    });

    // Create the Bedrock Agent with Action Groups
    const agent = new bedrock.CfnAgent(this, 'CodeScanningAgent', {
      agentName: 'code-scanning-remediation-agent',
      agentResourceRoleArn: agentRole.roleArn,
      foundationModel: 'us.anthropic.claude-sonnet-4-20250514-v1:0',
      instruction: 'You are a code scanning and remediating AI assistant. Greet the user and ask user for repository_url and branch_name that needs to be scanned. Ask user for list of folders that needs to be excluded from scanning and also ask user for list of specific file extensions that needs to be excluded from scanning. Ask user new branch name to push the remediated code. Call scanAndRemediate function with these parameters. IMPORTANT: Wait for the function to complete execution and return the final results before responding to user. Use only the actual function output in your response.',
      description: 'AI assistant for scanning and remediating code repositories',
      idleSessionTtlInSeconds: 3600,
      customerEncryptionKeyArn: undefined,
      
      // Action Groups as part of the Agent
      actionGroups: [{
        actionGroupName: 'code-scan-remediation',
        description: 'Action group for code scanning and remediation',
        actionGroupExecutor: {
          lambda: codeScanningLambda.functionArn
        },
        apiSchema: {
          payload: JSON.stringify({
            openapi: '3.0.0',
            info: {
              title: 'Code Scanning and Remediation API',
              version: '1.0.0',
              description: 'API for scanning and remediating code repositories'
            },
            paths: {
              '/scanAndRemediate': {
                post: {
                  summary: 'Scan and remediate code repository',
                  description: 'Analyzes code repository for issues and creates a new branch with fixes',
                  operationId: 'scanAndRemediate',
                  parameters: [
                    {
                      name: 'repository_url',
                      in: 'query',
                      required: true,
                      schema: {
                        type: 'string'
                      },
                      description: 'Code repository URL'
                    },
                    {
                      name: 'branch_name', 
                      in: 'query',
                      required: true,
                      schema: {
                        type: 'string'
                      },
                      description: 'Branch name of code repository that needs to be scanned'
                    },
                    {
                      name: 'file_extensions_to_exclude',
                      in: 'query',
                      required: false,
                      schema: {
                        type: 'string'
                      },
                      description: 'Comma-separated file extensions to exclude from scanning (e.g., .md,.txt)'
                    },
                    {
                      name: 'folders_to_exclude',
                      in: 'query', 
                      required: false,
                      schema: {
                        type: 'string'
                      },
                      description: 'Comma-separated folder names to exclude from scanning (e.g., node_modules,dist)'
                    },
                    {
                      name: 'new_remediated_branch_name',
                      in: 'query',
                      required: true,
                      schema: {
                        type: 'string'
                      },
                      description: 'New branch name to push remediated code'
                    }
                  ],
                  responses: {
                    '200': {
                      description: 'Successful response',
                      content: {
                        'application/json': {
                          schema: {
                            type: 'object',
                            properties: {
                              result: {
                                type: 'string',
                                description: 'Result message'
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          })
        }
      }],
      
      promptOverrideConfiguration: {
        promptConfigurations: [
          {
            promptType: 'ORCHESTRATION',
            promptCreationMode: 'DEFAULT'
          }
        ]
      }
    });

    // Create Agent Alias
    const agentAlias = new bedrock.CfnAgentAlias(this, 'CodeScanningAgentAlias', {
      agentAliasName: 'production',
      agentId: agent.ref,
      description: 'Production alias for code scanning agent'
    });

    // Output values
    new cdk.CfnOutput(this, 'AgentId', {
      value: agent.ref,
      description: 'The ID of the Bedrock Agent'
    });

    new cdk.CfnOutput(this, 'AgentAliasId', {
      value: agentAlias.ref,
      description: 'The ID of the Bedrock Agent Alias'
    });

    new cdk.CfnOutput(this, 'LambdaFunctionArn', {
      value: codeScanningLambda.functionArn,
      description: 'The ARN of the Lambda function'
    });

    new cdk.CfnOutput(this, 'AgentRoleArn', {
      value: agentRole.roleArn,
      description: 'The ARN of the Agent IAM role'
    });
  }
} 