import re
import logging
import os
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from tenacity import retry, stop_after_attempt, wait_fixed
from fuzzywuzzy import fuzz
import pytz
import requests
import unicodedata

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def load_french_dict(dict_file='french_dict.json'):
    try:
        with open(dict_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"File kamus {dict_file} tidak ditemukan")
        return {"leagues": {}, "teams": {}}
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing {dict_file}: {e}")
        return {"leagues": {}, "teams": {}}

def initialize_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except Exception as e:
        logging.error(f"Gagal menginisialisasi ChromeDriver: {e}")
        raise

def save_cache(url, content, cache_file):
    with open(cache_file, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f"Cache disimpan untuk {url}: {cache_file}")

def load_cache(cache_file):
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def convert_cet_to_wib(time_str):
    try:
        cet_tz = pytz.timezone('Europe/Paris')
        wib_tz = pytz.timezone('Asia/Jakarta')
        cet_time = cet_tz.localize(datetime.strptime(time_str, '%H:%M:%S'))
        wib_time = cet_time.astimezone(wib_tz)
        return wib_time
    except ValueError as e:
        logging.error(f"Gagal mengonversi waktu: {time_str}, error: {e}")
        return datetime.now(pytz.timezone('Asia/Jakarta'))

def generate_match_id(home_team, away_team):
    return f"{clean_team_name(home_team)}-{clean_team_name(away_team)}".lower().replace(' ', '')

def clean_team_name(name):
    name = unicodedata.normalize('NFKD', name.strip()).encode('ASCII', 'ignore').decode('ASCII')
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+(FC|RJ|SC|AC|CF|SE|SA)$', '', name, flags=re.IGNORECASE)
    return name.strip()

def match_name(name1, name2, threshold=60):
    name1_clean = clean_team_name(name1).lower()
    name2_clean = clean_team_name(name2).lower()
    score = max(fuzz.ratio(name1_clean, name2_clean), fuzz.partial_ratio(name1_clean, name2_clean))
    logging.debug(f"Pencocokan fuzzy: {name1} vs {name2} -> Skor: {score}")
    return score >= threshold

def match_league(league1, league2, threshold=80):
    league1_clean = clean_team_name(league1).lower()
    league2_clean = clean_team_name(league2).lower()
    score = fuzz.ratio(league1_clean, league2_clean)
    logging.debug(f"Pencocokan liga: {league1} vs {league2} -> Skor: {score}")
    return score >= threshold

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def scrape_with_selenium(url):
    driver = initialize_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup
    except Exception as e:
        logging.error(f"Gagal mengakses {url}: {e}")
        raise
    finally:
        driver.quit()

def calculate_match_time(kickoff_time):
    try:
        kickoff = datetime.strptime(kickoff_time, '%H:%M')
        match_time = kickoff - timedelta(minutes=10)
        return match_time.strftime('%H:%M')
    except ValueError:
        logging.error(f"Gagal menghitung match_time untuk {kickoff_time}")
        return kickoff_time

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
                
                match_id = generate_match_id(home_team, away_team)
                matches[match_id] = {
                    'id': match_id,
                    'league': league_name,
                    'team1': {'name': home_team, 'logo': home_logo},
                    'team2': {'name': away_team, 'logo': away_logo},
                    'kickoff_date': match_date.strftime('%Y-%m-%d'),
                    'kickoff_time': time_str,  # Gunakan waktu langsung dari Flashscore (WIB)
                    'match_date': match_date.strftime('%Y-%m-%d'),
                    'match_time': calculate_match_time(time_str),
                    'duration': '3.5',
                    'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                    'servers': []
                }
                logging.info(f"Pertandingan: {league_name} - {home_team} vs {away_team} pada {match_date.strftime('%Y-%m-%d')} {time_str}")
        except (ValueError, AttributeError) as e:
            logging.error(f"Error mem-parsing waktu atau elemen untuk {time_text}: {e}")
            continue
    
    logging.info(f"Total pertandingan untuk {league_name}: {len(matches)}")
    return matches
def convert_sportsonline_url(url):
    try:
        channel_match = re.search(r'channels/(?:hd|pt|bra)/([^.]+)\.php|([^/]+)\.php$', url)
        if channel_match:
            channel = channel_match.group(1) or channel_match.group(2)
            return f"https://listsportsembed.blogspot.com/p/{channel}.html"
        logging.warning(f"URL Sportsonline tidak cocok dengan pola yang diharapkan: {url}")
        return None
    except AttributeError:
        logging.warning(f"Gagal mengonversi URL Sportsonline: {url}")
        return None

def scrape_sportsonline_servers(url, matches, days=5, cache_file='sportsonline_cache.html'):
    current_date = datetime.now(pytz.timezone('Asia/Jakarta')).date()
    end_date = current_date + timedelta(days=days)
    current_day = None
    server_count = {}
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        text = response.text
        logging.debug(f"Panjang data Sportsonline: {len(text)}")
    except Exception as e:
        text = None
        logging.warning(f"Gagal mengambil {url}: {e}, mencoba cache")
    
    if not text and cache_file:
        text = load_cache(cache_file)
        logging.info(f"Menggunakan cache untuk {url}")
    
    if not text:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    if cache_file:
        save_cache(url, text, cache_file)
    
    lines = text.split('\n')
    logging.debug(f"Total baris Sportsonline: {len(lines)}")
    
    for line in lines:
        line = line.strip()
        if not line:
            logging.debug("Baris kosong, dilewati")
            continue
        
        if line.upper() in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']:
            current_day = line.upper()
            logging.debug(f"Header hari ditemukan: {current_day}")
            continue
        
        logging.debug(f"Memproses baris Sportsonline: {line}")
        match = re.match(r'^(\d{2}:\d{2})\s+([^|;]+?)\s+(?:x|vs)\s+([^|;]+?)\s*[|;]\s*(https?://[^\s]+)', line, re.IGNORECASE)
        if match:
            time_str, home_team, away_team, channel = match.groups()
            home_team_clean = clean_team_name(home_team)
            away_team_clean = clean_team_name(away_team)
            
            converted_url = convert_sportsonline_url(channel)
            if not converted_url:
                logging.debug(f"URL tidak valid: {channel}")
                continue
            
            if not current_day:
                current_day = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%A').upper()
                logging.debug(f"Tidak ada header hari, menggunakan default: {current_day}")
            
            try:
                match_date = get_date_from_day(current_day, current_date, end_date)
                if match_date and current_date <= match_date <= end_date:
                    for match_id, match in matches.items():
                        home_match = match_name(match['team1']['name'], home_team)
                        away_match = match_name(match['team2']['name'], away_team)
                        reverse_match = match_name(match['team1']['name'], away_team) and match_name(match['team2']['name'], home_team)
                        match_date_flashscore = datetime.strptime(match['kickoff_date'], '%Y-%m-%d').date()
                        date_diff = abs((match_date - match_date_flashscore).days)
                        if ((home_match and away_match) or reverse_match) and date_diff <= 1:
                            server_count[match_id] = server_count.get(match_id, 0) + 1
                            matches[match_id]['servers'].append({
                                'url': converted_url,
                                'label': f"mobile-{server_count[match_id]}"
                            })
                            logging.info(f"Server Sportsonline ditambahkan: {home_team} vs {away_team}, URL: {converted_url}, Label: mobile-{server_count[match_id]}")
                        else:
                            logging.debug(f"Tim atau tanggal tidak cocok: {match['team1']['name']} vs {match['team2']['name']} ({match['kickoff_date']}) dengan {home_team} vs {away_team} ({match_date.strftime('%Y-%m-%d')})")
                else:
                    logging.debug(f"Tanggal di luar rentang: {match_date}")
            except ValueError as e:
                logging.error(f"Error mem-parsing tanggal untuk {line}: {e}")
                continue
        else:
            logging.debug(f"Baris Sportsonline tidak cocok dengan regex: {line}")
    
    return matches

def convert_rereyano_channel(channel):
    try:
        channel_match = re.search(r'CH(\d+)([a-zA-Z]+)?', channel, re.IGNORECASE)
        if channel_match:
            number = channel_match.group(1)
            suffix = channel_match.group(2) or ''
            url = f"https://envivo.govoet.my.id/{number}"
            label = f"CH-{suffix.upper()}" if suffix else f"CH-{number}"
            return url, label
        logging.warning(f"Gagal mengonversi channel Rereyano: {channel}")
        return None, None
    except AttributeError:
        logging.warning(f"Gagal mengonversi channel Rereyano: {channel}")
        return None, None

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
            
            # Validasi nama tim
            if len(home_team_translated.strip()) < 2 or len(away_team_translated.strip()) < 2:
                logging.warning(f"Nama tim tidak valid: Home={home_team_translated}, Away={away_team_translated}, Baris={line}")
                continue
            
            home_team_clean = clean_team_name(home_team_translated)
            away_team_clean = clean_team_name(away_team_translated)
            match_id = generate_match_id(home_team_translated, away_team_translated)
            
            try:
                match_date = datetime.strptime(date_str, '%d-%m-%Y').date()
                # Konversi waktu dari CEST ke WIB
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
                            'kickoff_time': time_wib,  # Waktu dalam WIB
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
    """
    Menggabungkan jadwal manual dari manual_file dengan jadwal otomatis.
    - Menambahkan pertandingan baru dari manual.
    - Menambahkan server manual ke pertandingan yang sudah ada berdasarkan id.
    """
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
        
        if match_id in merged_schedule:
            # Pertandingan sudah ada, tambahkan server manual
            existing_servers = merged_schedule[match_id].get('servers', [])
            manual_servers = manual_match.get('servers', [])
            merged_servers = existing_servers + [
                server for server in manual_servers
                if server not in existing_servers  # Hindari duplikasi
            ]
            merged_schedule[match_id]['servers'] = merged_servers
            logging.info(f"Server manual ditambahkan untuk {match_id}: {manual_servers}")
        else:
            # Pertandingan baru, tambahkan ke jadwal
            merged_schedule[match_id] = manual_match
            logging.info(f"Pertandingan manual baru ditambahkan: {match_id}")
    
    return merged_schedule    

def get_date_from_day(day, current_date, end_date):
    days_map = {
        'MONDAY': 0, 'TUESDAY': 1, 'WEDNESDAY': 2, 'THURSDAY': 3,
        'FRIDAY': 4, 'SATURDAY': 5, 'SUNDAY': 6
    }
    try:
        target_day = days_map[day]
        current_day = current_date.weekday()
        delta = (target_day - current_day) % 7
        if delta == 0 and current_date > end_date:
            delta = 7
        match_date = current_date + timedelta(days=delta)
        logging.debug(f"Konversi hari {day} -> Tanggal: {match_date.strftime('%Y-%m-%d')}")
        return match_date if current_date <= match_date <= end_date else None
    except KeyError:
        logging.error(f"Hari tidak valid: {day}")
        return None

def main():
    flashscore_urls = [
        ("https://www.flashscore.com/football/world/fifa-club-world-cup/fixtures/", "FIFA Club World Cup")
    ]
    sportsonline_url = "https://sportsonline.ci/prog.txt"
    rereyano_url = "https://rereyano.ru/"
    manual_schedule_file = "manual_schedule.json"  # File untuk jadwal/server manual
    
    matches = {}
    
    try:
        for url, league_name in flashscore_urls:
            matches.update(scrape_flashscore_schedule(url, days=5, league_name=league_name))
            team_list = [f"{m['team1']['name']} vs {m['team2']['name']}" for m in matches.values()]
            logging.debug(f"Tim Flashscore: {team_list}")
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
    
    # Gabungkan dengan jadwal manual
    matches = merge_manual_schedule(manual_schedule_file, matches)
    
    output = list(matches.values())
    
    try:
        with open('schedule.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        logging.info("Jadwal disimpan ke schedule.json")
    except Exception as e:
        logging.error(f"Gagal menyimpan schedule.json: {e}")
    
    logging.info(f"Total pertandingan: {len(output)}")
    return output

if __name__ == "__main__":
    output = main()
    print(f"Total pertandingan: {len(output)}")