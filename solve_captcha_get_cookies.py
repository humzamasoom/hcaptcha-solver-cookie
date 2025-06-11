import requests
import json
import os
import sys
from seleniumbase import SB
import time

# Get API key from environment variable (GitHub secrets)
API_KEY = os.getenv('SOLVECAPTCHA_API_KEY')
if not API_KEY:
    print("ERROR: SOLVECAPTCHA_API_KEY environment variable not set")
    sys.exit(1)

SOLVE_URL = "https://api.solvecaptcha.com/in.php"
RESULT_URL = "https://api.solvecaptcha.com/res.php"

def solve_captcha(sitekey, pageurl):
    try:
        # Submit captcha
        payload = {
            'key': API_KEY,
            'method': 'hcaptcha',
            'sitekey': sitekey,
            'pageurl': pageurl,
            'json': '1'
        }
        
        print("Submitting captcha to API...")
        response = requests.post(SOLVE_URL, data=payload)
        response_data = response.json()
        
        if response_data.get('status') != 1:
            raise Exception(f"Failed to submit captcha: {response_data}")
            
        request_id = response_data['request']
        print(f"Captcha submitted successfully. Request ID: {request_id}")
        
        # Wait for solution
        max_attempts = 24  # 2 minutes maximum wait time
        attempts = 0
        
        while attempts < max_attempts:
            time.sleep(5)
            result_payload = {
                'key': API_KEY,
                'action': 'get',
                'id': request_id,
                'json': '1'
            }
            
            result = requests.get(RESULT_URL, params=result_payload)
            result_data = result.json()
            
            if result_data.get('status') == 1:
                print("Captcha solved successfully!")
                return {
                    'token': result_data['request'],
                    'useragent': result_data.get('useragent'),
                    'respKey': result_data.get('respKey')
                }
            
            attempts += 1
            print(f"Waiting for solution... Attempt {attempts}/{max_attempts}")
            
        raise Exception("Timeout waiting for captcha solution")
        
    except Exception as e:
        print(f"Error solving captcha: {str(e)}")
        raise

def get_cookies():
    with SB(uc=True, locale="en", headless=True, xvfb=True) as sb:
        url = "https://bizfileonline.sos.ca.gov/search/business"
        sb.activate_cdp_mode(url, tzone="America/Panama")
        sb.sleep(3)
        
        # First try to find search input on main page (no captcha needed)
        try:
            print("Checking for search input on main page...")
            sb.wait_for_element_present('input[placeholder="Search by name or file number"]', timeout=5)
            print("Search input found on main page - no captcha needed!")
            print("Waiting 5 seconds for cookies to be set...")
            sb.sleep(5)
            
            # Get all cookies directly
            cookies = sb.cdp.get_all_cookies()
            
            # Convert cookies to the format expected by requests
            cookie_dict = {}
            for cookie in cookies:
                cookie_dict[cookie.name] = cookie.value
                
            return cookie_dict
            
        except Exception as e:
            # Search input not found, proceed with captcha solving
            print(f"Search input not found on main page: {e}")
            print("Looking for captcha iframe...")
            
            try:
                # Wait for and switch to the iframe (only exists if captcha is present)
                print("Waiting for iframe to be present...")
                sb.wait_for_element_present('iframe#main-iframe')
                sb.switch_to_frame('iframe#main-iframe')
                print("Switched to iframe")
                
                # Extract sitekey from within the iframe
                sitekey = sb.get_attribute('div[class="h-captcha"]', 'data-sitekey')
                print(f"Found sitekey: {sitekey}")
                
                if sitekey:
                    try:
                        # Solve captcha
                        captcha_data = solve_captcha(sitekey, url)
                        
                        # Set useragent if provided
                        if captcha_data.get('useragent'):
                            sb.execute_script(
                                f'navigator.userAgent = "{captcha_data["useragent"]}";'
                            )
                        
                        # Set both response fields
                        js_script = f'''
                            document.querySelector("[name=h-captcha-response]").innerHTML = "{captcha_data['token']}";
                            document.querySelector("[name=g-recaptcha-response]").innerHTML = "{captcha_data['token']}";
                            if (typeof onCaptchaFinished === 'function') {{
                                onCaptchaFinished("{captcha_data['token']}");
                            }}
                        '''
                        sb.execute_script(js_script)
                        print("Captcha response set successfully")
                        
                    except Exception as captcha_error:
                        print(f"Failed to handle captcha: {captcha_error}")
                else:
                    print("No captcha sitekey found in iframe")
                    
            except Exception as iframe_error:
                print(f"No iframe found or iframe error: {iframe_error}")
                print("Proceeding without captcha solving")
        
        # Wait a bit for all cookies to be set
        sb.sleep(5)
        
        # Get all cookies
        cookies = sb.cdp.get_all_cookies()
        
        # Convert cookies to the format expected by requests
        cookie_dict = {}
        for cookie in cookies:
            cookie_dict[cookie.name] = cookie.value
            
        return cookie_dict

def main():
    """Main function to get cookies and output them as JSON"""
    try:
        print("Starting cookie extraction process...")
        cookies = get_cookies()
        
        # Output cookies in the same flat format as original scraper
        # This matches exactly what create_session_with_cookies() expects
        
        # Output JSON to stdout for GitHub Actions to capture
        print("Cookie extraction completed successfully!")
        print("=== COOKIES_JSON_START ===")
        print(json.dumps(cookies, indent=2))
        print("=== COOKIES_JSON_END ===")
        
        # Also save to file for artifact
        with open('cookies.json', 'w') as f:
            json.dump(cookies, f, indent=2)
        
        print("Cookies saved to cookies.json file")
        
    except Exception as e:
        print(f"Error in cookie extraction: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
