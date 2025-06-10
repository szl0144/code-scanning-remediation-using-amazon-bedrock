#!/bin/bash

# Code Scanning Remediation - Deployment Script
set -e

echo "🚀 Starting deployment of Code Scanning Remediation system..."

# Check if GitHub token is set
if [ -z "$GITHUB_TOKEN" ]; then
    echo "⚠️  Warning: GITHUB_TOKEN environment variable is not set."
    echo "   Please set it with: export GITHUB_TOKEN=your_github_token"
    echo "   You can still proceed, but the Lambda function won't be able to access GitHub repositories."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Navigate to CDK directory
echo "📁 Navigating to CDK directory..."
cd cdk-bedrock-agent

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing CDK dependencies..."
    npm install
fi

# Bootstrap CDK if needed (only runs if not already bootstrapped)
echo "🔧 Checking CDK bootstrap..."
cdk bootstrap

# Deploy the stack
echo "🚀 Deploying Bedrock Agent stack..."
cdk deploy --require-approval never

echo "✅ Deployment completed successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Note down the Agent ID and Agent Alias ID from the output"
echo "2. Use these values in the Streamlit UI"
echo "3. Make sure your GitHub token has proper permissions"
echo ""
echo "🌐 To start the Streamlit UI:"
echo "   cd ../streamlit-ui"
echo "   streamlit run app.py" 