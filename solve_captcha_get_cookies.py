import requests
import json
import os
import sys
from seleniumbase import SB
import time
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, List, Any, Tuple

# Get API key from environment variable (GitHub secrets)
API_KEY = os.getenv('SOLVECAPTCHA_API_KEY')
if not API_KEY:
    print("ERROR: SOLVECAPTCHA_API_KEY environment variable not set")
    sys.exit(1)

SOLVE_URL = "https://api.solvecaptcha.com/in.php"
RESULT_URL = "https://api.solvecaptcha.com/res.php"

def create_optimized_session():
    """Create an optimized requests session with connection pooling and retry logic"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504, 429],
        allowed_methods=["HEAD", "GET", "POST"]
    )
    
    # Configure HTTP adapter with connection pooling
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set optimized timeouts
    session.timeout = (5, 30)  # connection timeout, read timeout
    
    return session

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
    """Create a new optimized requests session with the provided cookies"""
    session = create_optimized_session()
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
    if response is None:
        return True
        
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

def is_connection_refused(exception):
    """Check if the exception indicates connection refused (blocking)"""
    error_msg = str(exception).lower()
    blocking_indicators = [
        'connection refused',
        'connection reset',
        'connection aborted',
        'network is unreachable',
        'timeout',
        'connection error',
        'remote end closed connection'
    ]
    return any(indicator in error_msg for indicator in blocking_indicators)

def scrape_single_file_number(file_number: str, session: requests.Session) -> Tuple[str, Dict[str, Any]]:
    """Scrape data for a single file number"""
    print(f"🔍 Processing file number: {file_number}")
    
    scraped_data = []
    
    try:
        # Search for businesses
        print("Searching for businesses...")
        search_results = search_businesses_with_session(file_number, session)
        
        # Extract business IDs from the results
        if 'rows' in search_results:
            # The rows is a dictionary where keys are the business IDs
            for business_id, business_data in search_results['rows'].items():
                print(f"  📋 Fetching details for business ID: {business_id}")
                
                # Get detailed information for each business
                details = get_business_details_with_session(business_id, session)
                
                # Add the scraped data to our results
                scraped_data.append({
                    'file_number': file_number,
                    'business_id': business_id,
                    'search_data': business_data,
                    'details': details
                })
                
                print(f"  ✅ Successfully scraped business ID: {business_id}")
        else:
            print("  ⚠️ No results found or unexpected response format")
            
        return file_number, {
            'success': True,
            'businesses_found': len(scraped_data),
            'data': scraped_data,
            'error': None
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"  ❌ Error processing {file_number}: {error_msg}")
        
        # Check if this is a blocking/connection issue
        is_blocked = is_connection_refused(e)
        
        return file_number, {
            'success': False,
            'businesses_found': 0,
            'data': [],
            'error': error_msg,
            'blocked': is_blocked
        }

def search_businesses_with_session(file_number: str, session: requests.Session):
    """Search businesses using existing session"""
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

    response = session.post(url, headers=headers, json=data)
    
    if is_request_blocked(response):
        raise Exception(f"Search request blocked (status {response.status_code})")
    
    response.raise_for_status()
    return response.json()

def get_business_details_with_session(business_id: str, session: requests.Session):
    """Get business details using existing session"""
    url = f"https://bizfileonline.sos.ca.gov/api/FilingDetail/business/{business_id}/false"
    
    response = session.get(url)
    
    if is_request_blocked(response):
        raise Exception(f"Details request blocked (status {response.status_code})")
    
    response.raise_for_status()
    return response.json()

def scrape_batch_of_file_numbers(file_numbers: List[str], cookies: Dict[str, str]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Scrape a batch of file numbers (up to 5) simultaneously
    Returns: (successful_results, remaining_file_numbers)
    """
    print(f"\n🚀 Starting batch processing of {len(file_numbers)} file numbers")
    print(f"File numbers: {file_numbers}")
    
    # Create session with cookies
    session = create_session_with_cookies(cookies)
    
    successful_results = {}
    remaining_files = []
    blocked = False
    
    try:
        # Process up to 5 file numbers simultaneously
        batch_size = min(5, len(file_numbers))
        current_batch = file_numbers[:batch_size]
        remaining_files = file_numbers[batch_size:]
        
        print(f"Processing batch of {len(current_batch)} files simultaneously...")
        
        # Use ThreadPoolExecutor for concurrent processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(scrape_single_file_number, file_num, session): file_num 
                for file_num in current_batch
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_file):
                file_number = future_to_file[future]
                try:
                    file_num, result = future.result()
                    successful_results[file_num] = result
                    
                    # Check if this file was blocked
                    if result.get('blocked', False):
                        print(f"🚫 Blocking detected for file {file_num}")
                        blocked = True
                        # Add unprocessed files from current batch to remaining
                        for other_future in future_to_file:
                            if not other_future.done():
                                other_file = future_to_file[other_future]
                                if other_file not in successful_results:
                                    remaining_files.insert(0, other_file)
                                other_future.cancel()
                        break
                        
                except Exception as e:
                    print(f"❌ Unexpected error processing {file_number}: {e}")
                    # If it's a connection issue, treat as blocking
                    if is_connection_refused(e):
                        blocked = True
                        remaining_files.insert(0, file_number)
                        break
                    else:
                        # Add failed result
                        successful_results[file_number] = {
                            'success': False,
                            'businesses_found': 0,
                            'data': [],
                            'error': str(e),
                            'blocked': False
                        }
    
    except Exception as e:
        print(f"💥 Critical error during batch processing: {e}")
        # If session-level error, likely blocking - return all files as remaining
        if is_connection_refused(e):
            remaining_files = file_numbers
            successful_results = {}
        
    finally:
        session.close()
    
    if blocked:
        print(f"🚫 Blocking detected! Processed {len(successful_results)} files, {len(remaining_files)} remaining")
    else:
        print(f"✅ Batch completed successfully! Processed {len(successful_results)} files")
    
    return successful_results, remaining_files

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

def save_partial_results(results: Dict[str, Any], batch_number: int = 1):
    """Save partial results to file"""
    if not results:
        return None
        
    timestamp = time.strftime('%Y%m%d_%H%M%S', time.gmtime())
    filename = f'scraped_data_partial_batch_{batch_number}_{timestamp}.json'
    
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"💾 Partial results saved to: {filename}")
    return filename

def trigger_new_workflow(remaining_files: List[str], batch_number: int):
    """Trigger a new workflow with remaining file numbers"""
    if not remaining_files:
        return
        
    print(f"🔄 Triggering new workflow for {len(remaining_files)} remaining files...")
    
    # Set environment variable for the next workflow
    remaining_files_json = json.dumps(remaining_files)
    
    # Create a file with remaining file numbers for GitHub Actions to pick up
    with open('remaining_files.json', 'w') as f:
        json.dump({
            'file_numbers': remaining_files,
            'batch_number': batch_number + 1,
            'trigger_time': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        }, f, indent=2)
    
    print(f"📝 Remaining files saved to: remaining_files.json")
    print(f"File numbers: {remaining_files}")

def main():
    """Main function with batch processing and blocking detection"""
    try:
        # Get file numbers from environment variable
        file_numbers_input = os.getenv('FILE_NUMBERS', '202250419109')
        batch_number = int(os.getenv('BATCH_NUMBER', '1'))
        
        file_numbers = parse_file_numbers(file_numbers_input)
        
        print(f"🚀 Starting California business scraper (Batch #{batch_number})")
        print(f"File numbers to process: {file_numbers}")
        print(f"Total files: {len(file_numbers)}")
        
        # Get initial cookies
        print("\n🍪 Getting cookies and solving captcha...")
        cookies = get_cookies()
        print("✅ Cookies obtained successfully")
        
        # Process files in batches of 5
        all_results = {}
        current_batch_num = 1
        remaining_files = file_numbers
        
        while remaining_files:
            print(f"\n📦 Processing batch #{current_batch_num} of up to 5 files...")
            
            # Process current batch
            batch_results, remaining_files = scrape_batch_of_file_numbers(remaining_files, cookies)
            
            # Merge results
            all_results.update(batch_results)
            
            # If we have remaining files, it means we got blocked
            if remaining_files:
                print(f"\n🚫 BLOCKING DETECTED!")
                print(f"✅ Successfully processed: {len(all_results)} files")
                print(f"⏳ Remaining files: {len(remaining_files)}")
                
                # Save partial results
                if all_results:
                    final_data = {
                        'metadata': {
                            'total_files_requested': len(file_numbers),
                            'files_processed': len(all_results),
                            'files_remaining': len(remaining_files),
                            'batch_number': batch_number,
                            'blocked': True,
                            'scrape_timestamp': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                        },
                        'results': all_results
                    }
                    
                    save_partial_results(final_data, batch_number)
                
                # Trigger new workflow for remaining files
                trigger_new_workflow(remaining_files, batch_number)
                
                # Exit with partial success
                print(f"\n🏁 Partial processing complete!")
                print(f"📊 Files processed in this batch: {len(all_results)}")
                print(f"🔄 New workflow will be triggered for remaining {len(remaining_files)} files")
                
                return
            
            current_batch_num += 1
            
            # Add small delay between batches if processing multiple batches
            if remaining_files:
                time.sleep(2)
        
        # All files processed successfully
        total_businesses = sum(
            result.get('businesses_found', 0) 
            for result in all_results.values()
        )
        
        successful_files = sum(
            1 for result in all_results.values() 
            if result.get('success', False)
        )
        
        if total_businesses > 0 or successful_files > 0:
            # Create final results
            final_data = {
                'metadata': {
                    'total_files_requested': len(file_numbers),
                    'files_processed': len(all_results),
                    'files_remaining': 0,
                    'batch_number': batch_number,
                    'blocked': False,
                    'scrape_timestamp': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                },
                'results': all_results
            }
            
            # Create filename
            if len(file_numbers) == 1:
                output_file = f'scraped_data_{file_numbers[0]}.json'
            else:
                output_file = f'scraped_data_batch_{batch_number}_{len(file_numbers)}_files.json'
            
            # Save as JSON
            with open(output_file, 'w') as f:
                json.dump(final_data, f, indent=2)
            print(f"\n💾 Scraped data saved to {output_file}")
            
            # Output JSON data to console for GitHub Actions
            print("\n=== SCRAPED_DATA_JSON_START ===")
            print(json.dumps(final_data, indent=2))
            print("=== SCRAPED_DATA_JSON_END ===")
            
            print(f"\n🎉 SCRAPING COMPLETE!")
            print(f"📊 Total files processed: {len(file_numbers)}")
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
