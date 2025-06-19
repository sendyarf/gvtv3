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
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        try:
            return datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            return '2025-01-01'

def get_json_hash(data):
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

def read_existing_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def scrape_events():
    url = 'https://govoet720.blogspot.com/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive'
    }
    output_path = os.path.join(os.getcwd(), 'event.json')

    try:
        print(f"Fetching {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Log HTML untuk debugging
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Saved raw HTML to debug.html")

        event_cards = soup.select('.event-card')
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
                        'duration': '2.5',
                        'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                        'servers': servers
                    }
                    events.append(event)
                    print(f"Processed event {index}: {team_home} vs {team_away} ({cleaned_event_id})")

            except Exception as e:
                print(f"Error processing event {index}: {str(e)}")

        existing_events = read_existing_json(output_path)
        existing_hash = get_json_hash(existing_events)
        new_hash = get_json_hash(events)

        if existing_hash != new_hash:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(events)} events to {output_path} (data changed)")
            return events, True
        else:
            print(f"No changes detected, skipping save to {output_path}")
            return events, False

    except requests.RequestException as e:
        print(f"Failed to fetch {url}: {str(e)}")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text if 'response' in locals() else 'No response')
        return [], False

if __name__ == '__main__':
    events, changed = scrape_events()
    if not events:
        print("No events scraped. Check debug.html for raw HTML.")