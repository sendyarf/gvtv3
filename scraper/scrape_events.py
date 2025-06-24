import json
import logging
import re
import hashlib
from datetime import datetime, timedelta
import pytz
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
from tenacity import retry, stop_after_attempt, wait_fixed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import requests
import os
import time

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_team_name(name):
    # Hapus (W) atau simbol lain untuk pembersihan
    name = re.sub(r'\(W\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'[^\w\s]', '', name).strip().lower()
    return name

def generate_match_id(team1, team2):
    return f"{clean_team_name(team1).replace(' ', '')}-{clean_team_name(team2).replace(' ', '')}"

def match_name(name1, name2, threshold=40):
    score = fuzz.ratio(clean_team_name(name1), clean_team_name(name2))
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

def convert_to_wib(time_str, date_str, source_tz):
    try:
        wib_tz = pytz.timezone('Asia/Jakarta')
        source_dt = source_tz.localize(datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M'))
        wib_dt = source_dt.astimezone(wib_tz)
        logging.debug(f"Konversi: {source_dt} ({source_tz.zone}) -> {wib_dt} (WIB)")
        return wib_dt.strftime('%Y-%m-%d'), wib_dt.strftime('%H:%M')
    except ValueError as e:
        logging.error(f"Gagal mengonversi waktu: {time_str}, date: {date_str}, tz: {source_tz.zone}, error: {e}")
        return date_str, time_str

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def scrape_with_selenium(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'body'))
        )
        time.sleep(2)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        if not soup.select('body'):
            logging.error(f"Halaman kosong atau gagal dimuat: {url}")
            raise ValueError("Halaman tidak memuat konten yang valid")
        return soup
    except (TimeoutException, WebDriverException) as e:
        logging.error(f"Gagal memuat {url}: {e}")
        raise
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
    current_date = datetime.now().date()
    current_year = current_date.year
    current_month = current_date.month
    end_date = current_date + timedelta(days=days)
    #utc1_tz = pytz.timezone('Europe/London')
    
    try:
        soup = scrape_with_selenium(url)
    except Exception as e:
        soup = None
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {e}")
    
    if not soup and cache_file:
        cached_content = load_cache(cache_file)
        if cached_content:
            soup = BeautifulSoup(cached_content, 'html.parser')
            logging.info(f"Menggunakan cache untuk {url}")
    
    if not soup:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    if cache_file:
        save_cache(url, str(soup), cache_file)
    
    match_elements = soup.select('.event__match--scheduled, .event__match')
    if not match_elements:
        logging.warning(f"Tidak ada elemen pertandingan ditemukan untuk {league_name}, mencoba selektor alternatif")
        match_elements = soup.select('.sport__event, .event__row')
    
    if not match_elements:
        logging.warning(f"Tidak ada elemen pertandingan ditemukan untuk {league_name} dengan selektor apa pun")
        return matches
    
    for match_elem in match_elements:
        time_elem = match_elem.select_one('.event__time, .event__time div, .time')
        if not time_elem:
            logging.warning("Tidak ada elemen waktu")
            continue
        time_text = time_elem.text.strip().split('<')[0].strip()
        
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
                home_team_elem = match_elem.select_one('.event__homeParticipant .event__participant--home, .event__homeParticipant span, .homeTeam')
                away_team_elem = match_elem.select_one('.event__awayParticipant .event__participant--away, .event__awayParticipant span, .awayTeam')
                home_team = home_team_elem.text.strip() if home_team_elem else ''
                away_team = away_team_elem.text.strip() if away_team_elem else ''
                
                home_logo_elem = match_elem.select_one('.event__homeParticipant img, .event__homeParticipant img.wcl-logo_EkYgo, .event__homeParticipant img.wcl-name_3y6f5, .teamLogo')
                away_logo_elem = match_elem.select_one('.event__awayParticipant img, .event__awayParticipant img.wcl-logo_EkYgo, .event__awayParticipant img.wcl-name_3y6f5, .teamLogo')
                home_logo = home_logo_elem['src'] if home_logo_elem and 'src' in home_logo_elem.attrs else ''
                away_logo = away_logo_elem['src'] if away_logo_elem and 'src' in away_logo_elem.attrs else ''
                
                if not home_team or not away_team:
                    logging.warning(f"Tim tidak lengkap: Home={home_team}, Away={away_team}")
                    continue
                
                match_date_str = match_date.strftime('%Y-%m-%d')
                wib_date, wib_time = convert_to_wib(time_str, match_date_str, utc1_tz)
                
                match_id = generate_match_id(home_team, away_team)
                matches[match_id] = {
                    'id': match_id,
                    'league': league_name,
                    'team1': {'name': home_team, 'logo': home_logo},
                    'team2': {'name': away_team, 'logo': away_logo},
                    'kickoff_date': wib_date,
                    'kickoff_time': wib_time,
                    'match_date': wib_date,
                    'match_time': calculate_match_time(wib_time),
                    'duration': '3.5',
                    'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                    'servers': [],
                    'is_womens': False  # Default: bukan jadwal perempuan
                }
                logging.info(f"Pertandingan: {league_name} - {home_team} vs {away_team} pada {wib_date} {wib_time} WIB")
        except Exception as e:
            logging.error(f"Error mem-parsing waktu atau elemen untuk {time_text}: {e}")
            continue
    
    logging.info(f"Total pertandingan untuk {league_name}: {len(matches)}")
    return matches

def scrape_sportsonline_servers(url, matches, dict_file='french_dict.json'):
    utc1_tz = pytz.timezone('Europe/London')
    french_dict = load_french_dict(dict_file)
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = response.text.split('\n')
        logging.debug(f"Isi Sportsonline prog.txt (10 baris pertama): {lines[:10]}")
    except Exception as e:
        logging.error(f"Gagal mengambil Sportsonline {url}: {e}")
        return matches
    
    current_date = datetime.now().date()
    last_update_match = re.search(r'LAST UPDATE: (\d{2})-(\d{2})-(\d{2})', '\n'.join(lines))
    if last_update_match:
        day, month, year = map(int, last_update_match.groups())
        year = 2000 + year
        update_date = datetime(year, month, day).date()
    else:
        update_date = current_date
        logging.warning("Tidak dapat mendeteksi LAST UPDATE, menggunakan tanggal saat ini")
    
    day_mapping = {
        'MONDAY': update_date - timedelta(days=1) if update_date.weekday() == 1 else update_date + timedelta(days=(0 - update_date.weekday()) % 7),
        'TUESDAY': update_date if update_date.weekday() == 1 else update_date + timedelta(days=(1 - update_date.weekday()) % 7),
        'WEDNESDAY': update_date + timedelta(days=(2 - update_date.weekday()) % 7),
        'THURSDAY': update_date + timedelta(days=(3 - update_date.weekday()) % 7),
        'FRIDAY': update_date + timedelta(days=(4 - update_date.weekday()) % 7),
        'SATURDAY': update_date + timedelta(days=(5 - update_date.weekday()) % 7),
        'SUNDAY': update_date + timedelta(days=(6 - update_date.weekday()) % 7),
    }
    current_day = None
    
    for line in lines:
        line = line.strip()
        if not line:
            logging.debug("Baris kosong di Sportsonline, dilewati")
            continue
        
        if line.upper() in day_mapping:
            current_day = day_mapping[line.upper()]
            logging.debug(f"Deteksi hari: {line} -> {current_day}")
            continue
        
        # Regex untuk menangkap (W) opsional
        match = re.match(r'(\d{2}:\d{2})\s+(.+?)\s+x\s+(.+?)(?:\s*\((W)\))?\s+\|\s+(https://sportzonline\.si/channels/[^\s]+)', line, re.IGNORECASE)
        if not match:
            logging.debug(f"Baris Sportsonline tidak cocok dengan regex: {line}")
            continue
        
        time_str, home_team, away_team, is_womens, server_url = match.groups()
        is_womens = bool(is_womens)  # True jika ada (W), False jika tidak
        logging.debug(f"Parsed Sportsonline: Time={time_str}, Home={home_team}, Away={away_team}, Womens={is_womens}, URL={server_url}")
        
        try:
            if not current_day:
                logging.warning(f"Tidak ada hari yang ditentukan untuk baris: {line}")
                continue
            
            # Terjemahkan nama tim menggunakan french_dict.json
            home_team_translated = french_dict['teams'].get(home_team.strip(), home_team.strip())
            away_team_translated = french_dict['teams'].get(away_team.strip(), away_team.strip())
            logging.debug(f"Terjemahan Sportsonline: Home={home_team} -> {home_team_translated}, Away={away_team} -> {away_team_translated}")
            
            match_date_str = current_day.strftime('%Y-%m-%d')
            wib_date, wib_time = convert_to_wib(time_str, match_date_str, utc1_tz)
            
            home_team_clean = clean_team_name(home_team_translated)
            away_team_clean = clean_team_name(away_team_translated)
            
            # Pencocokan berdasarkan nama tim dan (opsional) waktu
            best_match = None
            best_score = -1
            for match_id, match in matches.items():
                # Cek kecocokan nama tim
                home_match = match_name(home_team_clean, match['team1']['name'], threshold=40)
                away_match = match_name(away_team_clean, match['team2']['name'], threshold=40)
                if home_match and away_match:
                    score = fuzz.ratio(home_team_clean, clean_team_name(match['team1']['name'])) + \
                            fuzz.ratio(away_team_clean, clean_team_name(match['team2']['name']))
                    # Tambah poin jika waktu cocok (opsional)
                    if wib_time == match['kickoff_time']:
                        score += 50  # Bonus untuk waktu yang sama
                    # Cek kecocokan is_womens
                    if is_womens == match.get('is_womens', False):
                        score += 20  # Bonus untuk kecocokan jenis kelamin
                    if score > best_score:
                        best_match = match_id
                        best_score = score
                    logging.debug(f"Pencocokan: {home_team_translated} vs {match['team1']['name']} & {away_team_translated} vs {match['team2']['name']} -> Skor: {score}")
            
            if best_match:
                # Extract channel number from URL (e.g., hd4 from hd4.php)
                channel = server_url.split('/')[-1].replace('.php', '')
                # Count existing mobile servers for this match
                mobile_count = len([s for s in matches[best_match]["servers"] if s["label"].startswith("Mobile-")])
                # Create server entry with listsportsembed URL
                matches[best_match]['servers'].append({
                    'url': f'https://listsportsembed.blogspot.com/p/{channel}.html',
                    'label': f'Mobile-{mobile_count + 1}'
                })
                matches[best_match]['is_womens'] = is_womens  # Update is_womens status
                logging.info(f"Added Sportsonline server: {home_team_translated} vs {away_team_translated} (Womens={is_womens}), URL: Mobile-{mobile_count + 1}")
            else:
                logging.debug(f"Tidak ada pertandingan yang cocok untuk {home_team_translated} vs {away_team_translated} (Womens={is_womens})")
        
        except ValueError as e:
            logging.error(f"Error memproses baris Sportsonline {line}: {e}")
            continue
    
    return matches

def scrape_rereyano_servers(url, matches, days=5, cache_file='rereyano_cache.html', dict_file='french_dict.json'):
    utc2_tz = pytz.timezone('Europe/Paris')
    current_date = datetime.now().date()
    end_date = current_date + timedelta(days=days)
    french_dict = load_french_dict(dict_file)
    
    try:
        soup = scrape_with_selenium(url)
    except Exception as e:
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {e}")
        soup = None
    
    if not soup and cache_file:
        cached_content = load_cache(cache_file)
        if cached_content:
            soup = BeautifulSoup(cached_content, 'html.parser')
            logging.info(f"Menggunakan cache untuk {url}")
    
    if not soup:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    if cache_file:
        save_cache(url, str(soup), cache_file)
    
    textarea = soup.select_one('textarea, div.schedule, pre, p, span')
    if not textarea:
        logging.warning("Tidak ada elemen teks jadwal di Rereyano")
        return matches
    
    text = textarea.text.strip()
    logging.debug(f"Data Rereyano (200 karakter pertama): {text[:200]}...")
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            logging.debug("Baris kosong Rereyano, dilewati")
            continue
        logging.debug(f"Memproses baris Rereyano: {line}")
        
        match = re.match(r'(\d{2}-\d{2}-\d{4})\s+\((\d{2}:\d{2})\)\s+([^:]+?)\s*:\s*([^(\n]+?)\s*[-vs]\s*([^(\n]+?)(?:\s*\((.*?)\))?', line, re.IGNORECASE)
        if match:
            date_str, time_str, league_name, home_team, away_team, channels_str = match.groups()
            
            league_name_translated = french_dict['leagues'].get(league_name.strip(), league_name.strip())
            home_team_translated = french_dict['teams'].get(home_team.strip(), home_team.strip())
            away_team_translated = french_dict['teams'].get(away_team.strip(), away_team.strip())
            
            logging.debug(f"Terjemahan: Liga={league_name} -> {league_name_translated}, Home={home_team} -> {home_team_translated}, Away={away_team} -> {away_team_translated}")
            
            if len(home_team_translated.strip()) < 2 or len(away_team_translated.strip()) < 2:
                logging.warning(f"Nama tim tidak valid: Home={home_team_translated}, Away={away_team_translated}")
                continue
            
            try:
                match_date = datetime.strptime(date_str, '%d-%m-%Y')
                match_date_str = match_date.strftime('%Y-%m-%d')
                wib_date, wib_time = convert_to_wib(time_str, match_date_str, utc2_tz)
                
                if current_date <= match_date.date() <= end_date:
                    match_id = generate_match_id(home_team_translated, away_team_translated)
                    for existing_id, match in matches.items():
                        if match_league(league_name_translated, match['league']) and \
                           match['kickoff_date'] == wib_date and \
                           match['kickoff_time'] == wib_time and \
                           ((match_name(match['team1']['name'], home_team_translated) and \
                             match_name(match['team2']['name'], away_team_translated)) or \
                            (match_name(match['team1']['name'], away_team_translated) and \
                             match_name(match['team2']['name'], home_team_translated))):
                            channels = re.findall(r'\((CH[^)]+)\)', channels_str) if channels_str else []
                            for channel in channels:
                                url, label = convert_rereyano_channel(channel)
                                if url and label:
                                    matches[existing_id]['servers'].append({
                                        'url': url,
                                        'label': label
                                    })
                                    logging.info(f"Server Rereyano: {home_team_translated} vs {away_team_translated}, URL={url}, Label={label}")
                            break
            except ValueError as e:
                logging.error(f"Error mem-parsing {line}: {e}")
                continue
        logging.debug(f"Baris Rereyano tidak cocok: {line}")
    
    return matches

def merge_manual_schedule(manual_file, auto_schedule):
    try:
        with open(manual_file, 'r', encoding='utf-8') as f:
            manual_schedule = json.load(f)
    except FileNotFoundError:
        logging.warning(f"File manual {manual_file} tidak ditemukan")
        return auto_schedule
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding {manual_file}: {e}")
        return auto_schedule
    
    merged_schedule = auto_schedule.copy()
    
    for manual in manual_schedule:
        match_id = manual.get('id', '')
        if not match_id:
            logging.warning(f"Manual tanpa ID: {manual}")
            continue
        
        try:
            datetime.strptime(manual['kickoff_time'], '%H:%M')
        except (KeyError, ValueError):
            logging.warning(f"Format waktu manual tidak valid: {manual.get('kickoff_time', 'tidak ada')}")
            continue
        
        if match_id in merged_schedule:
            existing_servers = merged_schedule[match_id].get('servers', [])
            manual_servers = manual.get('servers', [])
            merged_servers = existing_servers + [
                server for server in manual_servers
                if server not in existing_servers
            ]
            merged_schedule[match_id]['servers'] = merged_servers
            merged_schedule[match_id]['is_womens'] = manual.get('is_womens', False)
            logging.info(f"Server manual untuk {match_id}: {manual_servers}")
        else:
            merged_schedule[match_id] = manual
            logging.info(f"Pertandingan manual baru: {match_id}")
    
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
    dict_file = "french_dict.json"
    output_file = "event.json"
    
    matches = {}
    
    for url, name in flashscore_urls:
        league_matches = scrape_flashscore_schedule(url, days=5, league_name=name, cache_file=f'flashscore_cache_{name.lower().replace(" ", "_")}.html')
        matches.update(league_matches)
        logging.debug(f"Tim Flashscore ({name}): {list(league_matches.keys())}")
    
    matches = scrape_sportsonline_servers(sportsonline_url, matches, dict_file=dict_file)
    matches = scrape_rereyano_servers(rereyano_url, matches, dict_file=dict_file)
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
            logging.info(f"Jadwal updated: {output_file}")
        except Exception as e:
            logging.error(f"Gagal menyimpan {output_file}: {e}")
    else:
        logging.info(f"Tidak ada perubahan, {output_file} tidak diupdate")
    
    logging.info(f"Total pertandingan: {len(output)}")
    return output

if __name__ == "__main__":
    main()