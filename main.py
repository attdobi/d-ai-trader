# --- D-AI-Trader bootstrap (auto-inserted) ---
import os as _os, sys as _sys
_repo_root = _os.environ.get("DAI_TRADER_ROOT") or _os.path.dirname(_os.path.abspath(__file__))
_os.environ.setdefault("DAI_TRADER_ROOT", _repo_root)
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
_os.environ.setdefault("DAI_DISABLE_UC", "1")
try:
    import sitecustomize  # noqa: F401
except Exception:
    pass
# --- end bootstrap ---

import os
import time
import json
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from sqlalchemy import text
from config import engine, api_key, PromptManager, session, get_current_config_hash, set_gpt_model
import chromedriver_autoinstaller
import openai
import undetected_chromedriver as uc
from feedback_agent import TradeOutcomeTracker

# Apply model from environment if specified
if _os.environ.get("DAI_GPT_MODEL"):
    set_gpt_model(_os.environ["DAI_GPT_MODEL"])
from bs4 import BeautifulSoup

# Configuration - Optimized for day trading (6 sources max for cost efficiency)
# Using sites with minimal popups and real-time trading news
URLS = [
    ("Agent_CNBC", "https://www.cnbc.com"),                    # Breaking news, market movers
    ("Agent_Benzinga", "https://www.benzinga.com"),            # ⭐ Best for day trading - real-time catalysts
    ("Agent_MarketWatch", "https://www.marketwatch.com"),      # Market trends, sector rotation
    ("Agent_Yahoo_Finance", "https://finance.yahoo.com"),      # Stock-specific news, earnings
    ("Agent_Finviz", "https://finviz.com/news.ashx"),          # Top gainers/losers, market heat map
    ("Agent_Fox_Business", "https://www.foxbusiness.com")      # Market sentiment, trading ideas
    # Removed for cost/reliability: Bloomberg (paywall), SeekingAlpha (login), CNN Money (popups)
]

# Use absolute path for screenshot directory to avoid working directory issues
import os
import pytz
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, "screenshots")

# Use Pacific Time for timestamps
PACIFIC_TZ = pytz.timezone('US/Pacific')
RUN_TIMESTAMP = datetime.now(PACIFIC_TZ).strftime("%Y%m%dT%H%M%S")

# Include configuration hash to isolate screenshots for parallel runs
CONFIG_HASH = get_current_config_hash()
RUN_DIR = os.path.join(SCREENSHOT_DIR, CONFIG_HASH, RUN_TIMESTAMP)
os.makedirs(RUN_DIR, exist_ok=True)

print(f"Screenshot directory: {SCREENSHOT_DIR}")
print(f"Run directory: {RUN_DIR}")

# Automatically install correct ChromeDriver version
chromedriver_autoinstaller.install()

# Function to create fresh Chrome options (never reuse)
def create_chrome_options():
    """Create fresh ChromeOptions - never reuse the same object"""
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")  #This is stealthier than old headless
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    options.add_argument("--disable-extensions")  # Disable extensions
    options.add_argument("--disable-plugins")  # Disable plugins
    options.add_argument("--disable-images")  # Disable image loading for faster performance
    return options

# Global driver variable (will be created fresh for each run)
driver = None

# PromptManager instance
prompt_manager = PromptManager(client=openai, session=session, run_id=RUN_TIMESTAMP)

# Initialize feedback tracker
feedback_tracker = TradeOutcomeTracker()

def initialize_database():
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS summaries (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                agent TEXT,
                timestamp TIMESTAMP,
                run_id TEXT,
                data JSONB
            )
        '''))

def get_openai_summary(agent_name, html_content, image_paths):
    # Get versioned prompt for SummarizerAgent
    from prompt_manager import get_active_prompt
    try:
        prompt_data = get_active_prompt("SummarizerAgent")
        system_prompt_template = prompt_data["system_prompt"]
        user_prompt_template = prompt_data["user_prompt_template"]
        prompt_version = prompt_data["version"]
        print(f"🔧 Using SummarizerAgent prompt v{prompt_version} (UNIFIED)")
    except Exception as e:
        print(f"⚠️  Could not load unified prompt: {e}, using fallback")
        # Fallback to basic prompts
        system_prompt_template = "You are a financial analysis assistant specialized in extracting actionable trading insights from news articles."
        user_prompt_template = """Analyze the following financial news and extract the most important actionable insights.

Content: {content}

Return a JSON object with:
- "headlines": A list of 3-5 most important headlines
- "insights": A paragraph summarizing key trading opportunities and risks"""
    
    # Get feedback context for summarizer
    feedback_context = ""
    try:
        latest_feedback = feedback_tracker.get_latest_feedback()
        if latest_feedback:
            summarizer_feedback = latest_feedback.get('summarizer_feedback', '')
            if summarizer_feedback and summarizer_feedback != 'null':
                # Parse JSON feedback if it's a string
                if isinstance(summarizer_feedback, str):
                    try:
                        summarizer_feedback = json.loads(summarizer_feedback)
                    except:
                        pass
                
                feedback_context = f"\nPERFORMANCE FEEDBACK: {summarizer_feedback}\nIncorporate this guidance to improve analysis quality."
    except Exception as e:
        print(f"Failed to get summarizer feedback: {e}")

    # Reduce HTML content length to avoid rate limiting
    # Extract only the most relevant content from the HTML
    
    # Remove script and style tags
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
    
    # Extract text content more efficiently
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text content
        text_content = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text_content.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text_content = ' '.join(chunk for chunk in chunks if chunk)
        
        # Limit content length to avoid rate limiting (reduced from 10000 to 5000)
        if len(text_content) > 5000:
            text_content = text_content[:5000] + "... [content truncated]"
            
        html_content = text_content
    except Exception as e:
        print(f"Failed to parse HTML content for {agent_name}: {e}")
        # Fallback: just truncate the raw HTML
        if len(html_content) > 5000:
            html_content = html_content[:5000] + "... [content truncated]"

    # Use versioned prompt template
    prompt = user_prompt_template.format(
        content=html_content,
        feedback_context=feedback_context
    )
    
    # Add instruction to ignore popups and extract visible content
    prompt += """\n
IMPORTANT: If you see privacy notices, cookie consent dialogs, login prompts, or "Press and Hold" overlays in the screenshots:
- IGNORE the popup overlay completely
- Look BEHIND/AROUND the popup to the visible webpage content
- Extract headlines and news that are visible on the page
- Focus on the financial news content that is readable despite any overlays

Most financial news websites still show headlines and articles even with popups visible."""
    
    # Use versioned system prompt with feedback context
    system_prompt = system_prompt_template + f"\n\n{feedback_context}"
    
    # Only include images if they were successfully saved and are reasonably sized
    valid_image_paths = []
    for img_path in image_paths:
        if os.path.exists(img_path):
            file_size = os.path.getsize(img_path)
            # Only include images smaller than 1MB to avoid rate limiting
            if file_size < 1024 * 1024:
                valid_image_paths.append(img_path)
            else:
                print(f"Skipping large image {img_path} ({file_size} bytes)")
    
    return prompt_manager.ask_openai(
        prompt, 
        system_prompt, 
        agent_name="SummarizerAgent", 
        image_paths=valid_image_paths
    )

def try_click_popup(web_driver, agent_name):
    """
    Try to dismiss privacy popups and consent dialogs.
    Returns True if a popup was dismissed, False otherwise.
    """
    def click_button(button):
        try:
            web_driver.execute_script("arguments[0].click();", button)
            print(f"✅ Clicked button via JS: '{button.text.strip()}'")
            time.sleep(2)  # Wait for popup to close
            return True
        except Exception as e:
            print(f"JavaScript click failed: {e}")
            return False

    keywords = ["agree", "accept", "ok", "got it", "understand", "continue", "allow", "dismiss"]

    if agent_name == "Agent_Fox_Business":
        print("Skipping popup checks for Fox Business.")
        return False

    try:
        # Try multiple strategies for different sites
        
        # Strategy 1: Site-specific handling
        if agent_name == "Agent_CNN_Money":
            print("🔍 CNN Money: Looking for consent buttons...")
            xpaths = [
                "//button[contains(., 'Agree')]",
                "//button[contains(., 'Accept')]",
                "//button[contains(., 'Continue')]",
                "//button[@data-testid='agree-button']",
                "//button[@class='consent-button']"
            ]
            for xpath in xpaths:
                try:
                    buttons = web_driver.find_elements(By.XPATH, xpath)
                    for button in buttons:
                        try:
                            # Try both regular click and JS click
                            if button.is_displayed():
                                button.click()
                                print(f"✅ CNN Money: Clicked '{button.text.strip()}' via regular click")
                                time.sleep(5)
                                return True
                        except:
                            if click_button(button):
                                print(f"✅ CNN Money: Clicked via JS")
                                time.sleep(5)
                                return True
                except:
                    continue
        
        if agent_name == "Agent_SeekingAlpha":
            print("🔍 SeekingAlpha: Looking for login/consent overlays...")
            # SeekingAlpha often has "Press and Hold" or sign-in overlays
            selectors = [
                "//button[contains(., 'Maybe later')]",
                "//button[contains(., 'Not now')]",
                "//button[contains(., 'Skip')]",
                "//a[contains(., 'Continue')]",
                "//button[contains(@aria-label, 'close')]",
                "//button[@class*='close']"
            ]
            for selector in selectors:
                try:
                    buttons = web_driver.find_elements(By.XPATH, selector)
                    for button in buttons[:3]:  # Try first 3 matches
                        try:
                            if button.is_displayed():
                                button.click()
                                print(f"✅ SeekingAlpha: Dismissed overlay via '{button.text.strip()}'")
                                time.sleep(5)
                                return True
                        except:
                            pass
                except:
                    continue
        
        # Strategy 2: Find all buttons and click consent-related ones
        try:
            buttons = WebDriverWait(web_driver, 3).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, 'button'))
            )
            
            for btn in buttons:
                try:
                    text = btn.text.lower().strip()
                    if text and any(keyword in text for keyword in keywords):
                        if click_button(btn):
                            print(f"✅ Popup dismissed via button: '{btn.text.strip()}'")
                            time.sleep(3)  # Wait for content to load
                            return True
                except:
                    continue
        except:
            pass
        
        # Strategy 3: Try common CSS selectors for consent buttons
        selectors = [
            "button[data-testid*='accept']",
            "button[data-testid*='agree']",
            "button[id*='accept']",
            "button[id*='consent']",
            ".consent-button",
            ".cookie-accept"
        ]
        
        for selector in selectors:
            try:
                button = web_driver.find_element(By.CSS_SELECTOR, selector)
                if button.is_displayed() and button.is_enabled():
                    if click_button(button):
                        print(f"✅ Popup dismissed via selector: {selector}")
                        time.sleep(3)
                        return True
            except:
                continue

        print("ℹ️  No popup found or already dismissed.")
        return False
        
    except Exception as e:
        print(f"Error in try_click_popup for {agent_name}: {e}")
        return False

def summarize_page(agent_name, url, web_driver):
    """
    Summarize a webpage using the provided webdriver
    """
    # Check if driver session is still valid
    try:
        web_driver.current_url  # Test if session is alive
    except Exception as e:
        print(f"Driver session invalid for {agent_name}: {e}")
        raise e
    
    # Special handling for Yahoo Finance which can be slow
    if "yahoo.com" in url.lower():
        print(f"Loading {agent_name} (Yahoo Finance - extended timeout)")
        try:
            # Set page load timeout for Yahoo Finance
            web_driver.set_page_load_timeout(180)  # 3 minutes
            web_driver.get(url)
            time.sleep(8)  # Extra wait for Yahoo Finance
        except Exception as e:
            print(f"Timeout loading {agent_name}, retrying with shorter timeout: {e}")
            try:
                web_driver.set_page_load_timeout(60)  # Fallback to 1 minute
                web_driver.get(url)
                time.sleep(5)
            except Exception as e2:
                print(f"Failed to load {agent_name} after retry: {e2}")
                # Return empty summary if we can't load the page
                return {
                    "agent": agent_name,
                    "timestamp": RUN_TIMESTAMP,
                    "summary": {"error": f"Failed to load page: {e2}"},
                    "screenshot_paths": [],
                    "run_id": RUN_TIMESTAMP
                }
    else:
        # Normal handling for other sites
        web_driver.get(url)
        time.sleep(5)

    # Reset timeout to default after successful page load
    try:
        web_driver.set_page_load_timeout(30)  # Reset to 30 seconds default
    except:
        pass

    popup_dismissed = try_click_popup(web_driver, agent_name)
    
    # If popup was dismissed, wait for content to fully load
    if popup_dismissed:
        print(f"⏳ Waiting for content to load after popup dismissal...")
        time.sleep(5)
        # Scroll to load dynamic content
        web_driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(2)

    screenshot_path_1 = os.path.join(RUN_DIR, f"{agent_name}_1.png")
    screenshot_saved_1 = False
    try:
        web_driver.save_screenshot(screenshot_path_1)
        if os.path.exists(screenshot_path_1) and os.path.getsize(screenshot_path_1) > 0:
            screenshot_saved_1 = True
            print(f"Screenshot 1 saved successfully for {agent_name}: {screenshot_path_1}")
        else:
            print(f"Screenshot 1 file not created or empty for {agent_name}")
    except Exception as e:
        print(f"Screenshot 1 failed for {agent_name}: {e}")
        time.sleep(3)
        try:
            web_driver.save_screenshot(screenshot_path_1)
            if os.path.exists(screenshot_path_1) and os.path.getsize(screenshot_path_1) > 0:
                screenshot_saved_1 = True
                print(f"Screenshot 1 retry successful for {agent_name}")
            else:
                print(f"Screenshot 1 retry failed - file not created for {agent_name}")
        except Exception as e:
            print(f"Retry failed for Screenshot 1: {e}")

    try:
        web_driver.execute_script("window.scrollBy(0, window.innerHeight * 0.875);")
    except Exception as e:
        print(f"Scroll failed for {agent_name}: {e}")

    time.sleep(2)

    screenshot_path_2 = os.path.join(RUN_DIR, f"{agent_name}_2.png")
    screenshot_saved_2 = False
    try:
        web_driver.save_screenshot(screenshot_path_2)
        if os.path.exists(screenshot_path_2) and os.path.getsize(screenshot_path_2) > 0:
            screenshot_saved_2 = True
            print(f"Screenshot 2 saved successfully for {agent_name}: {screenshot_path_2}")
        else:
            print(f"Screenshot 2 file not created or empty for {agent_name}")
    except Exception as e:
        print(f"Screenshot 2 failed for {agent_name}: {e}")
        time.sleep(3)
        try:
            web_driver.save_screenshot(screenshot_path_2)
            if os.path.exists(screenshot_path_2) and os.path.getsize(screenshot_path_2) > 0:
                screenshot_saved_2 = True
                print(f"Screenshot 2 retry successful for {agent_name}")
            else:
                print(f"Screenshot 2 retry failed - file not created for {agent_name}")
        except Exception as e:
            print(f"Retry failed for Screenshot 2: {e}")

    try:
        html = web_driver.page_source
    except Exception as e:
        print(f"Failed to capture page source for {agent_name}: {e}")
        html = ""

    # Only include screenshot paths that were actually saved
    saved_screenshots = []
    if screenshot_saved_1:
        saved_screenshots.append(screenshot_path_1)
    if screenshot_saved_2:
        saved_screenshots.append(screenshot_path_2)

    try:
        summary_data = get_openai_summary(agent_name, html, saved_screenshots)
    except Exception as e:
        summary_data = {"error": f"Summary failed: {e}"}

    summary = {
        "agent": agent_name,
        "timestamp": RUN_TIMESTAMP,
        "summary": summary_data,
        "screenshot_paths": saved_screenshots,
        "run_id": RUN_TIMESTAMP
    }

    return summary

def store_summary(summary):
    config_hash = get_current_config_hash()
    with engine.begin() as conn:
        # Parse timestamp and ensure it's timezone-aware (Pacific)
        timestamp_str = summary['timestamp']
        try:
            timestamp_dt = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%S")
            # Make it timezone-aware in Pacific time
            timestamp_dt = PACIFIC_TZ.localize(timestamp_dt)
        except:
            # Fallback to current Pacific time
            timestamp_dt = datetime.now(PACIFIC_TZ)
        
        conn.execute(text(
            "INSERT INTO summaries (config_hash, agent, timestamp, run_id, data) VALUES (:config_hash, :agent, :timestamp, :run_id, :data)"
        ), {
            "config_hash": config_hash,
            "agent": summary['agent'],
            "timestamp": timestamp_dt,
            "run_id": summary['run_id'],
            "data": json.dumps(summary)
        })

def run_summary_agents():
    initialize_database()
    current_driver = None
    
    try:
        # Create a fresh Chrome driver for this run
        print("Creating new Chrome driver for summarizer run")
        current_driver = uc.Chrome(options=create_chrome_options())
        print("Chrome driver created successfully")
        
        for agent_name, url in URLS:
            try:
                # Check if driver is still alive before each agent
                try:
                    current_driver.current_url
                except Exception as session_error:
                    print(f"Driver session lost before {agent_name}, creating new driver: {session_error}")
                    try:
                        current_driver.quit()
                    except:
                        pass
                    current_driver = uc.Chrome(options=create_chrome_options())
                    print(f"New driver created for {agent_name}")
                
                summary = summarize_page(agent_name, url, current_driver)
                store_summary(summary)
                print(f"Stored summary for {agent_name}")
                # Small delay between agents to prevent overwhelming the system
                time.sleep(3)
                
            except Exception as e:
                print(f"Error processing {agent_name} ({url}): {e}")
                
                # Store error summary so we know what failed
                try:
                    error_summary = {
                        "agent": agent_name,
                        "timestamp": RUN_TIMESTAMP,
                        "run_id": RUN_TIMESTAMP,
                        "summary": {
                            "headlines": [],
                            "insights": f"API error: {str(e)}"
                        }
                    }
                    store_summary(error_summary)
                    print(f"Stored error summary for {agent_name}")
                except:
                    pass
                
                # Try to create a new driver for the next agent if this one failed
                try:
                    if current_driver:
                        current_driver.quit()
                except:
                    pass
                
                # Wait a bit before recreating driver to let system recover
                time.sleep(2)
                
                try:
                    current_driver = uc.Chrome(options=create_chrome_options())
                    print(f"Created new driver after {agent_name} error")
                except Exception as driver_error:
                    print(f"Failed to create new driver: {driver_error}")
                    # Set to None so we don't try to use it
                    current_driver = None
                continue
                
    except Exception as e:
        print(f"Failed to create initial Chrome driver: {e}")
    finally:
        # Always cleanup the driver
        try:
            if current_driver:
                current_driver.quit()
                print("Chrome driver cleaned up")
        except Exception as e:
            print(f"Error cleaning up driver: {e}")

if __name__ == "__main__":
    run_summary_agents()
