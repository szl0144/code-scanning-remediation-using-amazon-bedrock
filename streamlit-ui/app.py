import streamlit as st
import boto3
import json
import uuid
from datetime import datetime
import logging
from botocore.config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="GitHub Code Remediation",
    page_icon="🔍",
    layout="wide",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)

# Default configuration
DEFAULT_REGION = "us-east-1"
DEFAULT_AGENT_ID = "UVJJPAARV4"  # Needs user input
DEFAULT_AGENT_ALIAS_ID = "1TCIQSTCHU"  # Needs user input

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'agent_client' not in st.session_state:
    st.session_state.agent_client = None
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

class BedrockAgentClient:
    """Simple Bedrock Agent client"""
    
    def __init__(self, agent_id: str, agent_alias_id: str, region: str):
        self.agent_id = agent_id
        self.agent_alias_id = agent_alias_id
        self.region = region
        
        # Configure maximum timeout
        config = Config(
            read_timeout=1500,  # 15 minutes read timeout
            connect_timeout=60,  # 1 minute connection timeout
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            }  # No retries
        )
        
        # Initialize client with local AWS configuration
        self.client = boto3.client(
            service_name='bedrock-agent-runtime',
            region_name=region,
            config=config
        )
    
    def invoke_agent(self, session_id: str, prompt: str) -> str:
        """Invoke Bedrock Agent"""
        try:
            response = self.client.invoke_agent(
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=session_id,
                inputText=prompt,
                enableTrace=False
            )
            
            # Handle streaming response
            completion = ""
            
            # Bedrock Agent returns an event stream
            event_stream = response.get('completion', {})
            
            # Iterate through event stream
            for event in event_stream:
                if 'chunk' in event:
                    chunk = event['chunk']
                    if 'bytes' in chunk:
                        completion += chunk['bytes'].decode('utf-8')
                elif 'trace' in event:
                    # Optional: handle trace information
                    logger.debug(f"Trace: {event['trace']}")
            
            return completion if completion else "No response received from agent."
            
        except Exception as e:
            logger.error(f"Error invoking agent: {str(e)}")
            logger.error(f"Full error details: {type(e).__name__}: {str(e)}")
            return f"Error: {str(e)}"

# Hide menu and optimize layout
st.markdown("""
<style>
    /* Hide entire header row including deploy button */
    header[data-testid="stHeader"] {
        display: none !important;
        height: 0 !important;
    }
    
    /* Adjust top spacing of main container */
    .stApp > div:first-child {
        padding-top: 0rem !important;
    }
    
    div[data-testid="stAppViewContainer"] > div:first-child {
        padding-top: 1rem !important;
    }
    
    /* Ensure title is tight to top */
    .stMainBlockContainer {
        padding-top: 0rem !important;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.title("🔍 Github Code Remediation Agent")

# Add spacing between title and chat box (can be deleted as it's set to 0)
# st.markdown("<div style='margin-bottom: 0rem;'></div>", unsafe_allow_html=True)

# Sidebar configuration
with st.sidebar:
    st.header("Configuration")
    
    # Project selection
    project = st.selectbox(
        "Select Project",
        options=["sample"],
        help="Choose a project configuration"
    )
    
    # Agent configuration
    st.subheader("Agent Settings")
    agent_id = st.text_input(
        "Agent ID", 
        value=st.session_state.get('agent_id', DEFAULT_AGENT_ID),
        help="Your Bedrock Agent ID"
    )
    
    agent_alias_id = st.text_input(
        "Agent Alias ID", 
        value=st.session_state.get('agent_alias_id', DEFAULT_AGENT_ALIAS_ID),
        help="Your Bedrock Agent Alias ID"
    )
    
    # AWS Region
    aws_region = st.selectbox(
        "AWS Region",
        options=["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"],
        index=0,
        help="AWS region where your agent is deployed"
    )
    
    # Save configuration to session state
    if agent_id:
        st.session_state.agent_id = agent_id
    if agent_alias_id:
        st.session_state.agent_alias_id = agent_alias_id
    
    # Initialize button
    if st.button("Initialize Agent", type="primary"):
        if not agent_id or not agent_alias_id:
            st.error("Please provide both Agent ID and Agent Alias ID")
        else:
            try:
                st.session_state.agent_client = BedrockAgentClient(
                    agent_id=agent_id,
                    agent_alias_id=agent_alias_id,
                    region=aws_region
                )
                st.success("✅ Agent initialized successfully!")
                
            except Exception as e:
                st.error(f"Failed to initialize agent: {str(e)}")
    
    # Clear conversation button
    if st.button("Clear Conversation"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()
    
    # Display session information
    st.divider()
    st.caption(f"Session ID: {st.session_state.session_id[:8]}...")


# Add small spacing
st.markdown("<div style='margin-top: 0rem; margin-bottom: 0rem;'></div>", unsafe_allow_html=True)

# Display conversation history
message_container = st.container(height=700)
with message_container:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "timestamp" in message:
                st.caption(f"🕐 {message['timestamp']}")

# Chat input
user_input = st.chat_input("Type your message here...")

if user_input:
    if not st.session_state.agent_client:
        st.warning("⚠️ Please initialize the agent first using the sidebar configuration.")
    else:
        # Add user message
        user_msg = {
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        st.session_state.messages.append(user_msg)
        
        # Display user message
        with message_container:
            with st.chat_message("user"):
                st.markdown(user_input)
                st.caption(f"🕐 {user_msg['timestamp']}")
        
        # Get agent response
        with message_container:
            with st.chat_message("assistant"):
                # Detect if it's a remediation request
                is_remediation_request = (
                    "1." in user_input and "2." in user_input and 
                    ("github.com" in user_input.lower() or "gitlab.com" in user_input.lower()) and "3." in user_input)
                
                
                spinner_text = "🔧 Remediating..." if is_remediation_request else "🤔 Thinking..."
                
                with st.spinner(spinner_text):
                    try:
                        # Add debug information
                        logger.info(f"Invoking agent with session_id: {st.session_state.session_id}")
                        logger.info(f"Agent ID: {st.session_state.agent_client.agent_id}")
                        logger.info(f"Agent Alias ID: {st.session_state.agent_client.agent_alias_id}")
                        logger.info(f"User input: {user_input}")
                        
                        # Invoke Bedrock Agent
                        response = st.session_state.agent_client.invoke_agent(
                            session_id=st.session_state.session_id,
                            prompt=user_input
                        )
                        
                        # Add assistant response
                        assistant_msg = {
                            "role": "assistant",
                            "content": response,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        }
                        st.session_state.messages.append(assistant_msg)
                        
                        # Display response
                        st.markdown(response)
                        st.caption(f"🕐 {assistant_msg['timestamp']}")
                        
                    except Exception as e:
                        error_msg = f"Sorry, I encountered an error: {str(e)}"
                        st.error(error_msg)
                        
                        # Display detailed error information
                        with st.expander("Error Details"):
                            st.code(f"""
Error Type: {type(e).__name__}
Error Message: {str(e)}
Session ID: {st.session_state.session_id}
Agent ID: {st.session_state.agent_client.agent_id if st.session_state.agent_client else 'N/A'}
Agent Alias ID: {st.session_state.agent_client.agent_alias_id if st.session_state.agent_client else 'N/A'}
                            """)
                        
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": error_msg,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })
        
        st.rerun()

 