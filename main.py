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
import sys
import time
import json
import re
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
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
# Ordered: Most reliable first (helps driver warm-up), complex sites later
URLS = [
    ("Agent_Yahoo_Finance", "https://finance.yahoo.com"),             # ✅ Most reliable, simple
    ("Agent_Benzinga", "https://www.benzinga.com"),                   # ⭐ Day trading catalysts - very reliable
    ("Agent_Fox_Business", "https://www.foxbusiness.com"),            # ✅ Reliable, good content
    ("Agent_AP_Business", "https://apnews.com/business"),             # Clean, simple, AP trusted
    ("Agent_BBC_Business", "https://www.bbc.com/business"),           # International news
    ("Agent_CNBC", "https://www.cnbc.com")                            # ⭐ Great content but can crash driver initially
    # Order matters: Simple sites first warm up driver, complex sites later
    # BLOCKED: Reuters, TheStreet, Investing.com (Cloudflare), MarketWatch, Finviz
]

SUMMARY_MAX_WORKERS = max(1, int(os.getenv("SUMMARY_MAX_WORKERS", "2")))

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

SUMMARY_WITH_IMAGES_ONLY = os.getenv("SUMMARY_WITH_IMAGES_ONLY", "0") == "1"
if SUMMARY_WITH_IMAGES_ONLY:
    print("📷 SUMMARY_WITH_IMAGES_ONLY enabled — summaries will rely solely on screenshots.")

# Automatically install correct ChromeDriver version
chromedriver_autoinstaller.install()

# Track UC cache reset to avoid repeated deletions in a single run
UC_CACHE_RESET = False
UC_VERSION_MAIN = None


def chrome_major_version():
    """Detect installed Chrome major version and cache it."""
    global UC_VERSION_MAIN
    if UC_VERSION_MAIN is not None:
        return UC_VERSION_MAIN
    try:
        detected = chromedriver_autoinstaller.get_chrome_version()
        if detected:
            UC_VERSION_MAIN = int(detected.split(".")[0])
            print(f"ℹ️  Detected Chrome major version {UC_VERSION_MAIN}")
            return UC_VERSION_MAIN
    except Exception as exc:
        print(f"⚠️  Unable to determine Chrome version automatically: {exc}")
    UC_VERSION_MAIN = None
    return None


def reset_undetected_chromedriver_cache():
    """Remove undetected_chromedriver cache directory to clear stale symlinks."""
    global UC_CACHE_RESET, UC_VERSION_MAIN
    data_dir_env = os.getenv("UC_DATA_DIR")
    if data_dir_env:
        base_dir = Path(data_dir_env)
    else:
        if sys.platform == "darwin":
            base_dir = Path.home() / "Library/Application Support/undetected_chromedriver"
        elif sys.platform.startswith("win"):
            base_dir = Path(os.getenv("LOCALAPPDATA", Path.home())) / "undetected_chromedriver"
        else:
            base_dir = Path.home() / ".undetected_chromedriver"
    try:
        if base_dir.exists():
            shutil.rmtree(base_dir)
            print(f"🧹 Cleared undetected_chromedriver cache at {base_dir}")
        UC_CACHE_RESET = True
        UC_VERSION_MAIN = None
    except Exception as exc:
        print(f"⚠️  Unable to reset undetected_chromedriver cache: {exc}")

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
    def _safe_format_template(template, values):
        sentinel_map = {}
        safe_template = template
        for key, value in values.items():
            placeholder = f"{{{key}}}"
            marker = f"__PLACEHOLDER_{key.upper()}__"
            sentinel_map[marker] = value
            safe_template = safe_template.replace(placeholder, marker)

        safe_template = safe_template.replace('{', '{{').replace('}', '}}')

        for marker, value in sentinel_map.items():
            safe_template = safe_template.replace(marker, value)

        return safe_template

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
    
    if SUMMARY_WITH_IMAGES_ONLY:
        html_content_processed = "[TEXT CONTEXT DISABLED – rely on screenshots only.]"
    else:
        html_content_processed = html_content
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
                
            html_content_processed = text_content
        except Exception as e:
            print(f"Failed to parse HTML content for {agent_name}: {e}")
            # Fallback: just truncate the raw HTML
            if len(html_content_processed) > 5000:
                html_content_processed = html_content_processed[:5000] + "... [content truncated]"

    # Only include images if they were successfully saved and are reasonably sized
    IMAGE_SIZE_LIMIT = 1_500_000  # 1.5 MB limit per image
    valid_image_paths = []
    for img_path in image_paths:
        if os.path.exists(img_path):
            file_size = os.path.getsize(img_path)
            if file_size < IMAGE_SIZE_LIMIT:
                valid_image_paths.append(img_path)
            else:
                print(f"Skipping large image {img_path} ({file_size} bytes >= {IMAGE_SIZE_LIMIT})")
        else:
            print(f"⚠️  Image path missing: {img_path}")

    # Use versioned prompt template
    prompt = _safe_format_template(
        user_prompt_template,
        {
            "content": html_content_processed,
            "feedback_context": feedback_context,
        }
    )

    screenshot_instructions = []
    if valid_image_paths:
        screenshot_instructions.append("SCREENSHOT CONTEXT:")
        for idx, path in enumerate(valid_image_paths, 1):
            screenshot_instructions.append(f"- Screenshot {idx}: {os.path.basename(path)}")
    elif SUMMARY_WITH_IMAGES_ONLY:
        screenshot_instructions.append("SCREENSHOT CONTEXT: No screenshots available (check capture pipeline).")

    # Add instruction to ignore popups and extract visible content
    prompt += """\n
IMPORTANT: If you see privacy notices, cookie consent dialogs, login prompts, or "Press and Hold" overlays in the screenshots:
- IGNORE the popup overlay completely
- Look BEHIND/AROUND the popup to the visible webpage content
- Extract headlines and news that are visible on the page
- Focus on the financial news content that is readable despite any overlays

Most financial news websites still show headlines and articles even with popups visible."""

    if screenshot_instructions:
        prompt += "\n\n" + "\n".join(screenshot_instructions)
    
    # Use versioned system prompt with feedback context
    system_prompt = system_prompt_template + f"\n\n{feedback_context}"
    
    print(f"🖼️ {agent_name}: passing {len(valid_image_paths)} image(s) to OpenAI")
    if valid_image_paths:
        for idx, img in enumerate(valid_image_paths, 1):
            try:
                print(f"   • Image {idx}: {img} ({os.path.getsize(img)} bytes)")
            except OSError:
                print(f"   • Image {idx}: {img} (size unavailable)")

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
    # Basic guard: ensure at least one window handle is available
    try:
        handles = web_driver.window_handles
    except Exception as e:
        print(f"Driver session invalid for {agent_name}: {e}")
        raise e
    if not handles:
        print(f"⚠️  No window handles for {agent_name} - attempting to continue with driver.get")
    
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
        if isinstance(summary_data, list):
            summary_data = summary_data[0] if summary_data else {}
        print(f"🧾 {agent_name} summary response: {summary_data}")
    except Exception as e:
        summary_data = {"error": f"Summary failed: {e}"}
        print(f"❌ {agent_name} summary error: {e}")

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

def _process_agent_sequence(agent_sequence, worker_id):
    """Process a sequence of agents using a dedicated Chrome driver"""
    if not agent_sequence:
        return
    global UC_VERSION_MAIN

    current_driver = None
    try:
        for agent_idx, (agent_name, url) in enumerate(agent_sequence, 1):
            try:
                driver_ok = False
                max_driver_attempts = 3
                
                for attempt in range(max_driver_attempts):
                    if current_driver:
                        try:
                            current_driver.current_url
                            current_driver.title
                            driver_ok = True
                            break
                        except Exception as session_error:
                            print(f"[Worker {worker_id}] ⚠️  Driver invalid for {agent_name} (attempt {attempt + 1}/{max_driver_attempts}): {session_error}")
                            try:
                                current_driver.quit()
                            except Exception:
                                pass
                            current_driver = None
                            time.sleep(2)
                    
                    # Try to create a fresh driver
                    try:
                        driver_kwargs = {"options": create_chrome_options()}
                        version_main = chrome_major_version()
                        if version_main:
                            driver_kwargs["version_main"] = version_main
                        current_driver = uc.Chrome(**driver_kwargs)
                        print(f"[Worker {worker_id}] ✅ New driver created for {agent_name}")
                        time.sleep(2)  # Allow Chrome to finish bootstrapping
                        driver_ok = True
                        break
                    except Exception as create_error:
                        print(f"[Worker {worker_id}] ❌ Failed to create driver (attempt {attempt + 1}/{max_driver_attempts}): {create_error}")
                        error_text = str(create_error)
                        if (
                            isinstance(create_error, FileNotFoundError)
                            or "undetected_chromedriver" in error_text
                            or "only supports Chrome version" in error_text
                        ):
                            reset_undetected_chromedriver_cache()
                            # Re-detect Chrome version after cache reset
                            globals()["UC_VERSION_MAIN"] = None
                            chrome_major_version()
                        current_driver = None
                        time.sleep(2)
                        continue
                
                if not driver_ok or not current_driver:
                    print(f"[Worker {worker_id}] ❌ Could not get working driver for {agent_name}, skipping")
                    try:
                        error_summary = {
                            "agent": agent_name,
                            "timestamp": RUN_TIMESTAMP,
                            "run_id": RUN_TIMESTAMP,
                            "summary": {
                                "headlines": [],
                                "insights": "Driver initialization failed - skipped"
                            }
                        }
                        store_summary(error_summary)
                    except Exception:
                        pass
                    continue
                
                print(f"[Worker {worker_id}] 📰 Processing agent {agent_idx}/{len(agent_sequence)}: {agent_name}")

                summary = None
                for page_attempt in range(2):
                    try:
                        summary = summarize_page(agent_name, url, current_driver)
                        break
                    except WebDriverException as driver_exc:
                        if "no such window" in str(driver_exc).lower():
                            print(f"[Worker {worker_id}] ⚠️  Driver window missing for {agent_name}, rebuilding (attempt {page_attempt + 1}/2)")
                            try:
                                if current_driver:
                                    current_driver.quit()
                            except Exception:
                                pass
                            current_driver = None
                            time.sleep(2)
                            try:
                                driver_kwargs = {"options": create_chrome_options()}
                                version_main = chrome_major_version()
                                if version_main:
                                    driver_kwargs["version_main"] = version_main
                                current_driver = uc.Chrome(**driver_kwargs)
                                print(f"[Worker {worker_id}] ✅ Recreated driver for {agent_name}")
                                time.sleep(2)  # Allow Chrome to fully initialize after recreation
                                continue
                            except Exception as recreate_err:
                                print(f"[Worker {worker_id}] ❌ Failed to recreate driver after window loss: {recreate_err}")
                                current_driver = None
                                break
                        raise

                if not summary:
                    raise RuntimeError("Unable to capture summary after driver recovery attempts")

                store_summary(summary)
                print(f"[Worker {worker_id}] ✅ Stored summary for {agent_name}")
                time.sleep(1)

            except Exception as e:
                print(f"[Worker {worker_id}] Error processing {agent_name} ({url}): {e}")

                try:
                    if current_driver:
                        current_driver.quit()
                except Exception:
                    pass
                current_driver = None
                time.sleep(2)
                continue
                
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
                    print(f"[Worker {worker_id}] Stored error summary for {agent_name}")
                except Exception:
                    pass
                
                try:
                    if current_driver:
                        current_driver.quit()
                except Exception:
                    pass
                current_driver = None
                time.sleep(2)
                continue
    finally:
        try:
            if current_driver:
                current_driver.quit()
                print(f"[Worker {worker_id}] Chrome driver cleaned up")
        except Exception as cleanup_error:
            print(f"[Worker {worker_id}] Error cleaning up driver: {cleanup_error}")


def run_summary_agents():
    initialize_database()
    
    worker_count = max(1, min(SUMMARY_MAX_WORKERS, len(URLS)))
    if worker_count == 1:
        _process_agent_sequence(URLS, worker_id=1)
        return
    
    # Distribute agents across workers in round-robin fashion
    batches = [[] for _ in range(worker_count)]
    for idx, entry in enumerate(URLS):
        batches[idx % worker_count].append(entry)
    
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_process_agent_sequence, batch, worker_id + 1): worker_id + 1
            for worker_id, batch in enumerate(batches)
            if batch
        }
        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[Worker {worker_id}] ❌ Batch processing failed: {e}")

if __name__ == "__main__":
    run_summary_agents()
