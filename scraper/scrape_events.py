import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import os
import hashlib

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
            return '2025-01-01'

def get_json_hash(data):
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

def read_existing_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"No existing event.json found at {file_path}, starting fresh")
        return []

def scrape_events():
    url = 'https://govoet720.blogspot.com/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'no-cache'
    }
    output_path = os.path.join(os.getcwd(), 'event.json')

    try:
        print(f"Fetching {url}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        print(f"Response status code: {response.status_code}")

        # Save raw HTML for debugging
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("Saved raw HTML to debug.html")

        soup = BeautifulSoup(response.text, 'html.parser')
        event_list = soup.select_one('.event-list')
        if not event_list:
            print("No .event-list found in HTML. Check debug.html for content.")
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

                league = event_card.select_one('.event-header .event-name').get_text(strip=True) if event_card.select_one('.event-header .event-name') else 'Unknown League'

                team_home = event_card.select_one('.team__home .team__name').get_text(strip=True) if event_card.select_one('.team__home .team__name') else 'Unknown Home'
                team_home_logo = event_card.select_one('.team__home .team__logo')['src'] if event_card.select_one('.team__home .team__logo') else 'https://via.placeholder.com/50.png?text=Team'
                team_away = event_card.select_one('.team__away .team__name').get_text(strip=True) if event_card.select_one('.team__away .team__name') else 'Unknown Away'
                team_away_logo = event_card.select_one('.team__away .team__logo')['src'] if event_card.select_one('.team__away .team__logo') else 'https://via.placeholder.com/50.png?text=Team'

                match_date = event_card.select_one('.match-datetime')['data-target-date'] if event_card.select_one('.match-datetime') else '2025-01-01'
                match_time = event_card.select_one('.match-hour')['data-target-time'] if event_card.select_one('.match-hour') else '00:00'
                match_date = convert_date_format(match_date)

                button_group = event_card.select_one('.button-group')
                servers = []
                if button_group:
                    for button in button_group.select('.stream-button'):
                        onclick = button.get('onclick', '')
                        url_match = re.search(r"changeStream\('([^']+)'\)", onclick)
                        url = url_match.group(1) if url_match else None
                        label = button.get_text(strip=True)
                        if url and label:
                            servers.append({'url': url, 'label': label})

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
                    print(f"Processed event {index}: {team_home} vs {team_away} ({cleaned_event_id})")

            except Exception as e:
                print(f"Error processing event {index}: {str(e)}")

        if not events:
            print("No valid events found after processing. Check HTML structure or server availability.")

        # Ensure event.json is written even if empty to confirm script execution
        existing_events = read_existing_json(output_path)
        existing_hash = get_json_hash(existing_events)
        new_hash = get_json_hash(events)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(events)} events to {output_path}")

        return events, existing_hash != new_hash

    except requests.RequestException as e:
        print(f"Failed to fetch {url}: {str(e)}")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text if 'response' in locals() else 'No response')
        # Write empty event.json to indicate failure
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        print(f"Saved empty event.json to {output_path} due to fetch failure")
        return [], False

if __name__ == '__main__':
    events, changed = scrape_events()
    if not events:
        print("No events scraped. Check debug.html for raw HTML.")
    else:
        print(f"Scraped {len(events)} events successfully.")