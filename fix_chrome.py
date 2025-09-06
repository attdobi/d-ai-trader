#!/usr/bin/env python3
"""
Chrome Driver Fix Script
This script diagnoses and fixes ChromeDriver issues
"""

import os
import subprocess
import undetected_chromedriver as uc
import chromedriver_autoinstaller

def fix_chrome_issues():
    """Fix common ChromeDriver issues"""

    print("🔧 Chrome Driver Diagnostic and Fix...")

    # 1. Kill existing Chrome processes
    print("1. Cleaning up existing Chrome processes...")
    try:
        result = subprocess.run(['pgrep', '-f', 'chrome'], capture_output=True, text=True)
        if result.stdout.strip():
            print(f"   Found {len(result.stdout.strip().split())} Chrome processes")
            os.system('pkill -f chrome')
            print("   ✅ Killed existing Chrome processes")
        else:
            print("   ✅ No Chrome processes running")
    except Exception as e:
        print(f"   ⚠️  Could not check Chrome processes: {e}")

    # 2. Update ChromeDriver
    print("2. Updating ChromeDriver...")
    try:
        current_version = chromedriver_autoinstaller.get_chrome_version()
        print(f"   Current Chrome version: {current_version}")
        chromedriver_autoinstaller.install()
        print("   ✅ ChromeDriver updated")
    except Exception as e:
        print(f"   ❌ ChromeDriver update failed: {e}")
        return False

    # 3. Test ChromeDriver creation
    print("3. Testing ChromeDriver...")
    try:
        options = uc.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')

        driver = uc.Chrome(options=options)
        print("   ✅ ChromeDriver created successfully")

        # Test basic functionality
        driver.get('https://www.google.com')
        title = driver.title
        print(f"   ✅ Navigation test successful: {title[:30]}...")

        driver.quit()
        print("   ✅ ChromeDriver test completed")

    except Exception as e:
        print(f"   ❌ ChromeDriver test failed: {e}")
        return False

    print("🎉 Chrome Driver fix completed successfully!")
    return True

if __name__ == "__main__":
    fix_chrome_issues()
