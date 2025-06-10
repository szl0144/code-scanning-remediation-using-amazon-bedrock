#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { BedrockAgentStack } from '../lib/bedrock-agent-stack';

const app = new cdk.App();

new BedrockAgentStack(app, 'bedrock-code-scanning-agent-stack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  description: 'AWS CDK Stack for Bedrock Agent with code scanning and remediation capabilities',
});

app.synth(); 