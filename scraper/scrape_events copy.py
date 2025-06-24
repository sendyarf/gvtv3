import os
import sys
import json
import re
import hashlib
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent

def clean_event_id(event_id):
    return re.sub(r'[^a-z0-9]', '', event_id.lower())

def convert_date_format(date_str):
    try:
        return datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')
    except ValueError:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            print(f"Invalid date format: {date_str}")
            return datetime.now().strftime('%Y-%m-%d')

def get_json_hash(data):
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

def read_existing_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"No existing event.json found at {file_path}, starting fresh: {str(e)}")
        return []

def setup_driver():
    """Set up and return a Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-software-rasterizer')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-browser-side-navigation')
    chrome_options.add_argument('--disable-features=VizDisplayCompositor')
    chrome_options.add_argument('--disable-software-rasterizer')
    chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def scrape_events():
    url = 'https://govoet720.blogspot.com/'
    project_root = get_project_root()
    output_path = project_root / 'event.json'
    debug_path = project_root / 'debug.html'
    
    print(f"Project root: {project_root}")
    print(f"Output path: {output_path}")
    
    driver = None
    try:
        print(f"Initializing Chrome WebDriver...")
        driver = setup_driver()
        print(f"Fetching {url}")
        driver.get(url)

        # Wait for .event-list to appear
        print("Waiting for event list to load...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.event-list'))
        )
        
        print("Page loaded successfully")
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Save rendered HTML for debugging
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"Saved rendered HTML to {debug_path}")

        event_list = soup.select_one('.event-list')
        if not event_list:
            print("No .event-list found in rendered HTML. Check debug.html for content.")
            return [], False

        event_cards = event_list.select('.event-card')
        print(f"Found {len(event_cards)} event(s)")

        events = []
        for index, event_card in enumerate(event_cards, 1):
            try:
                event_id = event_card.get('id', '')
                if not event_id:
                    print(f"Event {index}: Missing ID, skipping")
                    continue
                
                cleaned_event_id = clean_event_id(event_id)
                print(f"Processing event {index}: {cleaned_event_id}")

                # Extract event details
                league = event_card.select_one('.event-header .event-name')
                league = league.get_text(strip=True) if league else 'Unknown League'

                team_home = event_card.select_one('.team__home .team__name')
                team_home = team_home.get_text(strip=True) if team_home else 'Unknown Home'
                
                team_home_logo = event_card.select_one('.team__home .team__logo')
                team_home_logo = team_home_logo['src'] if team_home_logo and 'src' in team_home_logo.attrs else 'https://via.placeholder.com/50.png?text=Team'
                
                team_away = event_card.select_one('.team__away .team__name')
                team_away = team_away.get_text(strip=True) if team_away else 'Unknown Away'
                
                team_away_logo = event_card.select_one('.team__away .team__logo')
                team_away_logo = team_away_logo['src'] if team_away_logo and 'src' in team_away_logo.attrs else 'https://via.placeholder.com/50.png?text=Team'

                # Extract date and time
                match_date = '2025-01-01'
                match_time = '00:00'
                
                datetime_elem = event_card.select_one('.match-datetime')
                if datetime_elem and 'data-target-date' in datetime_elem.attrs:
                    match_date = convert_date_format(datetime_elem['data-target-date'])
                
                time_elem = event_card.select_one('.match-hour')
                if time_elem and 'data-target-time' in time_elem.attrs:
                    match_time = time_elem['data-target-time']

                # Extract server URLs
                button_group = event_card.select_one('.button-group')
                servers = []
                if button_group:
                    for button in button_group.select('.stream-button'):
                        try:
                            onclick = button.get('onclick', '')
                            print(f"Processing button with onclick: {onclick}")
                            
                            # Handle different URL formats in onclick
                            url = None
                            patterns = [
                                r"changeStream\(['\"]([^'\"]+)['\"]\)",  # changeStream('URL')
                                r"changeStream\(['\"]([^'\"]+)['\"],"   # changeStream('URL', ...)
                            ]
                            
                            for pattern in patterns:
                                match = re.search(pattern, onclick)
                                if match:
                                    url = match.group(1)
                                    break
                            
                            if not url:
                                print(f"  Could not extract URL from: {onclick}")
                                continue
                                
                            # Clean up the URL
                            url = url.strip("'\"")
                            
                            # Get the label (button text)
                            label = button.get_text(strip=True) or f"Server {len(servers) + 1}"
                            label = re.sub(r'\s+', ' ', label).strip()
                            
                            if url and label:
                                servers.append({
                                    'url': url,
                                    'label': label
                                })
                                print(f"  Added server: {label} - {url}")
                            else:
                                print(f"  Skipping invalid server - URL: {url}, Label: {label}")
                                
                        except Exception as e:
                            print(f"Error processing server button: {e}")
                            import traceback
                            traceback.print_exc()
                    
                # Debug: Print all found servers
                print(f"\nFound {len(servers)} servers for {team_home} vs {team_away}:")
                for i, server in enumerate(servers, 1):
                    print(f"  {i}. {server['label']}: {server['url']}")
                print()

                if team_home != 'Unknown Home' and team_away != 'Unknown Away' and servers:
                    event = {
                        'id': cleaned_event_id,
                        'league': league,
                        'team1': {'name': team_home, 'logo': team_home_logo},
                        'team2': {'name': team_away, 'logo': team_away_logo},
                        'kickoff_date': match_date,
                        'kickoff_time': match_time,
                        'match_date': match_date,
                        'match_time': match_time,
                        'duration': '3.1',
                        'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                        'servers': servers
                    }
                    events.append(event)
                    print(f"✓ Added event: {team_home} vs {team_away} ({cleaned_event_id})")
                else:
                    print(f"✗ Skipping event {index}: Missing required data")

            except Exception as e:
                print(f"Error processing event {index}: {str(e)}")
                import traceback
                traceback.print_exc()

        if not events:
            print("No valid events found after processing. Check HTML structure or server availability.")
            return [], False

        # Read existing events if file exists
        existing_events = []
        if output_path.exists():
            existing_events = read_existing_json(output_path)
        
        # Only update if there are changes
        existing_hash = get_json_hash(existing_events) if existing_events else ""
        new_hash = get_json_hash(events)
        has_changes = existing_hash != new_hash

        if has_changes:
            # Create parent directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write new events
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=2, ensure_ascii=False)
            print(f"✅ Saved {len(events)} events to {output_path}")
        else:
            print("ℹ️ No changes detected in events")

        return events, has_changes

    except Exception as e:
        print(f"❌ Failed to scrape {url}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Save error to debug file
        error_info = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        if driver:
            error_info += f"\n\nPage source length: {len(driver.page_source) if hasattr(driver, 'page_source') else 0}"
        
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(error_info)
        
        # Initialize empty event.json if it doesn't exist
        if not output_path.exists():
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=2)
            print(f"Initialized empty {output_path}")
            
        return [], False
        
    finally:
        if driver:
            try:
                driver.quit()
                print("Browser closed")
            except Exception as e:
                print(f"Error closing browser: {e}")

if __name__ == '__main__':
    print("=== Starting Scraper ===")
    events, changed = scrape_events()
    if not events:
        print("❌ No events were scraped. Check debug.html for more information.")
        sys.exit(1)
    print(f"✅ Successfully processed {len(events)} events")
    print(f"Changes detected: {'Yes' if changed else 'No'}")
    print("=== Scraper Finished ===")