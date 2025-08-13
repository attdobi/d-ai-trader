import os
import json
import base64
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import openai
from sqlalchemy import text

# Load environment variables (prefer .env over existing shell vars to avoid stale keys)
load_dotenv(override=True)

# Database connection
DATABASE_URI = 'postgresql://adobi@localhost/adobi'
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

# SQLAlchemy Base
Base = declarative_base()

# Define context storage model
class AgentContext(Base):
    __tablename__ = 'agent_contexts'
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    content = Column(Text, nullable=False)

# Define summaries model
class Summary(Base):
    __tablename__ = 'summaries'
    id = Column(Integer, primary_key=True)
    agent = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    run_id = Column(String, nullable=False)
    data = Column(Text, nullable=False)

# Create tables if not exist
Base.metadata.create_all(engine)

# OpenAI configuration
api_key = os.getenv("OPENAI_API_KEY")

# Schwab API configuration
SCHWAB_CLIENT_ID = os.getenv("SCHWAB_CLIENT_ID")
SCHWAB_CLIENT_SECRET = os.getenv("SCHWAB_CLIENT_SECRET")
SCHWAB_REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://localhost:8443/callback")
SCHWAB_ACCOUNT_HASH = os.getenv("SCHWAB_ACCOUNT_HASH")

# Trading configuration
TRADING_MODE = os.getenv("TRADING_MODE", "simulation")  # simulation or live
MAX_POSITION_VALUE = float(os.getenv("MAX_POSITION_VALUE", "1000"))
MAX_TOTAL_INVESTMENT = float(os.getenv("MAX_TOTAL_INVESTMENT", "10000"))
MIN_CASH_BUFFER = float(os.getenv("MIN_CASH_BUFFER", "500"))
DEBUG_TRADING = os.getenv("DEBUG_TRADING", "true").lower() == "true"

# Optional: print masked key for debugging if requested
try:
    if os.getenv("PRINT_OPENAI_KEY"):
        # Mask first 6 and last 4 characters unless PRINT_OPENAI_KEY=full
        if api_key:
            if os.getenv("PRINT_OPENAI_KEY").lower() == "full":
                masked = api_key
            else:
                masked = f"{api_key[:6]}...{api_key[-4:]} (len={len(api_key)})"
        else:
            masked = None
        print(f"[config] OPENAI_API_KEY present={bool(api_key)} key={masked}")
except Exception:
    pass

if not api_key:
    raise EnvironmentError(
        "OPENAI_API_KEY is not set. Add it to your environment or a .env file in the project root."
    )
openai.api_key = api_key

# Define the global model to use
# Available models: gpt-4.1, gpt-4.1-mini, o3, o3-mini, gpt-5, gpt-5-mini
GPT_MODEL = "gpt-4.1"  # Default model

def set_gpt_model(model_name):
    """Update the global GPT model"""
    global GPT_MODEL
    valid_models = ["gpt-4.1", "gpt-4.1-mini", "o3", "o3-mini", "gpt-5", "gpt-5-mini"]
    if model_name in valid_models:
        GPT_MODEL = model_name
        print(f"Updated GPT model to: {GPT_MODEL}")
    else:
        print(f"Invalid model '{model_name}'. Valid models are: {valid_models}")
        print(f"Keeping current model: {GPT_MODEL}")

def get_gpt_model():
    """Get the current GPT model"""
    return GPT_MODEL

# Prompt version configuration
PROMPT_VERSION_MODE = "auto"  # Default to auto
FORCED_PROMPT_VERSION = None

def set_prompt_version_mode(mode, specific_version=None):
    """Set the prompt version mode
    
    Args:
        mode: "auto" to use latest prompts, "fixed" to use a specific version
        specific_version: The specific version to use when mode is "fixed" (e.g., "v4", "4", etc.)
    """
    global PROMPT_VERSION_MODE, FORCED_PROMPT_VERSION
    
    if mode == "auto":
        PROMPT_VERSION_MODE = "auto"
        FORCED_PROMPT_VERSION = None
        print("🔄 Prompt version mode set to AUTO - will use latest prompt versions")
    elif mode == "fixed" and specific_version:
        PROMPT_VERSION_MODE = "fixed"
        # Normalize version format (remove 'v' prefix if present, then add it back)
        normalized_version = specific_version.lower().replace('v', '')
        try:
            version_num = int(normalized_version)
            FORCED_PROMPT_VERSION = version_num
            print(f"📌 Prompt version mode set to FIXED - will use version {version_num}")
        except ValueError:
            print(f"❌ Invalid version format '{specific_version}'. Expected format like 'v4', '4', etc.")
            print("🔄 Falling back to AUTO mode")
            PROMPT_VERSION_MODE = "auto"
            FORCED_PROMPT_VERSION = None
    else:
        print(f"❌ Invalid mode '{mode}' or missing specific_version")
        print("🔄 Keeping current mode")

def get_prompt_version_config():
    """Get current prompt version configuration"""
    return {
        "mode": PROMPT_VERSION_MODE,
        "forced_version": FORCED_PROMPT_VERSION
    }

def should_use_specific_prompt_version():
    """Check if we should use a specific prompt version instead of the latest"""
    return PROMPT_VERSION_MODE == "fixed" and FORCED_PROMPT_VERSION is not None

# Trading mode configuration
TRADING_MODE = "simulation"  # Default to simulation

def set_trading_mode(mode):
    """Set trading mode: simulation or real_world"""
    global TRADING_MODE
    valid_modes = ["simulation", "real_world"]
    if mode in valid_modes:
        TRADING_MODE = mode
        print(f"🔄 Trading mode set to: {TRADING_MODE.upper()}")
    else:
        print(f"❌ Invalid trading mode '{mode}'. Valid modes: {valid_modes}")
        print(f"🔄 Keeping current mode: {TRADING_MODE}")

def get_trading_mode():
    """Get current trading mode"""
    return TRADING_MODE

# Configuration hash system for parallel runs
import hashlib
import json

def generate_configuration_hash():
    """Generate a unique hash for the current configuration"""
    config_data = {
        "gpt_model": GPT_MODEL,
        "prompt_mode": PROMPT_VERSION_MODE,
        "forced_prompt_version": FORCED_PROMPT_VERSION,
        "trading_mode": TRADING_MODE
    }
    
    # Create a stable hash from configuration
    config_string = json.dumps(config_data, sort_keys=True)
    config_hash = hashlib.md5(config_string.encode()).hexdigest()[:8]
    
    return config_hash

def get_current_configuration():
    """Get complete current configuration"""
    return {
        "config_hash": generate_configuration_hash(),
        "gpt_model": GPT_MODEL,
        "prompt_mode": PROMPT_VERSION_MODE,
        "forced_prompt_version": FORCED_PROMPT_VERSION,
        "trading_mode": TRADING_MODE,
        "description": f"{GPT_MODEL}_{PROMPT_VERSION_MODE}_{TRADING_MODE}"
    }

# Global configuration hash for this run
CURRENT_CONFIG_HASH = None

def initialize_configuration_hash():
    """Initialize and store the configuration hash for this run"""
    global CURRENT_CONFIG_HASH
    CURRENT_CONFIG_HASH = generate_configuration_hash()
    
    # Store configuration in database
    try:
        with engine.begin() as conn:
            # Create configurations table if it doesn't exist
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS run_configurations (
                    config_hash TEXT PRIMARY KEY,
                    gpt_model TEXT NOT NULL,
                    prompt_mode TEXT NOT NULL,
                    forced_prompt_version INTEGER,
                    trading_mode TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Insert or update configuration
            config = get_current_configuration()
            conn.execute(text("""
                INSERT INTO run_configurations 
                (config_hash, gpt_model, prompt_mode, forced_prompt_version, trading_mode, description, last_used)
                VALUES (:config_hash, :gpt_model, :prompt_mode, :forced_prompt_version, :trading_mode, :description, CURRENT_TIMESTAMP)
                ON CONFLICT (config_hash) DO UPDATE SET last_used = CURRENT_TIMESTAMP
            """), config)
            
        print(f"📋 Configuration hash: {CURRENT_CONFIG_HASH}")
        print(f"📝 Description: {config['description']}")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not store configuration: {e}")
    
    return CURRENT_CONFIG_HASH

def get_current_config_hash():
    """Get the current configuration hash"""
    return CURRENT_CONFIG_HASH or initialize_configuration_hash()

def _is_gpt5_model(model_name):
    """
    Determine if a model is a GPT-5 series model that requires special API handling.
    GPT-5 models use different parameter names and restrictions.
    Uses regex patterns to catch variations like gpt-5-mini, gpt-5-nano, etc.
    """
    if not model_name:
        return False
    
    import re
    model_lower = model_name.lower()
    
    # Regex patterns for GPT-5 family models
    gpt5_patterns = [
        r'^gpt-5(-.*)?$',        # gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-turbo, etc.
        r'^o1(-.*)?$',           # o1, o1-mini, o1-preview, etc.
        r'^o3(-.*)?$'            # o3, o3-mini, o3-preview, etc.
    ]
    
    # Check if model matches any GPT-5 pattern
    for pattern in gpt5_patterns:
        if re.match(pattern, model_lower):
            return True
    
    return False

def get_model_token_params(model_name, max_tokens_value):
    """
    Get the correct token parameter for different OpenAI models.
    GPT-5 series uses 'max_completion_tokens' while GPT-4 and earlier use 'max_tokens'
    """
    if _is_gpt5_model(model_name):
        return {"max_completion_tokens": max_tokens_value}
    else:
        # GPT-4 and earlier models use max_tokens
        return {"max_tokens": max_tokens_value}

def get_model_temperature_params(model_name, temperature_value):
    """
    Get the correct temperature parameter for different OpenAI models.
    GPT-5 series only supports default temperature (1.0), while GPT-4 and earlier support custom values
    """
    if _is_gpt5_model(model_name):
        return {}  # Don't include temperature parameter for GPT-5
    else:
        # GPT-4 and earlier models support custom temperature
        return {"temperature": temperature_value}

class PromptManager:
    def __init__(self, client, session, run_id=None):
        self.client = client
        self.session = session
        self.run_id = run_id

    def ask_openai(self, prompt, system_prompt, agent_name=None, image_paths=None, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]

                if image_paths:
                    for image_path in image_paths:
                        with open(image_path, "rb") as img_file:
                            image_bytes = img_file.read()
                        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                                }
                            ]
                        })

                # Get the correct parameters based on model type
                token_params = get_model_token_params(GPT_MODEL, 1500)
                temperature_params = get_model_temperature_params(GPT_MODEL, 0.3)
                
                response = self.client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=messages,
                    #response_format="json",
                    **token_params,  # Use max_tokens or max_completion_tokens based on model
                    **temperature_params  # Use temperature or omit for GPT-5
                )
                content = response.choices[0].message.content.strip()

                # Try parsing JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    print(f"JSON Decode Error: {e}")
                    print(f"Response was: {content}")
                    
                    # Try to extract JSON from the response if it's wrapped in text
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        try:
                            return json.loads(json_match.group())
                        except json.JSONDecodeError:
                            pass
                    
                    # If we can't parse JSON, create a fallback response
                    print(f"Creating fallback response for {agent_name}")
                    print(f"Full response content: {content[:500]}...")
                    
                    # Try to extract useful content even if not JSON
                    lines = content.split('\n')
                    headlines = []
                    insights = ""
                    
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('{') and not line.startswith('}'):
                            if len(line) < 100 and ('stock' in line.lower() or 'market' in line.lower() or '$' in line):
                                headlines.append(line)
                            elif len(insights) < 200:
                                insights += line + " "
                    
                    if not headlines:
                        headlines = ["Unable to parse AI response"]
                    if not insights:
                        insights = f"Error parsing AI response: {content[:200]}..."
                        
                    return {
                        "headlines": headlines[:3],  # Limit to 3 headlines
                        "insights": insights.strip()
                    }

            except Exception as e:
                print(f"API Call Error: {e}")
                retries += 1
                if retries >= max_retries:
                    return {"headlines": ["API error occurred"], "insights": f"API error: {str(e)}"}

        return {"headlines": ["Max retries reached"], "insights": "Failed to get valid response after multiple attempts"}
