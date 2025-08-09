
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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import requests
import os
import time
import random
import subprocess
import tempfile
import shutil

# Konfigurasi logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_team_name(name):
    """Membersihkan nama tim dari karakter khusus dan spasi berlebih."""
    name = re.sub(r'\(W\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'[^\w\s]', '', name).strip().lower()
    return name

def generate_match_id(team1, team2):
    """Menghasilkan ID unik untuk pertandingan berdasarkan nama tim."""
    return f"{clean_team_name(team1).replace(' ', '')}-{clean_team_name(team2).replace(' ', '')}"

def match_name(name1, name2, threshold=70):
    """Mencocokkan dua nama tim menggunakan fuzzy matching."""
    score = fuzz.ratio(clean_team_name(name1), clean_team_name(name2))
    logging.debug(f"Pencocokan tim: {name1} vs {name2} -> Skor: {score}")
    return score >= threshold

def match_name_sportsonline(name1, name2, threshold=30):
    """Mencocokkan nama tim untuk SportsOnline dengan threshold lebih rendah."""
    score = fuzz.ratio(clean_team_name(name1), clean_team_name(name2))
    logging.debug(f"Pencocokan tim (SportsOnline): {name1} vs {name2} -> Skor: {score}")
    return score >= threshold

def match_league(league1, league2, threshold=30):
    """Mencocokkan nama liga menggunakan fuzzy matching."""
    score = fuzz.ratio(league1.lower(), league2.lower())
    logging.debug(f"Pencocokan liga: {league1} vs {league2} -> Skor: {score}")
    return score >= threshold

def find_team_fallback(team_name, matches, threshold=60):
    """Mencari nama tim terbaik jika tidak ada di kamus."""
    best_match = team_name
    best_score = 0
    for match_id, match in matches.items():
        for team_key in ['team1', 'team2']:
            team = match[team_key]['name']
            score = fuzz.ratio(clean_team_name(team_name), clean_team_name(team))
            current_threshold = 40 if len(team_name) < 7 else threshold
            if team_name.lower() in team.lower() or team.lower() in team_name.lower():
                score += 20
            if score > best_score and score >= current_threshold:
                best_match = team
                best_score = score
    if best_match != team_name:
        logging.debug(f"Fallback mapping: {team_name} -> {best_match} (score={best_score})")
    else:
        logging.debug(f"Tidak ada fallback untuk tim: {team_name}")
    return best_match

def calculate_match_time(time_str):
    """Menghitung waktu mulai pertandingan (10 menit sebelum kickoff)."""
    try:
        kickoff = datetime.strptime(time_str, '%H:%M')
        match_time = kickoff - timedelta(minutes=10)
        return match_time.strftime('%H:%M')
    except ValueError as e:
        logging.error(f"Error menghitung match_time: {time_str}, error: {e}")
        return time_str

def convert_to_wib(time_str, date_str, source_tz):
    """Mengonversi waktu dari zona waktu sumber ke WIB."""
    try:
        wib_tz = pytz.timezone('Asia/Jakarta')
        source_dt = source_tz.localize(datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M'))
        wib_dt = source_dt.astimezone(wib_tz)
        logging.debug(f"Konversi waktu: {source_dt} ({source_tz.zone}) -> {wib_dt} (WIB)")
        return wib_dt.strftime('%Y-%m-%d'), wib_dt.strftime('%H:%M')
    except ValueError as e:
        logging.error(f"Gagal mengonversi waktu: {time_str}, date: {date_str}, tz: {source_tz.zone}, error: {e}")
        return date_str, time_str

def time_within_window(time1, time2, window_minutes=120):
    """Memeriksa apakah dua waktu berada dalam jendela waktu tertentu."""
    try:
        t1 = datetime.strptime(time1, '%H:%M')
        t2 = datetime.strptime(time2, '%H:%M')
        delta = abs((t1 - t2).total_seconds() / 60)
        return delta <= window_minutes
    except ValueError:
        return False

@retry(stop=stop_after_attempt(5), wait=wait_fixed(15))
def scrape_with_selenium(url):
    """Mengambil konten halaman menggunakan Selenium."""
    user_data_dir = None
    try:
        # Log system state before starting ChromeDriver
        logging.debug("Checking running Chrome/ChromeDriver processes before starting:")
        try:
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            logging.debug(f"Processes:\n{result.stdout}")
            chrome_processes = subprocess.run(['ps', 'aux', '|', 'grep', '-E', 'chromedriver|google-chrome'], capture_output=True, text=True, shell=True)
            logging.debug(f"Chrome/ChromeDriver processes:\n{chrome_processes.stdout}")
            tmp_dirs = subprocess.run(['find', '/tmp', '-maxdepth', '1', '-type', 'd', '|', 'grep', '-E', 'tmp|.com.google.Chrome'], capture_output=True, text=True, shell=True)
            logging.debug(f"Temporary directories in /tmp:\n{tmp_dirs.stdout}")
        except Exception as e:
            logging.warning(f"Failed to check system state: {e}")

        # Create a unique temporary directory for user-data-dir
        user_data_dir = tempfile.mkdtemp(prefix='chrome_user_data_')
        logging.debug(f"Using temporary user-data-dir: {user_data_dir}")

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-extensions')
        options.add_argument(f'--user-data-dir={user_data_dir}')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        # Use a random port to avoid conflicts
        port = random.randint(1024, 65535)
        service = Service('/usr/bin/chromedriver', port=port)
        logging.debug(f"Starting ChromeDriver on port {port} with user-data-dir: {user_data_dir}")

        driver = webdriver.Chrome(service=service, options=options)
        logging.debug(f"ChromeDriver started successfully for URL: {url}")
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
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
            logging.error(f"Gagal memuat {url}: {type(e).__name__}: {str(e)}")
            raise
        finally:
            try:
                driver.quit()
                logging.debug(f"ChromeDriver closed successfully")
            except Exception as e:
                logging.warning(f"Gagal menutup driver: {e}")
    except Exception as e:
        logging.error(f"Error in scrape_with_selenium: {type(e).__name__}: {str(e)}")
        # Attempt to clean up any stuck processes
        try:
            subprocess.run(['pkill', '-9', 'chromedriver'], check=False)
            subprocess.run(['pkill', '-9', 'google-chrome'], check=False)
            logging.debug("Attempted to clean up ChromeDriver and Chrome processes")
        except Exception as cleanup_e:
            logging.warning(f"Failed to clean up processes: {cleanup_e}")
        raise
    finally:
        # Clean up the temporary user-data-dir
        if user_data_dir and os.path.exists(user_data_dir):
            try:
                shutil.rmtree(user_data_dir)
                logging.debug(f"Cleaned up temporary user-data-dir: {user_data_dir}")
            except Exception as e:
                logging.warning(f"Failed to clean up user-data-dir {user_data_dir}: {e}")

def load_cache(cache_file):
    """Memuat konten dari file cache."""
    try:
        if os.path.exists(cache_file):
            file_age = datetime.now().timestamp() - os.path.getmtime(cache_file)
            if file_age > 24 * 60 * 60:
                logging.warning(f"Cache {cache_file} terlalu lama ({file_age/3600:.2f} jam), diabaikan")
                return None
            with open(cache_file, 'r', encoding='utf-8') as f:
                content = f.read()
                logging.info(f"Cache loaded successfully from {cache_file}")
                return content
        else:
            logging.warning(f"Cache file {cache_file} does not exist")
            return None
    except Exception as e:
        logging.error(f"Gagal memuat cache {cache_file}: {e}")
        return None

def save_cache(url, content, cache_file):
    """Menyimpan konten ke file cache."""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"Cache disimpan ke {cache_file}")
    except Exception as e:
        logging.error(f"Gagal menyimpan cache ke {cache_file}: {e}")

def load_french_dict(dict_file):
    """Memuat kamus terjemahan dari file JSON."""
    try:
        with open(dict_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"File kamus {dict_file} tidak ditemukan, menggunakan default")
        return {"leagues": {}, "teams": {}}
    except Exception as e:
        logging.error(f"Gagal memuat {dict_file}: {e}")
        return {"leagues": {}, "teams": {}}

def scrape_flashscore_schedule(url, days=5, league_name='Unknown League', cache_file='flashscore_cache.html'):
    """Mengambil jadwal pertandingan dari Flashscore."""
    matches = {}
    current_date = datetime.now().date()
    current_year = current_date.year
    current_month = current_date.month
    end_date = current_date + timedelta(days=days)
    
    try:
        soup = scrape_with_selenium(url)
        logging.debug(f"Successfully scraped {url}")
    except Exception as e:
        soup = None
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {type(e).__name__}: {str(e)}")
    
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
    
    # Selektor untuk menangkap pertandingan
    match_elements = soup.select('.event__match, .sport__event, .event__row, .event__match--scheduled')
    if not match_elements:
        logging.warning(f"Tidak ada elemen pertandingan ditemukan untuk {league_name}")
        return matches
    
    for match_elem in match_elements:
        try:
            # Ekstrak waktu
            time_elem = match_elem.select_one('.event__time, .event__time div, .time, .startTime')
            if not time_elem:
                logging.warning("Tidak ada elemen waktu")
                continue
            time_text = time_elem.text.strip().split('<')[0].strip()
            logging.debug(f"Waktu ditemukan: {time_text}")
            
            # Parsing waktu dengan penanganan error yang lebih baik
            time_match = re.match(r'(\d{2})\.(\d{2})\.\s*(\d{1,2}:\d{2})', time_text)
            if not time_match:
                time_match = re.match(r'(\d{2})\.(\d{2})\.(\d{4})\s*(\d{1,2}:\d{2})', time_text)
            
            if not time_match:
                logging.error(f"Format waktu tidak cocok: {time_text}")
                continue
                
            groups = time_match.groups()
            if len(groups) == 3:
                day, month, time_str = groups
                year = str(current_year) if int(month) >= current_month else str(current_year + 1)
            else:
                day, month, year, time_str = groups
            
            # Konversi ke integer dengan penanganan error
            try:
                day = int(day)
                month = int(month)
                year = int(year)
            except ValueError as e:
                logging.error(f"Gagal mengonversi tanggal: day={day}, month={month}, year={year}, error: {e}")
                continue
            
            # Validasi tanggal
            try:
                match_date = datetime(year, month, day).date()
            except ValueError as e:
                logging.error(f"Tanggal tidak valid: {year}-{month}-{day}, error: {e}")
                continue
            
            # Periksa apakah tanggal berada dalam jendela waktu
            if current_date <= match_date <= end_date:
                # Ekstrak tim
                home_team_elem = match_elem.select_one('.event__homeParticipant, .homeTeam, .event__homeParticipant span')
                away_team_elem = match_elem.select_one('.event__awayParticipant, .awayTeam, .event__awayParticipant span')
                home_team = home_team_elem.text.strip() if home_team_elem else ''
                away_team = away_team_elem.text.strip() if away_team_elem else ''
                
                # Ekstrak logo
                home_logo_elem = match_elem.select_one('.event__homeParticipant img, .teamLogo')
                away_logo_elem = match_elem.select_one('.event__awayParticipant img, .teamLogo')
                home_logo = home_logo_elem['src'] if home_logo_elem and 'src' in home_logo_elem.attrs else ''
                away_logo = away_logo_elem['src'] if away_logo_elem and 'src' in away_logo_elem.attrs else ''
                
                if not home_team or not away_team:
                    logging.warning(f"Tim tidak lengkap: Home={home_team}, Away={away_team}")
                    continue
                
                # Cek apakah pertandingan untuk wanita
                is_womens = 'Women' in home_team or 'Women' in away_team or '(W)' in home_team or '(W)' in away_team
                
                match_date_str = match_date.strftime('%Y-%m-%d')
                original_date = match_date_str
                original_time = time_str
                
                match_id = generate_match_id(home_team, away_team)
                matches[match_id] = {
                    'id': match_id,
                    'league': league_name,
                    'team1': {'name': home_team, 'logo': home_logo},
                    'team2': {'name': away_team, 'logo': away_logo},
                    'kickoff_date': original_date,
                    'kickoff_time': original_time,
                    'match_date': original_date,
                    'match_time': calculate_match_time(original_time),
                    'duration': '3.5',
                    'icon': 'https://via.placeholder.com/30.png?text=Soccer',
                    'servers': [],
                    'is_womens': is_womens
                }
                logging.info(f"Pertandingan: {league_name} - {home_team} vs {away_team} pada {original_date} {original_time}")
            else:
                logging.debug(f"Pertandingan di luar jendela waktu: {match_date} tidak antara {current_date} dan {end_date}")
        except Exception as e:
            logging.error(f"Error mem-parsing elemen pertandingan: {e}")
            continue
    
    logging.info(f"Total pertandingan untuk {league_name}: {len(matches)}")
    logging.debug(f"Isi matches: {json.dumps(matches, indent=2, ensure_ascii=False)}")
    return matches

def convert_rereyano_channel(channel):
    """Mengonversi channel Rereyano ke URL dan label."""
    channel = channel.strip().lower()
    channel_match = re.search(r'(?:ch)?(\d+)([a-z]{0,2})?', channel, re.IGNORECASE)
    if channel_match:
        channel_num = channel_match.group(1)
        lang = channel_match.group(2) or 'fr'
        return f"https://envivo.govoet.my.id/{channel_num}", f"CH-{lang.upper()}"
    logging.warning(f"Format channel Rereyano tidak dikenali: {channel}")
    return None, None

def scrape_rereyano_servers(url, matches, days=5, cache_file='rereyano_cache.html', dict_file='french_dict.json'):
    """Mengambil server dari Rereyano dan mencocokkannya dengan pertandingan."""
    utc2_tz = pytz.timezone('Europe/Paris')
    current_date = datetime.now().date()
    end_date = current_date + timedelta(days=days)
    french_dict = load_french_dict(dict_file)
    
    logging.info(f"Mengambil data dari Rereyano: {url}")
    
    soup = None
    try:
        soup = scrape_with_selenium(url)
        logging.debug(f"Successfully scraped Rereyano: {url}")
        if soup and cache_file:
            save_cache(url, str(soup), cache_file)
    except Exception as e:
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {type(e).__name__}: {str(e)}")
    
    if not soup and cache_file:
        cached_content = load_cache(cache_file)
        if cached_content:
            soup = BeautifulSoup(cached_content, 'html.parser')
            logging.info(f"Menggunakan cache untuk {url}")
    
    if not soup:
        logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
        return matches
    
    textarea = soup.find('textarea')
    if not textarea:
        logging.warning("Tidak menemukan textarea di halaman Rereyano")
        return matches
    
    text = textarea.text.strip()
    lines = [line.strip() for line in text.split('\n') 
             if re.search(r'\d{2}-\d{2}-\d{4}\s+\(\d{2}:\d{2}\)', line)]
    
    if not lines:
        logging.warning("Tidak menemukan jadwal di konten Rereyano")
        return matches
    
    logging.info(f"Ditemukan {len(lines)} baris jadwal di Rereyano")
    
    for line in lines:
        try:
            logging.debug(f"Memproses baris Rereyano: {line}")
            # Pisahkan baris menjadi bagian utama
            match = re.match(
                r'(\d{2}-\d{2}-\d{4})\s+\((\d{2}:\d{2})\)\s+([^:]+)\s*:\s*([^:]+?)\s*-\s*([^()]+)', 
                line
            )
            
            if not match:
                logging.debug(f"Baris Rereyano tidak cocok: {line}")
                continue
                
            date_str, time_str, league_name, home_team, away_team = match.groups()
            # Tangkap hanya channel yang valid
            channel_list = re.findall(r'\((CH\d+[a-zA-Z]{0,2})\)', line, re.IGNORECASE)
            channel_list = [ch.strip() for ch in channel_list if ch.strip()]
            
            logging.debug(f"Hasil ekstrak Rereyano: date={date_str}, time={time_str}, league={league_name}, "
                         f"home={home_team}, away={away_team}, channels={channel_list}")
            
            home_team = home_team.strip()
            away_team = away_team.strip()
            league_name = league_name.strip()
            
            league_name_translated = french_dict['leagues'].get(league_name, league_name)
            home_team_translated = french_dict['teams'].get(home_team)
            if home_team_translated is None:
                home_team_translated = find_team_fallback(home_team, matches)
            else:
                logging.debug(f"Tim ditemukan di french_dict: {home_team} -> {home_team_translated}")
            
            away_team_translated = french_dict['teams'].get(away_team)
            if away_team_translated is None:
                away_team_translated = find_team_fallback(away_team, matches)
            else:
                logging.debug(f"Tim ditemukan di french_dict: {away_team} -> {away_team_translated}")
            
            logging.debug(f"Rereyano setelah terjemahan: home={home_team_translated}, away={away_team_translated}, league={league_name_translated}")
            
            if len(home_team_translated) < 2 or len(away_team_translated) < 2:
                logging.warning(f"Nama tim Rereyano tidak valid: Home={home_team_translated}, Away={away_team_translated}")
                continue
            
            try:
                match_date = datetime.strptime(date_str, '%d-%m-%Y')
                match_date_str = match_date.strftime('%Y-%m-%d')
                wib_date, wib_time = convert_to_wib(time_str, match_date_str, utc2_tz)
                
                if current_date <= match_date.date() <= end_date:
                    match_found = False
                    added_servers = []
                    
                    for existing_id, match in list(matches.items()):
                        try:
                            league_match = match_league(league_name_translated, match['league'], threshold=30)
                            time_match = time_within_window(wib_time, match['kickoff_time'], window_minutes=120)
                            date_match = match_date.date() == datetime.strptime(match['kickoff_date'], '%Y-%m-%d').date()
                            
                            home_match1 = match_name(home_team_translated, match['team1']['name'])
                            away_match1 = match_name(away_team_translated, match['team2']['name'])
                            home_match2 = match_name(home_team_translated, match['team2']['name'])
                            away_match2 = match_name(away_team_translated, match['team1']['name'])
                            
                            if league_match and (time_match or date_match):
                                if (home_match1 and away_match1) or (home_match2 and away_match2):
                                    match_found = True
                                    logging.info(f"Pertandingan Rereyano cocok: {existing_id}, home={home_team_translated}, away={away_team_translated}")
                                    
                                    for channel in channel_list:
                                        url, label = convert_rereyano_channel(channel)
                                        if url and label:
                                            normalized_url = url.lower().rstrip('/')
                                            server_exists = any(
                                                s['url'].lower().rstrip('/') == normalized_url 
                                                for s in match['servers']
                                            )
                                            
                                            if not server_exists and url not in added_servers:
                                                match['servers'].append({
                                                    'url': url,
                                                    'label': label
                                                })
                                                added_servers.append(url)
                                                logging.info(f"Menambahkan server Rereyano: {label} - {url} untuk {existing_id}")
                                            else:
                                                logging.debug(f"Server Rereyano dilewati (sudah ada): {label} - {url}")
                                        else:
                                            logging.warning(f"Channel Rereyano tidak valid: {channel}")
                            
                            if not match_found:
                                logging.debug(f"Pencocokan gagal untuk {existing_id}: league_score={fuzz.ratio(league_name_translated.lower(), match['league'].lower())}, "
                                             f"home_score1={fuzz.ratio(clean_team_name(home_team_translated), clean_team_name(match['team1']['name']))}, "
                                             f"away_score1={fuzz.ratio(clean_team_name(away_team_translated), clean_team_name(match['team2']['name']))}, "
                                             f"home_score2={fuzz.ratio(clean_team_name(home_team_translated), clean_team_name(match['team2']['name']))}, "
                                             f"away_score2={fuzz.ratio(clean_team_name(away_team_translated), clean_team_name(match['team1']['name']))}, "
                                             f"time_match={time_within_window(wib_time, match['kickoff_time'])}")
                        
                        except Exception as e:
                            logging.error(f"Error memproses pertandingan Rereyano {existing_id}: {e}")
                            continue
                    
                    if not match_found:
                        logging.warning(f"Tidak ada pertandingan yang cocok untuk Rereyano: {home_team_translated} vs {away_team_translated}, "
                                       f"league={league_name_translated}, time={wib_time}, date={wib_date}. Tidak menambahkan server.")
                            
            except ValueError as e:
                logging.error(f"Error mem-parsing tanggal/waktu Rereyano {date_str} {time_str}: {e}")
                continue
                
        except Exception as e:
            logging.error(f"Error memproses baris Rereyano '{line}': {e}")
            continue
    
    return matches

def scrape_sportsonline_servers(url, matches, days=5, cache_file='sportsonline_cache.html', dict_file='french_dict.json'):
    """Mengambil server dari SportsOnline dan mencocokkannya dengan pertandingan."""
    utc1_tz = pytz.timezone('Europe/London')
    french_dict = load_french_dict(dict_file)
    
    logging.info(f"Mengambil data dari SportsOnline: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        text = response.text
        if cache_file:
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(text)
        lines = text.split('\n')
        schedule_lines = [line for line in lines if re.match(r'\d{2}:\d{2}\s+.*?\s*x\s*.*?\s*\|.*sport[zs]online\.si.*', line, re.IGNORECASE)]
        logging.info(f"Isi SportsOnline prog.txt (semua baris jadwal, {len(schedule_lines)} baris):\n" + '\n'.join(schedule_lines))
    except Exception as e:
        logging.warning(f"Gagal mengambil {url}, mencoba cache: {type(e).__name__}: {str(e)}")
        if cache_file and os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                text = f.read()
        else:
            logging.warning(f"Tidak ada data untuk {url}, menggunakan data kosong")
            return matches
    
    lines = text.split('\n')
    current_date = datetime.now().date()
    
    for line in lines:
        line = line.strip()
        if not line:
            logging.debug("Baris kosong di SportsOnline, dilewati")
            continue
        
        match = re.match(
            r'(\d{2}:\d{2})\s+((?:[^:]+?\s*:\s*)?)(.*?)(?:\s*W)?\sx\s*(.*?)(?:\s*W)?(?:\s*\((W)\))?\s*\|\s*(https?://sport[zs]online\.si/channels/[^\s]+)', 
            line, re.IGNORECASE
        )
        if not match:
            logging.debug(f"Baris SportsOnline tidak cocok dengan regex: {line}")
            continue
        
        time_str, league_name, home_team, away_team, is_womens_explicit, server_url = match.groups()
        is_womens_sportsonline = bool(
            is_womens_explicit or 
            home_team.strip().endswith(' W') or 
            away_team.strip().endswith(' W') or
            french_dict['teams'].get(home_team.strip(), '').endswith(' Women') or
            french_dict['teams'].get(away_team.strip(), '').endswith(' Women')
        )
        
        league_name = league_name.strip(':').strip() if league_name else 'Unknown League'
        league_name_translated = french_dict['leagues'].get(league_name.strip(), league_name.strip())
        if league_name_translated == 'Unknown League':
            league_name_translated = 'FIFA Club World Cup' if not is_womens_sportsonline else 'Women’s International'
        
        logging.debug(f"Hasil ekstrak SportsOnline: Time={time_str}, League={league_name_translated}, Home={home_team.strip()}, Away={away_team.strip()}, Womens={is_womens_sportsonline}, URL={server_url}")
        
        try:
            match_date = current_date
            match_date_str = current_date.strftime('%Y-%m-%d')
            wib_date, wib_time = convert_to_wib(time_str, match_date_str, utc1_tz)
            
            home_team_translated = french_dict['teams'].get(home_team.strip(), home_team.strip())
            if home_team_translated == home_team.strip():
                home_team_translated = find_team_fallback(home_team.strip(), matches, threshold=50)
            
            away_team_translated = french_dict['teams'].get(away_team.strip(), away_team.strip())
            if away_team_translated == away_team.strip():
                away_team_translated = find_team_fallback(away_team.strip(), matches, threshold=70)
            
            logging.debug(f"SportsOnline setelah terjemahan: home={home_team_translated}, away={away_team_translated}, league={league_name_translated}")
            
            if len(home_team_translated) < 2 or len(away_team_translated) < 2:
                logging.warning(f"Nama tim SportsOnline tidak valid: Home={home_team_translated}, Away={away_team_translated}")
                continue
            
            match_id = generate_match_id(home_team_translated, away_team_translated)
            match_found = False
            added_servers = []
            
            for existing_id, match in list(matches.items()):
                try:
                    if match.get('is_womens', False) != is_womens_sportsonline:
                        logging.debug(f"Melewati pertandingan Flashscore: {existing_id}, is_womens Flashscore={match.get('is_womens', False)}, is_womens SportsOnline={is_womens_sportsonline}")
                        continue
                    
                    league_match = match_league(league_name_translated, match['league'], threshold=30)
                    time_match = time_within_window(wib_time, match['kickoff_time'], window_minutes=120)
                    
                    home_match1 = match_name_sportsonline(home_team_translated, match['team1']['name'], threshold=70)
                    away_match1 = match_name_sportsonline(away_team_translated, match['team2']['name'], threshold=70)
                    home_match2 = match_name_sportsonline(home_team_translated, match['team2']['name'], threshold=70)
                    away_match2 = match_name_sportsonline(away_team_translated, match['team1']['name'], threshold=70)
                    
                    logging.debug(f"Pencocokan untuk {existing_id}: league_match={league_match}, time_match={time_match}, "
                                 f"home_match1={home_match1}, away_match1={away_match1}, home_match2={home_match2}, away_match2={away_match2}, "
                                 f"home_score1={fuzz.ratio(clean_team_name(home_team_translated), clean_team_name(match['team1']['name']))}, "
                                 f"away_score1={fuzz.ratio(clean_team_name(away_team_translated), clean_team_name(match['team2']['name']))}")
                    
                    if league_match and time_match:
                        if (home_match1 and away_match1) or (home_match2 and away_match2):
                            match_found = True
                            logging.info(f"Pertandingan SportsOnline cocok: {existing_id}, home={home_team_translated}, away={away_team_translated}, is_womens={is_womens_sportsonline}")
                            
                            channel = server_url.split('/')[-1].replace('.php', '')
                            normalized_url = f'https://listsportsembed.blogspot.com/p/{channel}.html'
                            server_exists = any(
                                s['url'].lower().rstrip('/') == normalized_url.lower().rstrip('/')
                                for s in match['servers']
                            )
                            
                            if not server_exists and normalized_url not in added_servers:
                                mobile_count = len([s for s in match['servers'] if s['label'].startswith('CH-')])
                                label = f'CH-{mobile_count + 1}'
                                match['servers'].append({
                                    'url': normalized_url,
                                    'label': label
                                })
                                added_servers.append(normalized_url)
                                logging.info(f"Menambahkan server SportsOnline: {label} - {normalized_url} untuk {existing_id}")
                            else:
                                logging.debug(f"Server SportsOnline dilewati (sudah ada): {normalized_url}")
                    
                except Exception as e:
                    logging.error(f"Error memproses pertandingan SportsOnline {existing_id}: {e}")
                    continue
            
            if not match_found:
                logging.info(f"Tidak ada pertandingan yang cocok untuk SportsOnline: {home_team_translated} vs {away_team_translated}, "
                            f"league={league_name_translated}, time={wib_time}, is_womens={is_womens_sportsonline}. Tidak menambahkan server.")
                            
        except ValueError as e:
            logging.error(f"Error mem-parsing tanggal/waktu SportsOnline {time_str}: {e}")
            continue
                
    return matches

def merge_manual_schedule(manual_file, auto_schedule):
    """Menggabungkan jadwal manual dengan jadwal otomatis, menempatkan server manual di awal."""
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
            # Prepend manual servers to existing servers to ensure they appear first
            merged_servers = [
                server for server in manual_servers
                if server not in existing_servers
            ] + existing_servers
            merged_schedule[match_id]['servers'] = merged_servers
            merged_schedule[match_id]['is_womens'] = manual.get('is_womens', False)
            logging.info(f"Server untuk {match_id}: {merged_servers}")
        else:
            merged_schedule[match_id] = manual
            logging.info(f"Pertandingan manual baru: {match_id}")
    
    return merged_schedule

def compute_json_hash(data):
    """Menghitung hash dari data JSON."""
    try:
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
    except Exception as e:
        logging.error(f"Error menghitung hash JSON: {e}")
        return ""

def main():
    """Fungsi utama untuk menjalankan scraping dan menyimpan ke event.json."""
    flashscore_urls = [
        ("https://www.flashscore.com/football/world/fifa-club-world-cup/fixtures/", "FIFA Club World Cup"),
        ("https://www.flashscore.com/football/asia/asean-championship-u23/fixtures/", "ASEAN Championship U23"),
        ("https://www.flashscore.com/football/netherlands/eredivisie/fixtures/", "Eredivisie")
    ]
    sportsonline_url = "https://sportsonline.ci/prog.txt"
    rereyano_url = "https://rereyano.ru/"
    manual_schedule_file = "manual_schedule.json"
    dict_file = "french_dict.json"
    output_file = "event.json"
    
    matches = {}
    
    # Scrape Flashscore
    for url, name in flashscore_urls:
        try:
            league_matches = scrape_flashscore_schedule(url, days=5, league_name=name, cache_file=f'flashscore_cache_{name.lower().replace(" ", "_")}.html')
            matches.update(league_matches)
            logging.info(f"Tim Flashscore ({name}): {list(league_matches.keys())}")
        except Exception as e:
            logging.error(f"Gagal scraping Flashscore untuk {name}: {type(e).__name__}: {str(e)}")
            continue
    
    # Scrape Rereyano (before SportsOnline to ensure Rereyano servers come first)
    try:
        matches = scrape_rereyano_servers(rereyano_url, matches, dict_file=dict_file)
    except Exception as e:
        logging.error(f"Gagal scraping Rereyano: {type(e).__name__}: {str(e)}")
    
    # Scrape SportsOnline
    try:
        matches = scrape_sportsonline_servers(sportsonline_url, matches, dict_file=dict_file)
    except Exception as e:
        logging.error(f"Gagal scraping SportsOnline: {type(e).__name__}: {str(e)}")
    
    # Merge manual schedule
    try:
        matches = merge_manual_schedule(manual_schedule_file, matches)
    except Exception as e:
        logging.error(f"Gagal menggabungkan manual schedule: {type(e).__name__}: {str(e)}")
    
    # Convert matches to list for output
    output = list(matches.values())
    logging.debug(f"Isi output sebelum disimpan: {json.dumps(output, indent=2, ensure_ascii=False)}")
    
    # Load existing event.json for hash comparison
    old_data = []
    old_hash = ""
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            old_hash = compute_json_hash(old_data)
    except FileNotFoundError:
        logging.info(f"File {output_file} tidak ditemukan, akan membuat baru")
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding {output_file}: {e}")
    except Exception as e:
        logging.error(f"Gagal membaca {output_file}: {e}")
    
    # Compute hash of new data
    new_hash = compute_json_hash(output)
    
    # Save to event.json if data has changed or file doesn't exist
    if new_hash != old_hash or not old_data:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            logging.info(f"Jadwal updated: {output_file} dengan {len(output)} pertandingan")
        except Exception as e:
            logging.error(f"Gagal menyimpan {output_file}: {type(e).__name__}: {str(e)}")
    else:
        logging.info(f"Tidak ada perubahan, {output_file} tidak diupdate")
    
    logging.info(f"Total pertandingan: {len(output)}")
    return output

if __name__ == "__main__":
    main()
