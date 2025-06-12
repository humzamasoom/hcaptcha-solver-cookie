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

def create_session_with_cookies(cookies):
    """Create a new requests session with the provided cookies"""
    session = requests.Session()
    session.cookies.update(cookies)
    
    # Set default headers
    session.headers.update({
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.7",
        "authorization": "undefined",
        "priority": "u=1, i",
        "referer": "https://bizfileonline.sos.ca.gov/search/business",
        "sec-ch-ua": '"Brave";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-gpc": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    })
    
    return session

def is_request_blocked(response):
    """Check if the request was blocked or failed"""
    if response.status_code in [401, 403, 429, 500, 502, 503, 504]:
        return True
    
    try:
        # Check if response contains error indicators
        if response.headers.get('content-type', '').startswith('application/json'):
            data = response.json()
            if 'error' in data or 'Error' in data:
                return True
    except:
        pass
    
    return False

def get_business_details_with_retry(business_id, session, max_retries=3):
    """Get business details with automatic retry and fresh cookies if blocked"""
    url = f"https://bizfileonline.sos.ca.gov/api/FilingDetail/business/{business_id}/false"
    
    for attempt in range(max_retries):
        try:
            response = session.get(url)
            
            if is_request_blocked(response):
                print(f"Request blocked (status {response.status_code}), getting fresh cookies... (Attempt {attempt + 1}/{max_retries})")
                
                # Get fresh cookies and update session
                fresh_cookies = get_cookies()
                session.cookies.update(fresh_cookies)
                continue
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            print(f"Error getting business details (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
            
            # Get fresh cookies for retry
            print("Getting fresh cookies for retry...")
            fresh_cookies = get_cookies()
            session.cookies.update(fresh_cookies)
    
    raise Exception(f"Failed to get business details after {max_retries} attempts")

def search_businesses_with_retry(file_number, session, max_retries=3):
    """Search businesses with automatic retry and fresh cookies if blocked"""
    url = "https://bizfileonline.sos.ca.gov/api/Records/businesssearch"
    
    # Add content-type header for POST request
    headers = {"content-type": "application/json"}
    
    data = {
        "SEARCH_VALUE": file_number,
        "SEARCH_FILTER_TYPE_ID": "0",
        "SEARCH_TYPE_ID": "1",
        "FILING_TYPE_ID": "",
        "STATUS_ID": "",
        "FILING_DATE": {
            "start": None,
            "end": None
        },
        "CORPORATION_BANKRUPTCY_YN": False,
        "CORPORATION_LEGAL_PROCEEDINGS_YN": False,
        "OFFICER_OBJECT": {
            "FIRST_NAME": "",
            "MIDDLE_NAME": "",
            "LAST_NAME": ""
        },
        "NUMBER_OF_FEMALE_DIRECTORS": "99",
        "NUMBER_OF_UNDERREPRESENTED_DIRECTORS": "99",
        "COMPENSATION_FROM": "",
        "COMPENSATION_TO": "",
        "SHARES_YN": False,
        "OPTIONS_YN": False,
        "BANKRUPTCY_YN": False,
        "FRAUD_YN": False,
        "LOANS_YN": False,
        "AUDITOR_NAME": ""
    }

    for attempt in range(max_retries):
        try:
            response = session.post(url, headers=headers, json=data)
            
            if is_request_blocked(response):
                print(f"Search request blocked (status {response.status_code}), getting fresh cookies... (Attempt {attempt + 1}/{max_retries})")
                
                # Get fresh cookies and update session
                fresh_cookies = get_cookies()
                session.cookies.update(fresh_cookies)
                continue
            
            response.raise_for_status()
            result = response.json()
            print(f"Search completed successfully for file number: {file_number}")
            return result
            
        except Exception as e:
            print(f"Error searching businesses (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
            
            # Get fresh cookies for retry
            print("Getting fresh cookies for retry...")
            fresh_cookies = get_cookies()
            session.cookies.update(fresh_cookies)
    
    raise Exception(f"Failed to search businesses after {max_retries} attempts")

def scrape_business_data(file_number, session):
    """Scrape data for a single file number using existing session"""
    print(f"\n{'='*50}")
    print(f"Processing file number: {file_number}")
    print(f"{'='*50}")
    
    scraped_data = []
    
    try:
        # Search for businesses
        print("Searching for businesses...")
        search_results = search_businesses_with_retry(file_number, session)
        
        # Extract business IDs from the results
        if 'rows' in search_results:
            # The rows is a dictionary where keys are the business IDs
            for business_id, business_data in search_results['rows'].items():
                print(f"\nFetching details for business ID: {business_id}")
                
                # Get detailed information for each business
                details = get_business_details_with_retry(business_id, session)
                
                # Add the scraped data to our results
                scraped_data.append({
                    'file_number': file_number,
                    'business_id': business_id,
                    'search_data': business_data,
                    'details': details
                })
                
                print(f"Successfully scraped data for business ID: {business_id}")
        else:
            print("No results found or unexpected response format")
            print(json.dumps(search_results, indent=2))
            
    except Exception as e:
        print(f"Error during scraping for file number {file_number}: {e}")
        # Don't raise the exception, just log it and continue with next file number
        
    return scraped_data

def parse_file_numbers(file_numbers_input):
    """Parse file numbers from various input formats"""
    if not file_numbers_input:
        return ['202250419109']  # Default file number
    
    # Try to parse as JSON array first
    try:
        parsed = json.loads(file_numbers_input)
        if isinstance(parsed, list):
            return [str(num).strip() for num in parsed if str(num).strip()]
    except:
        pass
    
    # Parse as comma-separated values
    file_numbers = [num.strip() for num in file_numbers_input.split(',') if num.strip()]
    
    if not file_numbers:
        return ['202250419109']  # Default if parsing fails
    
    return file_numbers

def scrape_multiple_businesses(file_numbers):
    """Main scraping function that handles multiple file numbers"""
    print(f"Starting bulk scrape for {len(file_numbers)} file numbers: {file_numbers}")
    
    # Get initial cookies
    print("Getting initial cookies and solving captcha...")
    cookies = get_cookies()
    print("Initial cookies obtained successfully")
    
    # Create session with cookies (no proxy)
    session = create_session_with_cookies(cookies)
    
    all_scraped_data = {
        'metadata': {
            'total_file_numbers': len(file_numbers),
            'file_numbers_processed': file_numbers,
            'scrape_timestamp': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        },
        'results': {}
    }
    
    try:
        for i, file_number in enumerate(file_numbers, 1):
            print(f"\n\nProcessing {i}/{len(file_numbers)}: {file_number}")
            
            try:
                scraped_data = scrape_business_data(file_number, session)
                all_scraped_data['results'][file_number] = {
                    'success': True,
                    'businesses_found': len(scraped_data),
                    'data': scraped_data
                }
                print(f"✅ Successfully processed {file_number}: {len(scraped_data)} businesses found")
                
            except Exception as e:
                print(f"❌ Failed to process {file_number}: {e}")
                all_scraped_data['results'][file_number] = {
                    'success': False,
                    'error': str(e),
                    'data': []
                }
            
            # Add delay between requests to be respectful
            if i < len(file_numbers):
                print("Waiting 2 seconds before next file number...")
                time.sleep(2)
                
    except Exception as e:
        print(f"Critical error during bulk scraping: {e}")
        raise
    finally:
        session.close()
    
    return all_scraped_data

def main():
    """Main function to run the complete scraping process"""
    try:
        # Get file numbers from environment variable
        file_numbers_input = os.getenv('FILE_NUMBERS', '202250419109')
        file_numbers = parse_file_numbers(file_numbers_input)
        
        print(f"Starting California business scraper for {len(file_numbers)} file numbers")
        print(f"File numbers to process: {file_numbers}")
        
        # Run the scraper for multiple file numbers
        all_scraped_data = scrape_multiple_businesses(file_numbers)
        
        # Count total businesses found
        total_businesses = sum(
            result.get('businesses_found', 0) 
            for result in all_scraped_data['results'].values()
        )
        
        # Count successful vs failed file numbers
        successful_files = sum(
            1 for result in all_scraped_data['results'].values() 
            if result.get('success', False)
        )
        
        if total_businesses > 0:
            # Create filename with file number count
            if len(file_numbers) == 1:
                output_file = f'scraped_data_{file_numbers[0]}.json'
            else:
                output_file = f'scraped_data_bulk_{len(file_numbers)}_files.json'
            
            # Save as JSON
            with open(output_file, 'w') as f:
                json.dump(all_scraped_data, f, indent=2)
            print(f"\nScraped data saved to {output_file}")
            
            # Output JSON data to console for GitHub Actions
            print("\n=== SCRAPED_DATA_JSON_START ===")
            print(json.dumps(all_scraped_data, indent=2))
            print("=== SCRAPED_DATA_JSON_END ===")
            
            print(f"\n🎉 SCRAPING COMPLETE!")
            print(f"📊 Processed {len(file_numbers)} file numbers")
            print(f"✅ Successful: {successful_files}")
            print(f"❌ Failed: {len(file_numbers) - successful_files}")
            print(f"🏢 Total businesses found: {total_businesses}")
            print(f"📄 Output format: JSON")
        else:
            print("\n❌ No data was scraped from any file numbers")
            sys.exit(1)
        
    except Exception as e:
        print(f"\n💥 Error in scraping process: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
