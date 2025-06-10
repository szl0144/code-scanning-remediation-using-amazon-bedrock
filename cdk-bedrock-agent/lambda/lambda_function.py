import json
import logging
import base64
import os
import boto3
import re
import requests
from urllib.parse import urlparse
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize a Boto3 client for Bedrock with extended timeout configuration
bedrock_config = Config(
    read_timeout=900,  # 15 minutes read timeout
    connect_timeout=600,  # 1 minute connection timeout
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'
    }
)

bedrock = boto3.client(
    service_name='bedrock-runtime',
    config=bedrock_config
)

# Fetch configuration from environment variables
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
MODEL_ID = os.getenv('MODEL_ID', 'us.anthropic.claude-sonnet-4-20250514-v1:0')
USE_CONVERSE_API = os.getenv('USE_CONVERSE_API', 'true').lower() == 'true'

if not GITHUB_TOKEN:
    raise ValueError("GitHub token is not set in the environment variables")

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Content-Type": "application/json"
}

def invoke_model_with_converse(prompt, max_tokens=10000, temperature=0.7):
    """
    Invoke Bedrock model using the Converse API
    """
    try:
        response = bedrock.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
                "topP": 0.95,
            }
        )
        
        # Extract the response content
        output_message = response['output']['message']
        text_content = output_message['content'][0]['text']
        return text_content
        
    except ClientError as e:
        logger.error(f"Error invoking model with Converse API: {e}")
        raise

def invoke_model_legacy(prompt, max_tokens=10000, temperature=0.7):
    """
    Legacy method to invoke Bedrock model
    """
    response = bedrock.invoke_model(
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
            "top_k": 250
        }),
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json"
    )
    
    response_body = json.loads(response['body'].read())
    return response_body['content'][0]['text']

def invoke_model(prompt, max_tokens=10000, temperature=0.7):
    """
    Wrapper function to invoke model using either Converse API or legacy method
    """
    if USE_CONVERSE_API:
        return invoke_model_with_converse(prompt, max_tokens, temperature)
    else:
        return invoke_model_legacy(prompt, max_tokens, temperature)

# Modified function to exclude specified folders
def fetch_repository_contents(repo_link, branch, path="", exclude_folders=None):
    repo_path = urlparse(repo_link).path.strip('/')
    api_endpoint = f"https://api.github.com/repos/{repo_path}/contents/{path}?ref={branch}"
    response = requests.get(api_endpoint, headers=headers)
    response.raise_for_status()
    
    files = {}
    for item in response.json():
        # Skip folders if they are in the exclude_folders list
        if item["type"] == "dir":
            folder_name = item["path"].split("/")[-1]
            if exclude_folders and folder_name in exclude_folders:
                logger.info(f"Skipping excluded folder: {folder_name}")
                continue
            # Recursively fetch contents from the subdirectory
            files.update(fetch_repository_contents(repo_link, branch, item["path"], exclude_folders))
        elif item["type"] == "file":
            file_content = requests.get(item["download_url"], headers=headers).text
            files[item["path"]] = file_content
    
    return files

def analyze_and_remediate_code(code_repo, non_code_exts):
    def analyze_code(code):
        prompt = f"""Please analyze the following code for potential issues:

Code:
{code}

Identify any:
- Security vulnerabilities
- Performance issues
- Code style problems
- Potential bugs
- Code complexity issues

Provide a detailed analysis of the issues found."""
        
        analysis = invoke_model(prompt, max_tokens=10000, temperature=0.5)
        
        # Extract issue types from the analysis
        issues = []
        issue_patterns = [
            "security vulnerability",
            "code style issue",
            "performance issue",
            "code complexity issue",
            "potential bug"
        ]
        
        for pattern in issue_patterns:
            if pattern.lower() in analysis.lower():
                issues.append(pattern)
        
        return issues if issues else ["general code improvement needed"]

    def remediate_code(code, issues):
        prompt = f"""Fix the following issues in the code and return ONLY the corrected code without any explanations, comments, or code block delimiters.

Code:
{code}

Issues to fix:
{', '.join(issues)}

Important: Return only the fixed code, nothing else."""
        
        remediation = invoke_model(prompt, max_tokens=10000, temperature=0.7)
        
        # Clean up the response
        remediation = remediation.strip()
        # Remove any code block markers if present
        remediation = re.sub(r"```[a-zA-Z]*\n?", "", remediation)
        remediation = remediation.replace("```", "")
        
        # Remove common explanation prefixes
        prefixes_to_remove = [
            "Here is the fixed code:",
            "Here's the corrected code:",
            "Fixed code:",
            "Corrected code:",
        ]
        
        for prefix in prefixes_to_remove:
            if remediation.lower().startswith(prefix.lower()):
                remediation = remediation[len(prefix):].strip()
        
        return remediation

    remediations = {}
    for file_path, file_content in code_repo.items():
        if any(file_path.endswith(ext) for ext in non_code_exts):
            logger.info(f"Skipping non-code file: {file_path}")
            continue
        
        logger.info(f"Analyzing file: {file_path}")
        issues = analyze_code(file_content)
        
        if issues:
            logger.info(f"Found issues in {file_path}: {issues}")
            remediated_code = remediate_code(file_content, issues)
            remediations[file_path] = remediated_code
        else:
            logger.info(f"No issues found in {file_path}")
            remediations[file_path] = file_content
    
    return remediations

def create_new_branch(event):
    repo_link = event['repository_link']
    remediations = event['remediations']
    base_branch = event['base_branch']
    new_branch_name = event['new_branch_name']

    repo_path = urlparse(repo_link).path.strip('/')
    
    # Get base commit
    base_commit_response = requests.get(
        f"https://api.github.com/repos/{repo_path}/git/refs/heads/{base_branch}", 
        headers=headers
    )
    base_commit_response.raise_for_status()
    base_commit = base_commit_response.json()["object"]["sha"]
    
    # Check if branch already exists
    check_branch = requests.get(
        f"https://api.github.com/repos/{repo_path}/git/refs/heads/{new_branch_name}", 
        headers=headers
    )
    if check_branch.status_code == 200:
        raise ValueError(f"Branch {new_branch_name} already exists.")
    
    # Create new branch
    create_branch_response = requests.post(
        f"https://api.github.com/repos/{repo_path}/git/refs", 
        json={"ref": f"refs/heads/{new_branch_name}", "sha": base_commit}, 
        headers=headers
    )
    create_branch_response.raise_for_status()
    
    # Create blobs for changed files
    blobs = []
    for file_path, remediated_code in remediations.items():
        blob_payload = {
            "content": base64.b64encode(remediated_code.encode()).decode(),
            "encoding": "base64"
        }
        blob_response = requests.post(
            f"https://api.github.com/repos/{repo_path}/git/blobs", 
            json=blob_payload, 
            headers=headers
        )
        blob_response.raise_for_status()
        blob_sha = blob_response.json()["sha"]
        blobs.append({"path": file_path, "mode": "100644", "type": "blob", "sha": blob_sha})

    # Get base tree
    base_tree_response = requests.get(
        f"https://api.github.com/repos/{repo_path}/git/trees/{base_commit}", 
        headers=headers
    )
    base_tree_response.raise_for_status()
    base_tree_sha = base_tree_response.json()["sha"]
    
    # Create new tree
    new_tree_response = requests.post(
        f"https://api.github.com/repos/{repo_path}/git/trees", 
        json={"base_tree": base_tree_sha, "tree": blobs}, 
        headers=headers
    )
    new_tree_response.raise_for_status()
    new_tree_sha = new_tree_response.json()["sha"]
    
    # Create commit
    commit_message = f"Automated code remediation - Fixed {len(remediations)} files"
    new_commit_response = requests.post(
        f"https://api.github.com/repos/{repo_path}/git/commits", 
        json={
            "message": commit_message, 
            "tree": new_tree_sha, 
            "parents": [base_commit]
        }, 
        headers=headers
    )
    new_commit_response.raise_for_status()
    new_commit_sha = new_commit_response.json()["sha"]
    
    # Update branch reference
    update_ref_response = requests.patch(
        f"https://api.github.com/repos/{repo_path}/git/refs/heads/{new_branch_name}", 
        json={"sha": new_commit_sha}, 
        headers=headers
    )
    update_ref_response.raise_for_status()
    
    return new_branch_name

def lambda_handler(event, context):
    # Initialize variables that will be used in error handling
    # Log the entire event to debug API path issues
    logger.info(f"Full event structure: {json.dumps(event, indent=2)}")
    
    # Extract apiPath - it might be in different locations
    apiPath = event.get('apiPath', None)
    if not apiPath and 'inputText' in event:
        # Sometimes it's in a nested structure
        apiPath = event.get('inputText', {}).get('apiPath', None)
    if not apiPath:
        # Default fallback
        apiPath = '/scanAndRemediate'
    
    logger.info(f"Extracted apiPath: {apiPath}")
    
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extract parameters based on Bedrock Agent format
        agent = event.get('agent', '')
        actionGroup = event.get('actionGroup', '')
        function = event.get('function', '')
        
        # Try to extract parameters from multiple possible locations
        parameters = []
        
        # First try: requestBody format (from Bedrock Agent)
        request_body = event.get('requestBody', {})
        if request_body:
            content = request_body.get('content', {})
            app_json = content.get('application/json', {})
            properties_list = app_json.get('properties', [])
            if properties_list:
                parameters = properties_list
        
        # Second try: direct parameters
        if not parameters:
            parameters = event.get('parameters', [])
        
        # Convert parameters list to dictionary
        properties = {}
        for param in parameters:
            if isinstance(param, dict) and 'name' in param and 'value' in param:
                properties[param["name"]] = param["value"]
        
        # Extract individual parameters
        repo_link = properties.get('repository_url')
        branch = properties.get('branch_name')
        non_code_exts = properties.get('file_extensions_to_exclude', [])
        exclude_folders = properties.get('folders_to_exclude', [])
        new_branch_name = properties.get('new_remediated_branch_name')
        
        # Convert string inputs to lists if necessary
        if isinstance(non_code_exts, str):
            # First remove leading/trailing brackets from the entire string
            non_code_exts = non_code_exts.strip().strip('[]')
            # Then split by comma and strip each element
            non_code_exts = [ext.strip() for ext in non_code_exts.split(',') if ext.strip()]
        if isinstance(exclude_folders, str):
            # First remove leading/trailing brackets from the entire string
            exclude_folders = exclude_folders.strip().strip('[]')
            # Then split by comma and strip each element
            exclude_folders = [folder.strip() for folder in exclude_folders.split(',') if folder.strip()]
        
        logger.info(f"Processing repository: {repo_link}, branch: {branch}")
        logger.info(f"Excluding folders: {exclude_folders}, extensions: {non_code_exts}")

        # Fetch repository contents
        code_repo = fetch_repository_contents(repo_link, branch, exclude_folders=exclude_folders)
        logger.info(f"Fetched {len(code_repo)} files from repository")
        
        # Analyze and remediate code
        remediations = analyze_and_remediate_code(code_repo, non_code_exts)
        logger.info(f"Generated remediations for {len(remediations)} files")

        # Create new branch with remediated code
        create_branch_event = {
            'repository_link': repo_link,
            'remediations': remediations,
            'base_branch': branch,
            'new_branch_name': new_branch_name
        }
        
        created_branch = create_new_branch(create_branch_event)
        logger.info(f"Successfully created new branch: {created_branch}")
        
        # Prepare response for Bedrock Agent (OpenAPI schema format)
        response_body = {
            'application/json': {
                'body': json.dumps({
                    "result": f"Successfully scanned and remediated code. New branch '{created_branch}' has been created with {len(remediations)} fixed files."
                })
            }
        }

        action_response = {
            'actionGroup': actionGroup,
            'apiPath': apiPath,
            'httpMethod': 'POST',
            'httpStatusCode': 200,
            'responseBody': response_body
        }

        final_response = {
            'messageVersion': event.get('messageVersion', '1.0'),
            'response': action_response
        }
        
        logger.info(f"Returning response: {json.dumps(final_response)}")
        return final_response

    except KeyError as ke:
        logger.error(f"Key error: {str(ke)}")
        error_message = f"Missing required parameter: {str(ke)}"
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        error_message = f"Error: {str(e)}"
    
    # Error response (OpenAPI schema format)
    response_body = {
        'application/json': {
            'body': json.dumps({
                "result": error_message
            })
        }
    }
    
    action_response = {
        'actionGroup': event.get('actionGroup', ''),
        'apiPath': apiPath,
        'httpMethod': 'POST',
        'httpStatusCode': 500,
        'responseBody': response_body
    }
    
    final_response = {
        'messageVersion': event.get('messageVersion', '1.0'),
        'response': action_response
    }
    
    return final_response 