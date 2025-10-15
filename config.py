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
# Available models for trading:
#
# RECOMMENDED FOR REAL MONEY (GPT-4 series):
#   - gpt-4o: BEST CHOICE for trading ($2.50/$10 per 1M tokens)
#     • Supports custom temperature (0.3 for consistency)
#     • Reliable JSON mode
#     • Fast and cost-effective
#   - gpt-4o-mini: Good for testing/development ($0.15/$0.60 per 1M tokens)
#   - gpt-4-turbo: "GPT-4.1" equivalent (older, more expensive)
#
# EXPERIMENTAL (GPT-5 reasoning models):
#   - gpt-5 / gpt-5-mini: REASONING MODELS (like o1)
#     ⚠️  WARNING: Uses tokens for internal "thinking" - can hit limits!
#     • No custom temperature (fixed at 1.0)
#     • Needs 8000+ tokens (vs 2000 for GPT-4o)
#     • May exhaust tokens during reasoning, leaving no output
#     • NOT RECOMMENDED for production trading yet
#
# Note: o1/o3 models NOT supported (no system messages or JSON mode)
GPT_MODEL = "gpt-4o"  # Default: GPT-4o (most reliable for trading)

def set_gpt_model(model_name):
    """Update the global GPT model"""
    global GPT_MODEL
    valid_models = ["gpt-5", "gpt-5-mini", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "chatgpt-4o-latest"]
    if model_name in valid_models:
        GPT_MODEL = model_name
        print(f"✅ Updated GPT model to: {GPT_MODEL}")
    else:
        print(f"❌ Invalid model '{model_name}'. Valid models are: {valid_models}")
        print(f"⚠️  Keeping current model: {GPT_MODEL}")

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

# Process-specific configuration hash (no global state to avoid sharing between parallel instances)
def initialize_configuration_hash():
    """Initialize and store the configuration hash for this run"""
    config_hash = generate_configuration_hash()
    
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
            config['config_hash'] = config_hash  # Use the locally generated hash
            conn.execute(text("""
                INSERT INTO run_configurations 
                (config_hash, gpt_model, prompt_mode, forced_prompt_version, trading_mode, description, last_used)
                VALUES (:config_hash, :gpt_model, :prompt_mode, :forced_prompt_version, :trading_mode, :description, CURRENT_TIMESTAMP)
                ON CONFLICT (config_hash) DO UPDATE SET last_used = CURRENT_TIMESTAMP
            """), config)
            
        print(f"📋 Configuration hash: {config_hash}")
        print(f"📝 Description: {config['description']}")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not store configuration: {e}")
    
    # Store in environment variable for this process (process-specific isolation)
    os.environ['CURRENT_CONFIG_HASH'] = config_hash
    print(f"🔧 Set CURRENT_CONFIG_HASH environment variable to: {config_hash}")
    return config_hash

def get_current_config_hash():
    """Get the current configuration hash from environment or generate new one"""
    # First try to get from environment variable (process-specific)
    config_hash = os.environ.get('CURRENT_CONFIG_HASH')
    if config_hash:
        return config_hash
    
    # If not in environment, generate based on current settings
    print("⚠️  Config hash not found in environment, generating from current settings")
    config_hash = generate_configuration_hash()
    os.environ['CURRENT_CONFIG_HASH'] = config_hash
    print(f"🔧 Generated and set CURRENT_CONFIG_HASH environment variable to: {config_hash}")
    return config_hash

def _is_gpt5_model(model_name):
    """
    Determine if a model is a GPT-4o/newer series model that uses max_completion_tokens.
    GPT-4o and later models use different parameter names and restrictions.
    Note: gpt-4-turbo is older and uses max_tokens; gpt-4o is newer and uses max_completion_tokens.
    """
    if not model_name:
        return False
    
    import re
    model_lower = model_name.lower()
    
    # Models that use max_completion_tokens (GPT-4o series and GPT-5)
    # Exclude gpt-4-turbo which still uses the old max_tokens
    # Note: GPT-5 also doesn't support custom temperature (reasoning model behavior)
    new_model_patterns = [
        r'^gpt-5(-.*)?$',        # gpt-5, gpt-5-mini, etc.
        r'^gpt-4o(-.*)?$',       # gpt-4o, gpt-4o-mini, etc.
        r'^chatgpt-4o(-.*)?$',   # chatgpt-4o-latest, etc.
    ]
    
    # Check if model matches any new model pattern
    for pattern in new_model_patterns:
        if re.match(pattern, model_lower):
            return True
    
    return False

def get_model_token_params(model_name, max_tokens_value):
    """
    Get the correct token parameter for different OpenAI models.
    GPT-4o and newer use 'max_completion_tokens' while GPT-4-turbo and earlier use 'max_tokens'
    """
    if _is_gpt5_model(model_name):
        return {"max_completion_tokens": max_tokens_value}
    else:
        # GPT-4-turbo and earlier models use max_tokens
        return {"max_tokens": max_tokens_value}

def get_model_temperature_params(model_name, temperature_value):
    """
    Get the correct temperature parameter for different OpenAI models.
    GPT-5 models only support temperature=1.0 (default), like reasoning models.
    GPT-4o and earlier support custom temperature.
    """
    if not model_name:
        return {"temperature": temperature_value}
    
    model_lower = model_name.lower()
    
    # GPT-5 series doesn't support custom temperature (only default 1.0)
    if model_lower.startswith('gpt-5'):
        return {}  # Don't send temperature parameter for GPT-5
    else:
        # GPT-4o, GPT-4-turbo, and earlier models support custom temperature
        return {"temperature": temperature_value}

# JSON schema functions removed - now using strong system prompts instead
# as structured response_format was unreliable with GPT-4o and newer models

class PromptManager:
    def __init__(self, client, session, run_id=None):
        self.client = client
        self.session = session
        self.run_id = run_id

    def ask_openai(self, prompt, system_prompt, agent_name=None, image_paths=None, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                model_lower = GPT_MODEL.lower() if GPT_MODEL else ""
                
                # ============================================
                # PARALLEL PATH 1: GPT-5 (Reasoning Model)
                # ============================================
                if model_lower.startswith('gpt-5'):
                    print(f"🤖 Using {GPT_MODEL} (REASONING MODEL) for {agent_name}")
                    
                    # GPT-5 config: Simple messages, no extra fluff
                    messages = [
                        {"role": "system", "content": system_prompt}
                    ]
                    
                    if image_paths:
                        user_content = [{"type": "text", "text": prompt}]
                        for image_path in image_paths:
                            with open(image_path, "rb") as img_file:
                                image_bytes = img_file.read()
                            encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                            user_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                            })
                        messages.append({"role": "user", "content": user_content})
                    else:
                        messages.append({"role": "user", "content": prompt})
                    
                    # GPT-5 parameters: Lots of tokens, NO temperature
                    api_params = {
                        "model": GPT_MODEL,
                        "messages": messages,
                        "max_completion_tokens": 8000  # GPT-5 needs lots for reasoning
                        # No temperature - GPT-5 only supports default (1.0)
                    }
                    print(f"📊 GPT-5 Token limit: 8000 (includes reasoning tokens)")
                
                # ============================================
                # PARALLEL PATH 2: GPT-4o (Standard Vision Model)
                # ============================================
                elif _is_gpt5_model(GPT_MODEL):
                    print(f"🤖 Using {GPT_MODEL} for {agent_name}")
                    
                    # GPT-4o config: Standard vision format (WORKING - DON'T CHANGE!)
                    messages = [
                        {"role": "system", "content": system_prompt}
                    ]
                    
                    if image_paths:
                        user_content = [{"type": "text", "text": prompt}]
                        for image_path in image_paths:
                            with open(image_path, "rb") as img_file:
                                image_bytes = img_file.read()
                            encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                            user_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                            })
                        messages.append({"role": "user", "content": user_content})
                    else:
                        messages.append({"role": "user", "content": prompt})
                    
                    # GPT-4o parameters: Normal tokens, custom temperature
                    api_params = {
                        "model": GPT_MODEL,
                        "messages": messages,
                        "max_completion_tokens": 2000,
                        "temperature": 0.3
                    }
                    print(f"📊 Token params: max_completion_tokens=2000, temperature=0.3")
                
                # ============================================
                # PARALLEL PATH 3: GPT-4-turbo and older
                # ============================================
                else:
                    print(f"🤖 Using {GPT_MODEL} (older model) for {agent_name}")
                    
                    # Older models: Use max_tokens instead of max_completion_tokens
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                    
                    # Note: GPT-4-turbo doesn't have vision support in this path
                    api_params = {
                        "model": GPT_MODEL,
                        "messages": messages,
                        "max_tokens": 1500,
                        "temperature": 0.3
                    }
                    print(f"📊 Token params: max_tokens=1500, temperature=0.3")
                
                # Make API call
                response = self.client.chat.completions.create(**api_params)
                choice = response.choices[0]
                finish_reason = choice.finish_reason
                content = choice.message.content
                
                # ============================================
                # Response Handling - Separate Paths
                # ============================================
                
                # GPT-5 response handling
                if model_lower.startswith('gpt-5'):
                    print(f"🔍 GPT-5 Response: finish_reason='{finish_reason}', content_length={len(content) if content else 0}")
                    
                    # GPT-5 specific: 'length' means reasoning tokens exhausted
                    if finish_reason == "length":
                        print(f"⚠️  GPT-5 hit token limit during reasoning!")
                        print(f"💡 Use GPT-4o instead for reliable results")
                        if retries < max_retries - 1:
                            retries += 1
                            time.sleep(2)
                            continue
                        return {"error": f"GPT-5 exhausted reasoning tokens. Switch to GPT-4o.", "agent": agent_name}
                    
                    if not content or finish_reason != "stop":
                        print(f"⚠️  GPT-5 failed: finish_reason={finish_reason}")
                        if retries < max_retries - 1:
                            retries += 1
                            time.sleep(2)
                            continue
                        return {"error": f"GPT-5 failed: {finish_reason}", "agent": agent_name}
                
                # GPT-4o response handling (SIMPLE - this was working!)
                elif _is_gpt5_model(GPT_MODEL):
                    print(f"🔍 GPT-4o Response: finish_reason='{finish_reason}', content_length={len(content) if content else 0}")
                    
                    # Only retry on actual failures
                    if not content or finish_reason == "content_filter":
                        print(f"⚠️  GPT-4o failed: finish_reason={finish_reason}")
                        if retries < max_retries - 1:
                            retries += 1
                            time.sleep(1)
                            continue
                        return {"error": f"GPT-4o failed: {finish_reason}", "agent": agent_name}
                
                # Older models response handling
                else:
                    print(f"🔍 Response: finish_reason='{finish_reason}', content_length={len(content) if content else 0}")
                
                content = content.strip() if content else ""
                
                # Remove markdown code blocks if present (```json ... ```)
                if content.startswith('```'):
                    # Remove opening ```json or ```
                    lines = content.split('\n')
                    if lines[0].startswith('```'):
                        lines = lines[1:]  # Remove first line
                    # Remove closing ```
                    if lines and lines[-1].strip() == '```':
                        lines = lines[:-1]  # Remove last line
                    content = '\n'.join(lines).strip()

                # Try parsing JSON with enhanced error handling
                try:
                    parsed_json = json.loads(content)
                    return parsed_json
                except json.JSONDecodeError as e:
                    # Special case: GPT returned multiple objects separated by commas without outer []
                    # Example: {"action":"sell",...},\n{"action":"buy",...}
                    if '},{' in content or '},\n{' in content:
                        print(f"🔧 Detected multiple JSON objects without array brackets, fixing...")
                        # Try wrapping in array brackets
                        try:
                            wrapped = f"[{content}]"
                            parsed_json = json.loads(wrapped)
                            print(f"✅ Successfully parsed after adding array brackets")
                            return parsed_json
                        except:
                            pass  # Fall through to retry logic below
                    print(f"JSON Decode Error (attempt {retries + 1}/{max_retries}): {e}")
                    print(f"Response was: {content[:300]}...")
                    
                    # If this is not the last retry, try again with simpler instructions
                    if retries < max_retries - 1:
                        print(f"🔄 Retrying {agent_name} with enhanced JSON instructions...")
                        # Simple enhancement for retry
                        enhanced_prompt = prompt + "\n\nIMPORTANT: Return only valid JSON format. Example: {\"headlines\": \"text\", \"insights\": \"text\"}"
                        
                        # Update messages for retry
                        messages = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": enhanced_prompt}
                        ]
                        
                        # Add images back if they were provided
                        if image_paths and len(image_paths) > 0:
                            user_content = [{"type": "text", "text": enhanced_prompt}]
                            for image_path in image_paths:
                                try:
                                    with open(image_path, "rb") as img_file:
                                        image_bytes = img_file.read()
                                    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                                    user_content.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{encoded_image}"}
                                    })
                                except Exception as img_e:
                                    print(f"Error re-adding image {image_path}: {img_e}")
                            messages[-1]["content"] = user_content
                        
                        retries += 1
                        continue  # Retry the request
                    
                    # Try aggressive JSON extraction
                    import re
                    # Try to find JSON object in the response
                    json_patterns = [
                        r'\{[^{}]*"headlines"[^{}]*"insights"[^{}]*\}',  # Specific to summarizer
                        r'\{.*?"headlines".*?\}',  # Look for headlines key
                        r'\{.*?\}',  # Any JSON object
                        r'\[.*?\]'   # JSON array (for decider)
                    ]
                    
                    for pattern in json_patterns:
                        json_match = re.search(pattern, content, re.DOTALL)
                        if json_match:
                            try:
                                extracted = json.loads(json_match.group())
                                print(f"✅ Successfully extracted JSON using pattern: {pattern[:30]}...")
                                return extracted
                            except json.JSONDecodeError:
                                continue
                    
                    # Try line by line extraction
                    content_lines = content.split('\n')
                    for line in content_lines:
                        line = line.strip()
                        if (line.startswith('{') and line.endswith('}')) or (line.startswith('[') and line.endswith(']')):
                            try:
                                line_json = json.loads(line)
                                print(f"✅ Successfully extracted JSON from line")
                                return line_json
                            except json.JSONDecodeError:
                                continue
                    
                    # If all JSON parsing fails, create a structured fallback
                    print(f"❌ All JSON extraction attempts failed for {agent_name}")
                    return self._create_fallback_response(content, agent_name)

            except Exception as e:
                print(f"API Call Error: {e}")
                retries += 1
                if retries >= max_retries:
                    return {"headlines": ["API error occurred"], "insights": f"API error: {str(e)}"}

        return {"headlines": ["Max retries reached"], "insights": "Failed to get valid response after multiple attempts"}

    def _create_fallback_response(self, content, agent_name):
        """Create a structured fallback response when JSON parsing fails"""
        if agent_name and "Summarizer" in agent_name:
            # Create summarizer-style response
            lines = content.split('\n')
            headlines = []
            insights = ""
            
            for line in lines:
                line = line.strip()
                if line and not line.startswith('{') and not line.startswith('}'):
                    if len(line) < 100 and any(word in line.lower() for word in ['stock', 'market', '$', 'trading', 'earnings']):
                        headlines.append(line)
                    elif len(insights) < 300:
                        insights += line + " "
            
            return {
                "headlines": headlines[:3] if headlines else ["Unable to parse AI response"],
                "insights": insights.strip() if insights else f"Error parsing AI response: {content[:200]}..."
            }
        
        elif agent_name and "Decider" in agent_name:
            # Create decider-style response (hold decision)
            return [{
                "action": "hold",
                "ticker": "N/A",
                "amount_usd": 0,
                "reason": f"Unable to parse AI response - defaulting to hold. Original response: {content[:100]}..."
            }]
        
        else:
            # Generic fallback
            return {
                "error": "Unable to parse AI response",
                "raw_content": content[:500],
                "agent": agent_name
            }
