import json
import logging
import re
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
import pytz
from tenacity import retry, stop_after_attempt, wait_fixed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import requests
import os

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_team_name(name):
    return re.sub(r'[^\w\s]', '', name).strip()

def generate_match_id(team1, team2):
    return f"{clean_team_name(team1).lower().replace(' ', '')}-{clean_team_name(team2).lower().replace(' ', '')}"

def match_name(name1, name2, threshold=60):
    score = fuzz.ratio(clean_team_name(name1).lower(), clean_team_name(name2).lower())
    logging.debug(f"Pencocokan fuzzy: {name1} vs {name2} -> Skor: {score}")
    return score >= threshold

def match_league(league1, league2, threshold=60):
    score = fuzz.ratio(league1.lower(), league2.lower())
    logging.debug(f"Pencocokan liga: {league1} vs {league2} -> Skor: {score}")
    return score >= threshold

def calculate_match_time(time_str):
    try:
        kickoff = datetime.strptime(time_str, '%H:%M')
        match_time = kickoff - timedelta(minutes=10)
        return match_time.strftime('%H:%M')
    except ValueError as e:
        logging.error(f"Error menghitung match_time: {time_str}, error: {e}")
        return time_str

def convert_utc1_to_wib(time_str, match_date):
    try:
        utc1_tz = pytz.timezone('Europe/London')  # UTC+1 (misalnya, BST tanpa DST pada Juni)
        wib_tz = pytz.timezone('Asia/Jakarta')    # UTC+7
        # Parse waktu dengan tanggal untuk konteks
        dt = datetime.strptime(f"{match_date} {time_str}", '%Y-%m-%d %H:%M')
        utc1_time = utc1_tz.localize(dt)
        wib_time = utc1_time.astimezone(wib_tz)
        logging.debug(f"Waktu UTC+1: {utc1_time}, Waktu WIB: {wib_time}")
        return wib_time.strftime('%H:%M')
    except ValueError as e:
        logging.error(f"Gagal mengonversi waktu UTC+1 ke WIB: {time_str}, error: {e}")
        return time_str

def convert_cet_to_wib(time_str):
    try:
        cet_tz = pytz.timezone('Europe/Paris')    # CEST (UTC+2 pada Juni)
        wib_tz = pytz.timezone('Asia/Jakarta')    # UTC+7
        cet_time = cet_tz.localize(datetime.strptime(time_str, '%H:%M:%S'))
        wib_time = cet_time.astimezone(wib_tz)
        logging.debug(f"Waktu CEST: {cet_time}, Offset: {cet_time.utcoffset().total_seconds()/3600} jam, Waktu WIB: {wib_time}")
        return wib_time
    except ValueError as e:
        logging.error(f"Gagal mengonversi waktu CEST ke WIB: {time_str}, error: {e}")
        return datetime.now(pytz.timezone('Asia/Jakarta'))

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def scrape_with_selenium(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, seperti Gecko) Chrome/137.0.0.0 Safari/537.36')
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        html = driver.page_source
        return BeautifulSoup(html, 'html.parser')
    finally:
        driver.quit()

def load_cache(cache_file):
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logging.warning(f"Cache {cache_file} tidak ditemukan")
        return None

def save_cache(url, content, cache_file):
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"Cache disimpan ke {cache_file}")
    except Exception as e:
        logging.error(f"Gagal menyimpan cache ke {cache_file}: {e}")

def load_french_dict(dict_file):
    try:
        with open(dict_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"File kamus {dict_file} tidak ditemukan, menggunakan default")
        return {"leagues": {}, "teams": {}}

def convert_rereyano_channel(channel):
    channel = channel.strip().lower()
    if channel.startswith('ch') and channel.endswith('fr'):
        return f"https://envivo.govoet.my.id/{channel[2:-2]}", f"CH-FR"
    elif channel.startswith('ch') and channel.endswith('es'):
        return f"https://envivo.govoet.my.id/{channel[2:-2]}", f"CH-ES"
    logging.warning(f"Channel Rereyano tidak dikenali: {channel}")
    return None, None

def scrape_flashscore_schedule(url, days=5, league_name='Unknown League', cache_file='flashscore_cache.html'):
    matches = {}
    current_date = datetime.now(pytz.timezone('Asia/Jakarta')).date()
    current_year = current_date.year
    current_month = current_date.month
    end_date = current_date + timedelta(days=days)
    
    try:
        soup = scrape_with_selenium(url)
    except Exception:
        soup = None
        logging.warning(f"Gagal mengambil {url}, mencoba cache")
    
    if not soup and cache_file:
        soup = load_cache(cache_file)
        if soup:
            soup = BeautifulSoup(soup, 'html.parser')
            logging.info(f"Menggunakan cache untuk {url}")
    
    if not soup:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    if cache_file:
        save_cache(url, str(soup), cache_file)
    
    match_elements = soup.select('.event__match--scheduled')
    if not match_elements:
        logging.warning(f"Tidak ada elemen pertandingan ditemukan untuk {league_name}")
        return matches
    
    for match_elem in match_elements:
        time_elem = match_elem.select_one('.event__time')
        if not time_elem:
            logging.warning("Tidak ada elemen waktu")
            continue
        time_text = time_elem.text.strip().split('<')[0]
        
        try:
            time_match = re.match(r'(\d{2})\.(\d{2})\.\s+(\d{1,2}:\d{2})', time_text)
            if not time_match:
                logging.error(f"Format waktu tidak cocok: {time_text}")
                continue
            
            day, month, time_str = time_match.groups()
            day = int(day)
            month = int(month)
            
            if month > current_month or (month == current_month and day >= current_date.day):
                year = current_year
            else:
                year = current_year + 1
            
            match_date = datetime(year, month, day).date()
            
            if current_date <= match_date <= end_date:
                home_team_elem = match_elem.select_one('.event__homeParticipant .wcl-name_3y6f5')
                away_team_elem = match_elem.select_one('.event__awayParticipant .wcl-name_3y6f5')
                home_team = home_team_elem.text.strip() if home_team_elem else ''
                away_team = away_team_elem.text.strip() if away_team_elem else ''
                home_logo = match_elem.select_one('.event__homeParticipant img.wcl-logo_EkYgo, .event__homeParticipant img.wcl-name_3y6f5')['src'] if match_elem.select_one('.event__homeParticipant img') else ''
                away_logo = match_elem.select_one('.event__awayParticipant img.wcl-logo_EkYgo, .event__awayParticipant img.wcl-name_3y6f5')['src'] if match_elem.select_one('.event__awayParticipant img') else ''
                
                if not home_team or not away_team:
                    logging.warning(f"Tim tidak lengkap: Home={home_team}, Away={away_team}")
                    continue
                
                # Konversi waktu dari UTC+1 ke WIB
                wib_time = convert_utc1_to_wib(time_str, match_date.strftime('%Y-%m-%d'))
                
                match_id = generate_match_id(home_team, away_team)
                matches[match_id] = {
                    'id': match_id,
                    'league': league_name,
                    'team1': {'name': home_team, 'logo': home_logo},
                    'team2': {'name': away_team, 'logo': away_logo},
                    'kickoff_date': match_date.strftime('%Y-%m-%d'),
                    'kickoff_time': wib_time,
                    'match_date': match_date.strftime('%Y-%m-%d'),
                    'match_time': calculate_match_time(wib_time),
                    'duration': '3.5',
                    'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                    'servers': []
                }
                logging.info(f"Pertandingan: {league_name} - {home_team} vs {away_team} pada {match_date.strftime('%Y-%m-%d')} {wib_time} WIB")
        except (ValueError, AttributeError) as e:
            logging.error(f"Error mem-parsing waktu atau elemen untuk {time_text}: {e}")
            continue
    
    logging.info(f"Total pertandingan untuk {league_name}: {len(matches)}")
    return matches

def scrape_sportsonline_servers(url, matches):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = response.text.splitlines()
    except Exception as e:
        logging.error(f"Gagal mengambil Sportsonline {url}: {e}")
        return matches
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        match = re.match(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+(.+?)\s*-\s*(.+?)(?:\s*\((.+?)\))?', line)
        if match:
            date_str, time_str, home_team, away_team, channel = match.groups()
            try:
                match_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                home_team_clean = clean_team_name(home_team)
                away_team_clean = clean_team_name(away_team)
                match_id = generate_match_id(home_team, away_team)
                
                for existing_match_id, existing_match in matches.items():
                    if match_date.strftime('%Y-%m-%d') == existing_match['kickoff_date'] and \
                       match_name(home_team_clean, existing_match['team1']['name']) and \
                       match_name(away_team_clean, existing_match['team2']['name']):
                        if channel:
                            url = f"https://sportsonline.ci/stream/{channel.lower()}"
                            matches[existing_match_id]['servers'].append({
                                'url': url,
                                'label': f"CH-SO-{channel}"
                            })
                            logging.info(f"Server Sportsonline ditambahkan: {home_team} vs {away_team}, URL: {url}")
                        break
            except ValueError as e:
                logging.error(f"Error mem-parsing Sportsonline {line}: {e}")
                continue
    
    return matches

def scrape_rereyano_servers(url, matches, days=5, cache_file='rereyano_cache.html', dict_file='french_dict.json'):
    current_date = datetime.now(pytz.timezone('Asia/Jakarta')).date()
    end_date = current_date + timedelta(days=days)
    server_count = {}
    french_dict = load_french_dict(dict_file)
    
    try:
        soup = scrape_with_selenium(url)
    except Exception as e:
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {e}")
        soup = None
    
    if not soup and cache_file:
        soup = load_cache(cache_file)
        if soup:
            soup = BeautifulSoup(soup, 'html.parser')
            logging.info(f"Menggunakan cache untuk {url}")
    
    if not soup:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    if cache_file:
        save_cache(url, str(soup), cache_file)
    
    textarea = soup.select_one('textarea') or soup.select_one('div, pre, p, span')
    if not textarea:
        logging.warning("Tidak ada elemen teks jadwal di Rereyano")
        logging.debug(f"Isi halaman Rereyano: {soup.prettify()[:500]}...")
        return matches
    
    text = textarea.text.strip()
    logging.debug(f"Data Rereyano (200 karakter pertama): {text[:200]}...")
    lines = text.split('\n')
    logging.debug(f"Total baris Rereyano: {len(lines)}")
    
    for line in lines:
        line = line.strip()
        if not line:
            logging.debug("Baris kosong Rereyano, dilewati")
            continue
        logging.debug(f"Memproses baris Rereyano: {line}")
        
        match = re.match(r'(\d{2}-\d{2}-\d{4})\s+\((\d{2}:\d{2})\)\s+([^:]+?)\s*:\s*([^(\n]+?)\s*[\-vs]\s*([^(\n]+?)(?:\s*\((.*?)\))?', line, re.IGNORECASE)
        if match:
            date_str, time_str, league_name, home_team, away_team, channels_str = match.groups()
            
            league_name_translated = french_dict['leagues'].get(league_name.strip(), league_name.strip())
            home_team_translated = french_dict['teams'].get(home_team.strip(), home_team.strip())
            away_team_translated = french_dict['teams'].get(away_team.strip(), away_team.strip())
            
            logging.debug(f"Terjemahan Rereyano: Liga={league_name} -> {league_name_translated}, Home={home_team} -> {home_team_translated}, Away={away_team} -> {away_team_translated}")
            
            if len(home_team_translated.strip()) < 2 or len(away_team_translated.strip()) < 2:
                logging.warning(f"Nama tim tidak valid: Home={home_team_translated}, Away={away_team_translated}, Baris={line}")
                continue
            
            home_team_clean = clean_team_name(home_team_translated)
            away_team_clean = clean_team_name(away_team_translated)
            match_id = generate_match_id(home_team_translated, away_team_translated)
            
            try:
                match_date = datetime.strptime(date_str, '%d-%m-%Y').date()
                wib_time = convert_cet_to_wib(f"{time_str}:00")
                time_wib = wib_time.strftime('%H:%M')
                logging.debug(f"Konversi waktu Rereyano: {time_str} CEST -> {time_wib} WIB")
                
                if current_date <= match_date <= end_date:
                    found = False
                    for existing_match_id, match in matches.items():
                        if match_league(league_name_translated, match['league']):
                            home_match = match_name(match['team1']['name'], home_team_translated)
                            away_match = match_name(match['team2']['name'], away_team_translated)
                            reverse_match = match_name(match['team1']['name'], away_team_translated) and match_name(match['team2']['name'], home_team_translated)
                            if (home_match and away_match) or reverse_match:
                                channels = re.findall(r'\((CH[^)]+)\)', channels_str) if channels_str else []
                                for channel in channels:
                                    url, label = convert_rereyano_channel(channel)
                                    if url and label:
                                        server_count[existing_match_id] = server_count.get(existing_match_id, 0) + 1
                                        matches[existing_match_id]['servers'].append({
                                            'url': url,
                                            'label': label
                                        })
                                        logging.info(f"Server Rereyano ditambahkan: {home_team_translated} vs {away_team_translated}, URL: {url}, Label: {label}")
                                found = True
                                break
                        else:
                            logging.debug(f"Liga tidak cocok: {league_name_translated} vs {match['league']}")
                    
                    if not found:
                        matches[match_id] = {
                            'id': match_id,
                            'league': league_name_translated,
                            'team1': {'name': home_team_translated, 'logo': ''},
                            'team2': {'name': away_team_translated, 'logo': ''},
                            'kickoff_date': match_date.strftime('%Y-%m-%d'),
                            'kickoff_time': time_wib,
                            'match_date': match_date.strftime('%Y-%m-%d'),
                            'match_time': calculate_match_time(time_wib),
                            'duration': '3.5',
                            'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                            'servers': []
                        }
                        channels = re.findall(r'\((CH[^)]+)\)', channels_str) if channels_str else []
                        for channel in channels:
                            url, label = convert_rereyano_channel(channel)
                            if url and label:
                                server_count[match_id] = server_count.get(match_id, 0) + 1
                                matches[match_id]['servers'].append({
                                    'url': url,
                                    'label': label
                                })
                                logging.info(f"Pertandingan baru dan server Rereyano ditambahkan: {home_team_translated} vs {away_team_translated}, URL: {url}, Label: {label}")
            except ValueError as e:
                logging.error(f"Error mem-parsing untuk {line}: {e}")
                continue
        else:
            logging.debug(f"Baris Rereyano tidak cocok dengan regex: {line}")
    
    return matches

def merge_manual_schedule(manual_file, auto_schedule):
    try:
        with open(manual_file, 'r', encoding='utf-8') as f:
            manual_schedule = json.load(f)
    except FileNotFoundError:
        logging.warning(f"File {manual_file} tidak ditemukan, tidak ada data manual")
        return auto_schedule
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding {manual_file}: {e}")
        return auto_schedule
    
    merged_schedule = auto_schedule.copy()
    
    for manual_match in manual_schedule:
        match_id = manual_match.get('id', '')
        if not match_id:
            logging.warning(f"Pertandingan manual tanpa ID: {manual_match}")
            continue
        
        try:
            datetime.strptime(manual_match['kickoff_time'], '%H:%M')
        except (KeyError, ValueError):
            logging.warning(f"Format waktu manual tidak valid: {manual_match.get('kickoff_time', 'tidak ada')}")
            continue
        
        if match_id in merged_schedule:
            existing_servers = merged_schedule[match_id].get('servers', [])
            manual_servers = manual_match.get('servers', [])
            merged_servers = existing_servers + [
                server for server in manual_servers
                if server not in existing_servers
            ]
            merged_schedule[match_id]['servers'] = merged_servers
            logging.info(f"Server manual ditambahkan untuk {match_id}: {manual_servers}")
        else:
            merged_schedule[match_id] = manual_match
            logging.info(f"Pertandingan manual baru ditambahkan: {match_id}")
    
    return merged_schedule

def compute_json_hash(data):
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

def main():
    flashscore_urls = [
        ("https://www.flashscore.com/football/world/fifa-club-world-cup/fixtures/", "FIFA Club World Cup"),
        ("https://www.flashscore.com/football/england/premier-league/fixtures/", "Premier League"),
        ("https://www.flashscore.com/football/france/ligue-1/fixtures/", "Ligue 1"),
        ("https://www.flashscore.com/football/germany/bundesliga/fixtures/", "Bundesliga")
    ]
    sportsonline_url = "https://sportsonline.ci/prog.txt"
    rereyano_url = "https://rereyano.ru/"
    manual_schedule_file = "manual_schedule.json"
    output_file = "event.json"
    
    matches = {}
    
    try:
        for url, league_name in flashscore_urls:
            matches.update(scrape_flashscore_schedule(url, days=5, league_name=league_name))
            team_list = [f"{m['team1']['name']} vs {m['team2']['name']}" for m in matches.values()]
            logging.debug(f"Tim Flashscore ({league_name}): {team_list}")
    except Exception as e:
        logging.error(f"Error saat scraping Flashscore: {e}")
    
    try:
        matches = scrape_sportsonline_servers(sportsonline_url, matches)
    except Exception as e:
        logging.error(f"Error saat scraping Sportsonline: {e}")
    
    try:
        matches = scrape_rereyano_servers(rereyano_url, matches)
    except Exception as e:
        logging.error(f"Error saat scraping Rereyano: {e}")
    
    matches = merge_manual_schedule(manual_schedule_file, matches)
    
    output = list(matches.values())
    
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
        old_hash = compute_json_hash(old_data)
    except (FileNotFoundError, json.JSONDecodeError):
        old_hash = ""
        old_data = []
    
    new_hash = compute_json_hash(output)
    
    if new_hash != old_hash:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            logging.info(f"Jadwal diperbarui dan disimpan ke {output_file}")
        except Exception as e:
            logging.error(f"Gagal menyimpan {output_file}: {e}")
    else:
        logging.info(f"Tidak ada perubahan pada jadwal, {output_file} tidak diperbarui")
    
    logging.info(f"Total pertandingan: {len(output)}")
    return output

if __name__ == "__main__":
    main()