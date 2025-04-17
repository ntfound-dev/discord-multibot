import DXJCOMMUNITY
import json
import threading
import time
import os
import random
import re
import requests
from DXJCOMMUNITY import print_logo 
from dotenv import load_dotenv
from datetime import datetime
from colorama import init, Fore, Style
import logging # Gunakan logging untuk output yang lebih terstruktur
import traceback # Untuk logging error detail

# Konfigurasi logging dasar
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s')
# Matikan logger dari library requests yang terlalu verbose
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Inisialisasi colorama
init(autoreset=True)
# Memuat variabel lingkungan
load_dotenv()

# Banner
print("\n" + Fore.MAGENTA + "="*80)
print("PUSH ROLE DISCORD - MULTI-BOT SETUP (Fitur Balas Antar Bot)".center(80))
print("="*80 + Style.RESET_ALL + "\n")

# Pengaturan Token & API Keys
use_bot_token = os.getenv('USE_BOT_TOKEN', 'true').lower() == 'true'
discord_tokens_env = os.getenv('DISCORD_TOKENS', '')
google_api_keys_env = os.getenv('GOOGLE_API_KEYS', '')

if not discord_tokens_env:
    raise ValueError("DISCORD_TOKENS tidak ditemukan di .env!")
discord_tokens_list = [token.strip() for token in discord_tokens_env.split(',') if token.strip()]

if not google_api_keys_env:
    # Tidak error jika AI tidak digunakan, tapi beri peringatan
    logging.warning("GOOGLE_API_KEYS tidak ditemukan di .env! Mode AI tidak akan berfungsi.")
    google_api_keys = []
else:
    google_api_keys = [key.strip() for key in google_api_keys_env.split(',') if key.strip()]

# --- Variabel Global & Kunci ---
processed_message_ids = set()
processed_message_ids_lock = threading.Lock() # Lock untuk akses aman ke set ID pesan

used_api_keys = set()
api_key_lock = threading.Lock() # Lock untuk akses aman ke set kunci API yang digunakan
cooldown_time = 86400 # 24 jam

# Data bersama antar thread channel (perlu lock untuk akses aman)
channel_last_action_times = {}
channel_data_lock = threading.Lock() # Lock untuk data spesifik channel (seperti last action time)

# --- Fungsi Helper ---

def log_message(message, level="INFO", channel_name=None):
    """Mencatat pesan log dengan level dan prefix channel (jika ada)."""
    prefix = f"[{channel_name}] " if channel_name else ""
    log_func = getattr(logging, level.lower(), logging.info)
    # Menggunakan logger yang dikonfigurasi di awal
    log_func(f"{prefix}{message}")

def get_auth_header(token):
    """Membuat header otorisasi."""
    auth = f"Bot {token}" if use_bot_token else token
    return {'Authorization': auth, 'User-Agent': 'Python DiscordBot (Multi-Bot v2)', 'Content-Type': 'application/json'}

def trigger_typing(channel_id, token, duration=5, channel_name="Unknown"):
    """Mengirim typing indicator (best effort, tanpa log error detail)."""
    headers = get_auth_header(token)
    url = f"https://discord.com/api/v10/channels/{channel_id}/typing"
    end_time = time.time() + duration
    log_message(f"Sending typing indicator for {duration}s (Bot ...{token[-6:]})", "DEBUG", channel_name)
    while time.time() < end_time:
        try:
            requests.post(url, headers=headers, timeout=3) # Timeout pendek
        except Exception:
            # log_message(f"Failed to send typing indicator (Bot ...{token[-6:]})", "DEBUG", channel_name) # Kurangi log noise
            break # Hentikan jika ada error
        time_left = end_time - time.time()
        if time_left <= 0: break
        # Discord expects typing events roughly every 8-9 seconds to keep the indicator active
        time.sleep(min(8.5, max(0.5, time_left)))

def get_random_api_key(channel_name="Unknown"):
    """Memilih Google API Key acak yang belum rate limited."""
    global used_api_keys
    with api_key_lock: # Pastikan akses thread-safe ke used_api_keys
        available_keys = [key for key in google_api_keys if key not in used_api_keys]
        if not available_keys:
            if not google_api_keys: # Jika memang tidak ada key sama sekali
                # log_message("Tidak ada Google API Key yang dikonfigurasi.", "ERROR", channel_name) # Sudah di log di tempat lain
                return None
            # Jika semua key sudah digunakan/rate limited
            log_message(f"Semua {len(used_api_keys)} Google API key rate limited. Menunggu cooldown {cooldown_time} detik...", "ERROR", channel_name)
            # Tunggu di luar lock agar tidak memblok thread lain yang mungkin masih punya key
            time.sleep(cooldown_time)
            # Setelah cooldown, reset set used_api_keys (masih di dalam lock)
            used_api_keys.clear()
            log_message("Cooldown selesai, mencoba lagi mendapatkan API key...", "INFO", channel_name)
            # Coba lagi ambil key setelah reset
            available_keys = [key for key in google_api_keys if key not in used_api_keys]
            if not available_keys: # Jika masih kosong setelah reset (jarang terjadi)
                 log_message("Masih tidak ada API key tersedia setelah cooldown.", "ERROR", channel_name)
                 return None

        selected_key = random.choice(available_keys)
        log_message(f"Menggunakan Google API Key: ...{selected_key[-6:]}", "DEBUG", channel_name)
        return selected_key

def mark_api_key_used(api_key):
    """Menandai API Key sebagai rate limited."""
    global used_api_keys
    with api_key_lock:
        used_api_keys.add(api_key)

def get_random_message_from_file(channel_name="Unknown"):
    """Mengambil pesan acak dari pesan.txt."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, "pesan.txt")
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Isi pesan di sini, satu per baris\n")
                f.write("Halo!\n")
                f.write("Semangat ya hari ini!\n")
            log_message("File pesan.txt dibuat karena tidak ada. Silakan isi pesan.", "INFO", channel_name)
            return "Halo!" # Kembalikan pesan default jika file baru dibuat

        with open(file_path, "r", encoding="utf-8") as file:
            messages = [line.strip() for line in file.readlines() if line.strip() and not line.startswith("#")]
            if messages:
                return random.choice(messages)
            else:
                log_message("File pesan.txt kosong atau hanya berisi komentar.", "WARNING", channel_name)
                return None # Kembalikan None jika tidak ada pesan valid
    except Exception as e:
        log_message(f"Error membaca pesan.txt: {e}", "ERROR", channel_name)
        return None

def generate_language_specific_prompt(user_message, prompt_language):
    """Membuat prompt AI."""
    user_message = str(user_message) # Pastikan string
    # Bersihkan @mentions bot jika ada (opsional, tapi bisa membantu AI)
    user_message = re.sub(r'<@!?\d+>', '', user_message).strip()

    if not user_message: # Jika pesan jadi kosong setelah dibersihkan
        return None

    # Prompt tetap sama, AI diharapkan bisa menyesuaikan gaya bicara
    if prompt_language == 'id':
        return f"Kamu adalah teman ngobrol santai di Discord. Balas pesan ini dalam Bahasa Indonesia informal, gaul, dan natural, *cukup satu kalimat pendek saja*. Jangan pernah mengaku sebagai AI atau model bahasa. Pesan dari user: \"{user_message}\""
    elif prompt_language == 'en':
        return f"You are a casual chat buddy on Discord. Reply to this message in natural, informal, conversational English, *just one short sentence*. Never identify yourself as an AI or language model. User's message: \"{user_message}\""
    else: # Default ke bahasa Indonesia jika tidak spesifik
        return f"Kamu adalah teman ngobrol santai di Discord. Balas pesan ini dalam Bahasa Indonesia informal, gaul, dan natural, *cukup satu kalimat pendek saja*. Jangan pernah mengaku sebagai AI atau model bahasa. Pesan dari user: \"{user_message}\""


def generate_reply(prompt_content, prompt_language, use_google_ai=True, channel_name="Unknown"):
    """Menghasilkan balasan (AI atau File)."""
    global last_generated_text # last_generated_text mungkin kurang berguna di multi-channel

    if use_google_ai:
        api_key = get_random_api_key(channel_name)
        if not api_key:
            log_message("Tidak ada Google API Key valid tersedia untuk AI.", "ERROR", channel_name)
            return None # Gagal mendapatkan key

        ai_prompt = generate_language_specific_prompt(prompt_content, prompt_language)
        if not ai_prompt:
             log_message("Prompt AI tidak dapat dibuat (mungkin pesan asli kosong?).", "WARNING", channel_name)
             return None

        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}'
        headers = {'Content-Type': 'application/json'}
        # Menambahkan konfigurasi keamanan dasar untuk Gemini (opsional)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        data = {
            'contents': [{'parts': [{'text': ai_prompt}]}],
            'safetySettings': safety_settings
        }
        retries = 2 # Jumlah percobaan ulang jika rate limit atau error

        for attempt in range(retries + 1): # Coba sekali + retries
            try:
                response = requests.post(url, headers=headers, json=data, timeout=30)

                if response.status_code == 429:
                    log_message(f"API Key ...{api_key[-6:]} rate limit (Attempt {attempt+1}). Menandai dan coba key lain.", "WARNING", channel_name)
                    mark_api_key_used(api_key) # Tandai key ini sudah kena limit
                    if attempt < retries:
                        new_api_key = get_random_api_key(channel_name) # Coba dapatkan key baru
                        if not new_api_key: return None # Jika tidak ada lagi key
                        api_key = new_api_key # Update api_key untuk log dan retry berikutnya
                        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}'
                        continue # Coba lagi dengan key baru
                    else:
                        log_message("Semua percobaan gagal karena rate limit.", "ERROR", channel_name)
                        return None # Gagal setelah retry

                # Cek jika respons diblokir karena safety settings
                if response.status_code == 200:
                    result = response.json()
                    if not result.get('candidates'):
                         # Cek promptFeedback untuk alasan blokir
                         feedback = result.get('promptFeedback', {})
                         block_reason = feedback.get('blockReason', 'UNKNOWN')
                         safety_ratings = feedback.get('safetyRatings', [])
                         log_message(f"Respons AI diblokir (Key: ...{api_key[-6:]}). Alasan: {block_reason}. Ratings: {safety_ratings}", "WARNING", channel_name)
                         # Jangan retry jika diblokir, anggap gagal
                         return None # Atau kembalikan pesan default

                response.raise_for_status() # Error untuk status code 4xx/5xx lainnya
                result = response.json() # Ulangi parse jika tidak diblokir

                # Parsing respons Gemini
                candidates = result.get('candidates')
                if not candidates: # Seharusnya tidak terjadi jika raise_for_status tidak error dan tidak diblokir
                    log_message(f"Respons API tidak valid (tidak ada 'candidates' setelah cek blokir) (Key: ...{api_key[-6:]}). Respons: {result}", "ERROR", channel_name)
                    continue # Coba lagi jika masih ada attempt

                content = candidates[0].get('content')
                if not content or not content.get('parts'):
                    log_message(f"Respons API tidak valid (tidak ada 'content'/'parts') (Key: ...{api_key[-6:]}). Respons: {result}", "ERROR", channel_name)
                    continue

                generated_text = content['parts'][0].get('text', '').strip()

                if not generated_text:
                    log_message(f"API Google mengembalikan teks kosong (Key: ...{api_key[-6:]}).", "WARNING", channel_name)
                    # Bisa dianggap gagal atau coba lagi
                    continue

                log_message(f"AI Generated (Key ...{api_key[-6:]}): \"{generated_text[:60]}...\"", "DEBUG", channel_name)
                return generated_text # Berhasil

            except requests.exceptions.RequestException as e:
                log_message(f"Error request Google API (Key: ...{api_key[-6:]}, Attempt {attempt+1}): {e}", "ERROR", channel_name)
                if attempt < retries:
                    time.sleep(2 + attempt) # Backoff sebelum retry
                else:
                    log_message("Gagal request Google API setelah retry.", "ERROR", channel_name)
                    return None # Gagal setelah retry
            except Exception as e:
                log_message(f"Error tak terduga saat proses respons Google API (Key: ...{api_key[-6:]}): {e}", "ERROR", channel_name)
                logging.error(traceback.format_exc()) # Log traceback
                return None # Gagal karena error tak terduga

        log_message("Gagal menghasilkan balasan AI setelah semua percobaan.", "ERROR", channel_name)
        return None
    else: # Mode File
        return get_random_message_from_file(channel_name)

def get_channel_info(channel_id, token):
    """Mengambil info channel (nama, server). Best effort."""
    headers = get_auth_header(token)
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    try:
        response = requests.get(url, headers=headers, timeout=7)
        response.raise_for_status()
        data = response.json()
        name = data.get('name', f'Unknown Channel ({channel_id})')
        guild_id = data.get('guild_id')
        server = "Direct Message" if not guild_id else f"Server ({guild_id})" # Tidak perlu ambil nama guild
        return server, name, True # Sukses
    except requests.exceptions.HTTPError as http_err:
        # Log error spesifik jika penting (misal 403 Forbidden)
        if http_err.response.status_code == 403:
             logging.warning(f"Gagal get channel info {channel_id} (Bot ...{token[-6:]}): Akses ditolak (403)")
        elif http_err.response.status_code == 404:
             logging.warning(f"Gagal get channel info {channel_id} (Bot ...{token[-6:]}): Channel tidak ditemukan (404)")
        return "Error Server", f"Error Channel ({channel_id})", False
    except requests.exceptions.RequestException:
        return "Error Server", f"Error Channel ({channel_id})", False
    except Exception as e:
        logging.error(f"Error tak terduga get_channel_info {channel_id}: {e}")
        return "Error Server", f"Error Channel ({channel_id})", False


def get_bot_info(token):
    """Mengambil info bot (username, ID)."""
    headers = get_auth_header(token)
    url = "https://discord.com/api/v10/users/@me"
    try:
        response = requests.get(url, headers=headers, timeout=7)
        response.raise_for_status()
        data = response.json()
        username = data.get("username", "Unknown")
        discriminator = data.get("discriminator") # Mungkin '0' atau None untuk username baru
        display_name = f"{username}#{discriminator}" if discriminator and discriminator != "0" else username
        bot_id = data.get("id", "Unknown")
        return display_name, bot_id
    except requests.exceptions.HTTPError as http_err:
         if http_err.response.status_code == 401: # Unauthorized
              logging.error(f"Token tidak valid: ...{token[-6:]} (401 Unauthorized)")
         else:
              logging.error(f"HTTP Error get_bot_info (...{token[-6:]}): {http_err}")
         return "Invalid Token?", "Unknown"
    except Exception as e:
        logging.error(f"Error get_bot_info (...{token[-6:]}): {e}")
        return "Error Getting Info", "Unknown"

def delayed_delete(channel_id, message_id, delay, token, channel_name="Unknown"):
    """Menunda penghapusan pesan."""
    if delay > 0:
        log_message(f"Menunggu {delay} detik untuk hapus pesan {message_id}...", "DEBUG", channel_name)
        time.sleep(delay)
    delete_message(channel_id, message_id, token, channel_name)

def delete_message(channel_id, message_id, token, channel_name="Unknown"):
    """Menghapus pesan (best effort)."""
    headers = get_auth_header(token)
    url = f'https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}'
    try:
        response = requests.delete(url, headers=headers, timeout=10)
        if response.status_code == 204:
            log_message(f"Pesan {message_id} berhasil dihapus (Bot ...{token[-6:]}).", "INFO", channel_name)
        elif response.status_code == 403:
            log_message(f"Gagal hapus {message_id} (Bot ...{token[-6:]}): Tidak punya izin (403).", "ERROR", channel_name)
        elif response.status_code == 404:
            log_message(f"Gagal hapus {message_id} (Bot ...{token[-6:]}): Pesan tidak ditemukan (404, mungkin sudah dihapus).", "WARNING", channel_name)
        else:
             log_message(f"Gagal hapus {message_id} (Bot ...{token[-6:]}). Status: {response.status_code}", "ERROR", channel_name)
    except requests.exceptions.RequestException as e:
        log_message(f"Error koneksi saat hapus {message_id} (Bot ...{token[-6:]}): {e}", "ERROR", channel_name)
    except Exception as e:
        log_message(f"Error tak terduga saat hapus {message_id} (Bot ...{token[-6:]}): {e}", "ERROR", channel_name)


def send_message(channel_id, message_text, token, reply_to=None, delete_after=None, delete_immediately=False, channel_name="Unknown"):
    """Mengirim pesan ke channel."""
    if not message_text or not isinstance(message_text, str) or not message_text.strip():
        log_message("Pesan kosong atau tidak valid, tidak dikirim.", "WARNING", channel_name)
        return False # Gagal karena pesan tidak valid

    headers = get_auth_header(token)
    payload = {'content': message_text[:2000]} # Batasi panjang pesan
    if reply_to:
        payload["message_reference"] = {"message_id": str(reply_to), "fail_if_not_exists": False}
        log_message(f"Menyiapkan pesan sebagai balasan ke {reply_to} (Bot ...{token[-6:]})", "DEBUG", channel_name)
    else:
        log_message(f"Menyiapkan pesan biasa (Bot ...{token[-6:]})", "DEBUG", channel_name)


    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)

        if response.status_code in [200, 201]: # 200 OK atau 201 Created (jarang)
            data = response.json()
            message_id = data.get("id")
            log_message(f"Pesan terkirim (ID: {message_id}, Bot ...{token[-6:]}): \"{message_text[:50]}...\"", "SUCCESS", channel_name)

            # Handle penghapusan setelah kirim
            if message_id and delete_after is not None:
                try:
                    delete_delay = int(delete_after)
                    if delete_immediately or delete_delay == 0:
                         log_message(f"Menjadwalkan penghapusan segera untuk pesan {message_id}.", "INFO", channel_name)
                         threading.Thread(target=delete_message, args=(channel_id, message_id, token, channel_name), daemon=True, name=f"Delete-{message_id[:5]}").start()
                    elif delete_delay > 0:
                         log_message(f"Menjadwalkan penghapusan pesan {message_id} dalam {delete_delay} detik.", "INFO", channel_name)
                         threading.Thread(target=delayed_delete, args=(channel_id, message_id, delete_delay, token, channel_name), daemon=True, name=f"DelayedDelete-{message_id[:5]}").start()
                except (ValueError, TypeError):
                    log_message(f"Nilai delete_after ({delete_after}) tidak valid untuk pesan {message_id}. Tidak dihapus.", "WARNING", channel_name)
            return True # Sukses mengirim

        elif response.status_code == 403:
            log_message(f"Gagal kirim (Bot ...{token[-6:]}): Tidak punya izin kirim pesan (403).", "ERROR", channel_name)
        elif response.status_code == 429: # Rate Limit
            retry_after = response.json().get('retry_after', 5) # Ambil waktu tunggu dari Discord
            log_message(f"Rate limit Discord saat kirim (Bot ...{token[-6:]})! Menunggu {retry_after:.2f} detik...", "ERROR", channel_name)
            time.sleep(retry_after + 0.5) # Tunggu sesuai instruksi + buffer
        elif response.status_code == 400 and "message_reference" in str(response.content): # Cek jika error karena reference
             log_message(f"Gagal kirim (Bot ...{token[-6:]}): Pesan yang direply tidak ditemukan (400 Bad Request). Mengirim tanpa reply...", "WARNING", channel_name)
             # Coba kirim lagi tanpa reply
             del payload["message_reference"]
             response_noreply = requests.post(url, json=payload, headers=headers, timeout=15)
             if response_noreply.status_code in [200, 201]:
                 log_message(f"Pesan berhasil dikirim tanpa reply (Bot ...{token[-6:]}).", "SUCCESS", channel_name)
                 # Handle delete lagi jika perlu
                 data_noreply = response_noreply.json()
                 message_id_noreply = data_noreply.get("id")
                 if message_id_noreply and delete_after is not None:
                    try:
                        delete_delay = int(delete_after)
                        if delete_immediately or delete_delay == 0:
                             threading.Thread(target=delete_message, args=(channel_id, message_id_noreply, token, channel_name), daemon=True, name=f"Delete-{message_id_noreply[:5]}").start()
                        elif delete_delay > 0:
                             threading.Thread(target=delayed_delete, args=(channel_id, message_id_noreply, delete_delay, token, channel_name), daemon=True, name=f"DelayedDelete-{message_id_noreply[:5]}").start()
                    except (ValueError, TypeError): pass # Log sudah ada sebelumnya
                 return True
             else:
                 log_message(f"Gagal kirim ulang tanpa reply (Bot ...{token[-6:]}). Status: {response_noreply.status_code}", "ERROR", channel_name)
                 # Kembalikan False karena percobaan awal gagal
                 return False

        else: # Error lain
            log_message(f"Gagal kirim pesan (Bot ...{token[-6:]}). Status: {response.status_code}, Respons: {response.text[:100]}", "ERROR", channel_name)
        return False # Gagal mengirim

    except requests.exceptions.RequestException as e:
        log_message(f"Error koneksi saat kirim pesan (Bot ...{token[-6:]}): {e}", "ERROR", channel_name)
        return False # Gagal mengirim
    except Exception as e:
        log_message(f"Error tak terduga saat kirim pesan (Bot ...{token[-6:]}): {e}", "ERROR", channel_name)
        logging.error(traceback.format_exc())
        return False

def get_slow_mode_delay(channel_id, token, channel_name="Unknown"):
    """Mendapatkan delay slow mode channel (best effort)."""
    headers = get_auth_header(token)
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        delay = response.json().get("rate_limit_per_user", 0)
        if delay > 0:
             log_message(f"Slow mode aktif: {delay} detik.", "DEBUG", channel_name)
        return delay
    except Exception:
        return 0 # Anggap 0 jika gagal cek

# --- Fungsi Inti Auto-Reply (Multi-Bot per Channel) ---
def auto_reply_channel_manager(channel_id, channel_name, settings, assigned_tokens, bot_ids_in_channel):
    """Loop utama yang mengelola operasi multi-bot untuk SATU channel."""
    log_message(f"Memulai manager untuk [{channel_name}] ({channel_id}) dengan {len(assigned_tokens)} bot.", "INFO")
    current_thread = threading.current_thread()
    current_thread.name = f"Manager-{channel_name[:10]}" # Beri nama thread agar mudah diidentifikasi di log

    if not assigned_tokens:
        log_message("Tidak ada bot yang ditugaskan ke channel ini. Thread berhenti.", "ERROR", channel_name)
        return

    # Ambil pengaturan probabilitas balas antar bot
    bot_reply_probability = settings.get("bot_reply_probability", 0.0) # Default 0 (nonaktif)

    while True:
        action_performed_in_cycle = False # Lacak apakah ada aksi kirim pesan di siklus ini
        prompt_content = None # Reset prompt content di setiap siklus
        reply_to_id = None    # Reset reply target di setiap siklus
        try:
            is_ai_mode = settings.get("use_google_ai", False)
            interval = settings.get("delay_interval", 60) # Default interval

            # --- Tunggu Interval Antar Siklus ---
            log_message(f"Menunggu interval siklus {interval} detik...", "WAIT", channel_name)
            time.sleep(interval)

            # --- Pilih Bot Secara Acak Untuk Aksi Berikutnya ---
            if not assigned_tokens: # Cek lagi jika ada masalah
                 log_message("Daftar token kosong! Tidak bisa memilih bot.", "ERROR", channel_name)
                 time.sleep(60) # Tunggu lama sebelum coba lagi
                 continue
            current_token = random.choice(assigned_tokens)
            log_message(f"Bot terpilih untuk siklus ini: ...{current_token[-6:]}", "DEBUG", channel_name)

            # --- Cek & Tunggu Slow Mode (jika diaktifkan) ---
            if settings.get("use_slow_mode", True): # Default aktifkan
                slow_mode_delay = get_slow_mode_delay(channel_id, current_token, channel_name)
                if slow_mode_delay > 0:
                    with channel_data_lock: # Lock akses ke dict waktu aksi terakhir
                        last_action = channel_last_action_times.get(channel_id, 0)
                    time_since_last = time.time() - last_action
                    wait_needed = max(0, slow_mode_delay - time_since_last)
                    if wait_needed > 0:
                        log_message(f"Perlu menunggu slow mode {wait_needed:.1f} detik lagi.", "WAIT", channel_name)
                        time.sleep(wait_needed + 0.2) # Tambah buffer sedikit

            # --- Aksi Utama (Baca Pesan atau Kirim File) ---
            if is_ai_mode:
                # --- Mode AI: Baca Pesan & Balas (jika diaktifkan) ---
                if settings.get("enable_read_message", True):
                    read_delay = settings.get("read_delay", 5)
                    if read_delay > 0:
                        log_message(f"Menunggu {read_delay} detik sebelum baca pesan...", "WAIT", channel_name)
                        time.sleep(read_delay)

                    log_message("Mencoba membaca pesan terakhir...", "INFO", channel_name)
                    headers = get_auth_header(current_token) # Gunakan token terpilih untuk baca

                    try:
                        # Ambil 1 pesan terakhir saja
                        response = requests.get(f'https://discord.com/api/v10/channels/{channel_id}/messages?limit=1', headers=headers, timeout=10)
                        response.raise_for_status()
                        messages = response.json()

                        if messages:
                            msg = messages[0]
                            msg_id = msg.get('id')
                            author = msg.get('author', {})
                            author_id = author.get('id')
                            author_name = author.get('global_name') or author.get('username', 'Unknown User')
                            content = msg.get('content', '').strip()

                            # Cek apakah pesan sudah diproses sebelumnya
                            with processed_message_ids_lock:
                                is_processed = msg_id in processed_message_ids

                            log_message(f"Pesan terakhir dibaca (ID: {msg_id}, Author: {author_name} [{author_id}], Processed: {is_processed}): \"{content[:70]}...\"", "DEBUG", channel_name)

                            # --- Logika Keputusan Memproses Pesan ---
                            should_process = False
                            is_from_managed_bot = author_id in bot_ids_in_channel

                            if not is_processed:
                                if not is_from_managed_bot:
                                    # Selalu proses pesan dari user atau bot lain (tidak dikelola script ini)
                                    should_process = True
                                    log_message(f"Pesan baru dari {author_name} (bukan bot terkelola) terdeteksi.", "INFO", channel_name)
                                elif bot_reply_probability > 0: # Hanya cek probabilitas jika fitur aktif
                                    # Pesan dari bot yang dikelola. Terapkan probabilitas.
                                    if random.random() < bot_reply_probability:
                                        should_process = True
                                        log_message(f"Memutuskan untuk membalas pesan dari bot terkelola {author_name} (Probabilitas: {bot_reply_probability*100:.1f}%)", "INFO", channel_name)
                                    else:
                                        log_message(f"Memutuskan untuk TIDAK membalas pesan dari bot terkelola {author_name} (Probabilitas: {bot_reply_probability*100:.1f}%)", "INFO", channel_name)
                                        # Tandai sudah diproses meskipun tidak dibalas, agar tidak dievaluasi ulang
                                        with processed_message_ids_lock:
                                            processed_message_ids.add(msg_id)
                                else:
                                     # Pesan dari bot terkelola, tapi fitur balas antar bot nonaktif (prob = 0)
                                     log_message(f"Mengabaikan pesan dari bot terkelola {author_name} karena fitur balas antar bot nonaktif.", "DEBUG", channel_name)
                                     # Tandai sudah diproses
                                     with processed_message_ids_lock:
                                         processed_message_ids.add(msg_id)

                            # --- Proses Pesan Jika Diputuskan (should_process == True) ---
                            if should_process:
                                if content: # Hanya proses jika ada teks
                                    prompt_content = content
                                    reply_to_id = msg_id

                                    # Tandai sudah diproses SEGERA
                                    with processed_message_ids_lock:
                                        processed_message_ids.add(msg_id)
                                        # Optional: Batasi ukuran set
                                        if len(processed_message_ids) > 5000:
                                            oldest_ids = list(processed_message_ids)[:1000]
                                            for old_id in oldest_ids:
                                                processed_message_ids.remove(old_id)
                                            log_message("Membersihkan cache ID pesan.", "DEBUG", channel_name)
                                else:
                                    log_message("Pesan baru terdeteksi tapi tidak ada konten teks. Dilewati.", "INFO", channel_name)
                                    # Tetap tandai sudah diproses
                                    with processed_message_ids_lock:
                                        processed_message_ids.add(msg_id)
                            # else: Pesan sudah diproses atau dari bot sendiri dan tidak lolos probabilitas/fitur nonaktif

                        else: # Tidak ada pesan di channel
                            log_message("Tidak ada pesan ditemukan di channel.", "INFO", channel_name)

                    except requests.exceptions.HTTPError as http_err:
                        log_message(f"Error HTTP saat baca pesan: {http_err}", "ERROR", channel_name)
                        if http_err.response.status_code == 403:
                            log_message("Bot kehilangan akses baca ke channel ini. Thread berhenti.", "CRITICAL", channel_name)
                            break # Hentikan loop thread ini
                    except requests.exceptions.RequestException as req_err:
                        log_message(f"Error koneksi saat baca pesan: {req_err}", "ERROR", channel_name)
                    except Exception as e:
                         log_message(f"Error tak terduga saat baca pesan: {e}", "ERROR", channel_name)
                         logging.error(traceback.format_exc())

                    # --- Jika ada prompt baru, hasilkan dan kirim balasan ---
                    # Kondisi ini hanya True jika should_process=True dan content ada
                    if prompt_content and reply_to_id:
                        log_message("Menghasilkan balasan AI...", "INFO", channel_name)
                        reply_token = random.choice(assigned_tokens) # Pilih bot acak untuk balas
                        log_message(f"Bot terpilih untuk membalas: ...{reply_token[-6:]}", "DEBUG", channel_name)

                        typing_duration = random.randint(5, 8)
                        typing_thread = threading.Thread(target=trigger_typing, args=(channel_id, reply_token, typing_duration, channel_name), daemon=True, name=f"Typing-{channel_name[:5]}")
                        typing_thread.start()

                        response_text = generate_reply(prompt_content, settings.get("prompt_language", "id"), use_google_ai=True, channel_name=channel_name)

                        typing_thread.join(timeout=1.0)

                        if response_text:
                            if send_message(
                                channel_id, response_text, reply_token,
                                reply_to=reply_to_id if settings.get("use_reply", True) else None,
                                delete_after=settings.get("delete_bot_reply"),
                                delete_immediately=settings.get("delete_immediately", False),
                                channel_name=channel_name
                            ):
                                action_performed_in_cycle = True # Berhasil kirim balasan
                        else:
                            log_message("Gagal menghasilkan balasan AI atau balasan kosong.", "WARNING", channel_name)
                    # else: Tidak ada pesan baru yang perlu dibalas

                else: # enable_read_message == False
                    log_message("Pembacaan pesan masuk dinonaktifkan dalam Mode AI.", "INFO", channel_name)

            else:
                # --- Mode File: Kirim Pesan Acak dari File ---
                log_message("Mode File Aktif. Mengambil pesan acak dari pesan.txt...", "INFO", channel_name)
                message_text = generate_reply("", "", use_google_ai=False, channel_name=channel_name)

                if message_text:
                    send_token = random.choice(assigned_tokens) # Pilih bot acak untuk kirim
                    log_message(f"Bot terpilih untuk mengirim pesan file: ...{send_token[-6:]}", "DEBUG", channel_name)

                    typing_duration = random.randint(2, 4)
                    typing_thread = threading.Thread(target=trigger_typing, args=(channel_id, send_token, typing_duration, channel_name), daemon=True, name=f"Typing-{channel_name[:5]}")
                    typing_thread.start()
                    time.sleep(random.uniform(0.5, 1.5))
                    typing_thread.join(timeout=1.0)

                    if send_message(
                        channel_id, message_text, send_token,
                        reply_to=None, # Mode file tidak me-reply
                        delete_after=settings.get("delete_bot_reply"),
                        delete_immediately=settings.get("delete_immediately", False),
                        channel_name=channel_name
                    ):
                        action_performed_in_cycle = True # Berhasil kirim pesan file
                else:
                    log_message("Tidak ada pesan valid ditemukan di pesan.txt atau error. Tidak mengirim.", "WARNING", channel_name)

            # --- Update Waktu Aksi Terakhir (jika ada aksi pengiriman) ---
            if action_performed_in_cycle:
                with channel_data_lock:
                    channel_last_action_times[channel_id] = time.time()
                log_message("Waktu aksi terakhir di channel ini diperbarui.", "DEBUG", channel_name)

        except Exception as e:
            log_message(f"!!! ERROR TIDAK TERDUGA di manager [{channel_name}] !!!: {e}", "CRITICAL")
            logging.error(traceback.format_exc()) # Log traceback lengkap untuk debug
            log_message("Mencoba melanjutkan siklus setelah 30 detik...", "WAIT", channel_name)
            time.sleep(30) # Beri jeda sebelum mencoba siklus berikutnya

# --- Fungsi Pengaturan Interaktif ---
def get_channel_settings_interactive(channel_id, channel_name, server_name, available_bots_info):
    """Meminta input pengaturan dari pengguna untuk satu channel."""
    print(Fore.CYAN + f"\n--- Pengaturan untuk Channel: {channel_name} ({channel_id}) ---" + Style.RESET_ALL)
    print(f"    Server: {server_name}")

    # --- Pilih Bot untuk Channel ini ---
    print("\n" + Fore.YELLOW + "Pilih Bot yang akan aktif di channel ini:" + Style.RESET_ALL)
    if not available_bots_info:
        print(Fore.RED + "Tidak ada bot valid yang tersedia untuk dipilih!" + Style.RESET_ALL)
        return None, None, None

    # Tampilkan bot yang tersedia dengan nomor urut
    bot_display_list = []
    for idx, token, info in available_bots_info:
        bot_display_list.append(f"  {idx}) {info['display_name']} (...{token[-6:]})")
    print('\n'.join(bot_display_list))


    assigned_bot_indices = set()
    while True: # Loop sampai input valid
        try:
            choice = input(Fore.GREEN + "Masukkan nomor bot (pisahkan koma jika > 1, atau 'all'): " + Style.RESET_ALL).strip().lower()
            if not choice: continue

            valid_indices = {idx for idx, _, _ in available_bots_info}

            if choice == 'all':
                chosen_indices = valid_indices
            else:
                chosen_indices_str = {i.strip() for i in choice.split(',') if i.strip()}
                if not all(i.isdigit() for i in chosen_indices_str):
                     print(Fore.RED + "Input tidak valid. Masukkan nomor saja atau 'all'." + Style.RESET_ALL)
                     continue
                chosen_indices = {int(i) for i in chosen_indices_str}

            if chosen_indices.issubset(valid_indices):
                if not chosen_indices:
                     print(Fore.RED + "Anda harus memilih setidaknya satu bot." + Style.RESET_ALL)
                     continue
                assigned_bot_indices = chosen_indices
                break
            else:
                invalid_chosen = chosen_indices - valid_indices
                print(Fore.RED + f"Nomor tidak valid: {', '.join(map(str, invalid_chosen))}. Pilih dari daftar di atas." + Style.RESET_ALL)
        except ValueError:
            print(Fore.RED + "Input tidak valid. Masukkan nomor saja, pisahkan dengan koma, atau 'all'." + Style.RESET_ALL)

    assigned_tokens = [token for idx, token, info in available_bots_info if idx in assigned_bot_indices]
    assigned_bot_ids = {info['bot_id'] for idx, token, info in available_bots_info if idx in assigned_bot_indices}
    assigned_bot_names = [info['display_name'] for idx, token, info in available_bots_info if idx in assigned_bot_indices]
    print(Fore.CYAN + f"-> Bot yang ditugaskan: {', '.join(assigned_bot_names)}" + Style.RESET_ALL)


    # --- Pilih Mode Operasi ---
    while True:
        ai_choice = input(Fore.GREEN + "Gunakan Google Gemini AI untuk balasan? (y/n, default y): " + Style.RESET_ALL).strip().lower()
        if ai_choice in ['y', 'n', '']:
            use_google_ai = ai_choice != 'n'
            break
        else: print(Fore.RED + "Input tidak valid (y/n)." + Style.RESET_ALL)

    settings = {"use_google_ai": use_google_ai}
    default_interval = 60 if use_google_ai else 300

    # --- Pengaturan Spesifik Mode ---
    if use_google_ai:
        print(Fore.YELLOW + "\n[Pengaturan Mode AI Gemini]" + Style.RESET_ALL)
        if not google_api_keys:
            log_message("PERINGATAN: Tidak ada Google API Keys di .env! Mode AI tidak akan berfungsi.", "ERROR", channel_name)
            settings["enable_read_message"] = False
            settings["prompt_language"] = "id"
            settings["read_delay"] = 0
            settings["delay_interval"] = 300
            settings["use_reply"] = False
            settings["bot_reply_probability"] = 0.0 # Nonaktifkan balas antar bot
        else:
            # Bahasa Prompt
            while True:
                lang_choice = input(Fore.GREEN + "  Bahasa prompt AI (id/en, default id): " + Style.RESET_ALL).strip().lower()
                if lang_choice in ['id', 'en', '']: settings["prompt_language"] = lang_choice or 'id'; break
                else: print(Fore.RED + "  Input tidak valid (id/en)." + Style.RESET_ALL)

            # Aktifkan Baca Pesan
            while True:
                read_choice = input(Fore.GREEN + "  Aktifkan baca pesan masuk & balas? (y/n, default y): " + Style.RESET_ALL).strip().lower()
                if read_choice in ['y', 'n', '']: settings["enable_read_message"] = read_choice != 'n'; break
                else: print(Fore.RED + "  Input tidak valid (y/n)." + Style.RESET_ALL)

            if settings["enable_read_message"]:
                # Delay Baca Pesan
                while True:
                    try:
                        delay = input(Fore.GREEN + "  Delay SEBELUM baca pesan (detik, default 5): " + Style.RESET_ALL)
                        settings["read_delay"] = int(delay or 5);
                        if settings["read_delay"] >= 0: break
                        else: print(Fore.RED + "  Delay tidak boleh negatif." + Style.RESET_ALL)
                    except ValueError: print(Fore.RED + "  Masukkan angka." + Style.RESET_ALL)

                # Kirim sebagai Reply
                while True:
                    reply_choice = input(Fore.GREEN + "  Kirim balasan sebagai 'reply'? (y/n, default y): " + Style.RESET_ALL).strip().lower()
                    if reply_choice in ['y', 'n', '']: settings["use_reply"] = reply_choice != 'n'; break
                    else: print(Fore.RED + "  Input tidak valid (y/n)." + Style.RESET_ALL)

                # --- BARU: Pengaturan Balas Antar Bot ---
                while True:
                    try:
                        prob_input = input(Fore.GREEN + "  Probabilitas bot membalas bot lain (0.0 - 1.0, default 0.0 = nonaktif): " + Style.RESET_ALL).strip()
                        if not prob_input: # Default jika kosong
                            settings["bot_reply_probability"] = 0.0
                            break
                        prob = float(prob_input)
                        if 0.0 <= prob <= 1.0:
                            settings["bot_reply_probability"] = prob
                            if prob > 0: print(Fore.CYAN + f"    -> Bot akan membalas bot lain dengan probabilitas {prob*100:.1f}%" + Style.RESET_ALL)
                            else: print(Fore.YELLOW + "    -> Fitur balas antar bot dinonaktifkan." + Style.RESET_ALL)
                            break
                        else:
                            print(Fore.RED + "  Masukkan angka antara 0.0 dan 1.0." + Style.RESET_ALL)
                    except ValueError:
                        print(Fore.RED + "  Masukkan angka desimal (gunakan titik '.')." + Style.RESET_ALL)
                # --- Akhir Pengaturan Balas Antar Bot ---

            else: # Jika baca nonaktif
                settings["read_delay"] = 0
                settings["use_reply"] = False
                settings["bot_reply_probability"] = 0.0 # Nonaktifkan jika tidak baca
                print(Fore.YELLOW + "  (Baca pesan nonaktif, bot hanya akan idle di mode AI)" + Style.RESET_ALL)


            # Interval Antar Siklus (AI)
            while True:
                try:
                    interval_prompt = f"  Interval antar {'balasan' if settings['enable_read_message'] else 'cek status'} (detik, default {default_interval}): "
                    interval = input(Fore.GREEN + interval_prompt + Style.RESET_ALL)
                    settings["delay_interval"] = int(interval or default_interval)
                    if settings["delay_interval"] > 0: break
                    else: print(Fore.RED + "  Interval harus lebih besar dari 0." + Style.RESET_ALL)
                except ValueError: print(Fore.RED + "  Masukkan angka." + Style.RESET_ALL)

    else: # Mode File
        print(Fore.YELLOW + "\n[Pengaturan Mode Pesan dari File (pesan.txt)]" + Style.RESET_ALL)
        get_random_message_from_file(channel_name) # Cek/buat file

        settings["prompt_language"] = "id"
        settings["enable_read_message"] = False
        settings["read_delay"] = 0
        settings["use_reply"] = False
        settings["bot_reply_probability"] = 0.0 # Nonaktifkan di mode file

        # Interval Kirim Pesan File
        while True:
            try:
                interval = input(Fore.GREEN + f"  Interval kirim pesan file (detik, default {default_interval}): " + Style.RESET_ALL)
                settings["delay_interval"] = int(interval or default_interval)
                if settings["delay_interval"] > 0: break
                else: print(Fore.RED + "  Interval harus lebih besar dari 0." + Style.RESET_ALL)
            except ValueError: print(Fore.RED + "  Masukkan angka." + Style.RESET_ALL)

    # --- Pengaturan Umum (Slow mode & Hapus Pesan Bot) ---
    print(Fore.YELLOW + "\n[Pengaturan Tambahan]" + Style.RESET_ALL)
    # Perhitungkan Slow Mode
    while True:
        slow_mode_choice = input(Fore.GREEN + "  Perhitungkan slow mode channel? (y/n, default y): " + Style.RESET_ALL).strip().lower()
        if slow_mode_choice in ['y', 'n', '']: settings["use_slow_mode"] = slow_mode_choice != 'n'; break
        else: print(Fore.RED + "  Input tidak valid (y/n)." + Style.RESET_ALL)

    # Hapus Pesan Bot
    while True:
        delete_choice = input(Fore.GREEN + "  Hapus pesan bot setelah dikirim? (y/n, default n): " + Style.RESET_ALL).strip().lower()
        if delete_choice in ['y', 'n', '']: hapus = delete_choice == 'y'; break
        else: print(Fore.RED + "  Input tidak valid (y/n)." + Style.RESET_ALL)

    if hapus:
        while True:
            try:
                delay_input = input(Fore.GREEN + "    Delay hapus (detik, 0=segera, kosong=tidak jadi hapus): " + Style.RESET_ALL).strip()
                if delay_input == '': # User tidak jadi hapus
                    settings["delete_bot_reply"] = None
                    settings["delete_immediately"] = False
                    print(Fore.YELLOW + "    Penghapusan pesan dibatalkan." + Style.RESET_ALL)
                    break
                delay = int(delay_input)
                if delay >= 0:
                    settings["delete_bot_reply"] = delay
                    settings["delete_immediately"] = (delay == 0)
                    print(Fore.CYAN + f"    -> Pesan bot akan dihapus setelah {delay} detik." + Style.RESET_ALL)
                    break
                else: print(Fore.RED + "    Delay harus 0 atau positif." + Style.RESET_ALL)
            except ValueError: print(Fore.RED + "    Masukkan angka atau biarkan kosong." + Style.RESET_ALL)
    else: # Tidak hapus
        settings["delete_bot_reply"] = None
        settings["delete_immediately"] = False

    # Rapikan output ringkasan pengaturan (opsional)
    print(Fore.YELLOW + "\n[Ringkasan Pengaturan Channel]" + Style.RESET_ALL)
    print(f"  - Mode: {'AI Gemini' if settings['use_google_ai'] else 'Pesan dari File'}")
    if settings['use_google_ai']:
        print(f"  - Baca Pesan: {'Aktif' if settings['enable_read_message'] else 'Nonaktif'}")
        if settings['enable_read_message']:
            print(f"  - Bahasa Prompt: {settings['prompt_language'].upper()}")
            print(f"  - Delay Baca: {settings['read_delay']} detik")
            print(f"  - Kirim sbg Reply: {'Ya' if settings['use_reply'] else 'Tidak'}")
            print(f"  - Prob. Balas Bot: {settings['bot_reply_probability']*100:.1f}%")
    print(f"  - Interval Siklus: {settings['delay_interval']} detik")
    print(f"  - Perhitungkan Slow Mode: {'Ya' if settings['use_slow_mode'] else 'Tidak'}")
    if settings['delete_bot_reply'] is not None:
        print(f"  - Hapus Pesan Bot: Ya (Delay: {settings['delete_bot_reply']} detik)")
    else:
        print(f"  - Hapus Pesan Bot: Tidak")

    return settings, assigned_tokens, assigned_bot_ids


# --- Blok Eksekusi Utama ---
if __name__ == "__main__":
    # 1. Verifikasi Token & Kumpulkan Info Bot yang Valid
    valid_tokens_info = [] # List of (index_for_user, token, info_dict)
    bot_accounts = {} # {token: info_dict} for quick lookup if needed later
    log_message("Memulai verifikasi token Discord dari .env...", "INFO")
    for i, token in enumerate(discord_tokens_list):
        display_name, bot_id = get_bot_info(token)
        if bot_id != "Unknown" and display_name != "Invalid Token?":
            info = {"display_name": display_name, "bot_id": bot_id}
            bot_accounts[token] = info
            valid_tokens_info.append((i + 1, token, info)) # Mulai index dari 1 untuk tampilan user
            log_message(f"Token #{i+1} VALID: {display_name} (ID: {bot_id})", "SUCCESS")
        else:
            log_message(f"Token #{i+1} (...{token[-6:]}) TIDAK VALID atau Gagal ambil info.", "ERROR")

    if not valid_tokens_info:
        log_message("Tidak ada token Discord yang valid ditemukan di .env. Program tidak bisa berjalan.", "CRITICAL")
        exit()
    log_message(f"Total {len(valid_tokens_info)} bot valid siap digunakan.", "INFO")


    # 2. Minta Input ID Channel Target
    input_channel_ids = []
    while not input_channel_ids:
        channel_ids_input = input(Fore.CYAN + "\nMasukkan ID channel target (pisahkan koma jika > 1): " + Style.RESET_ALL).strip()
        potential_ids = [cid.strip() for cid in channel_ids_input.split(',') if cid.strip()]
        numeric_ids = [cid for cid in potential_ids if cid.isdigit()]
        invalid_inputs = [cid for cid in potential_ids if not cid.isdigit()]

        if invalid_inputs:
            log_message(f"Input non-numerik diabaikan: {', '.join(invalid_inputs)}", "WARNING")

        if numeric_ids:
            input_channel_ids = list(dict.fromkeys(numeric_ids)) # Hapus duplikat sambil jaga urutan
            log_message(f"Channel ID target: {', '.join(input_channel_ids)}", "INFO")
            break
        else:
            print(Fore.RED + "Masukkan setidaknya satu ID channel numerik yang valid." + Style.RESET_ALL)


    # 3. Konfigurasi Setiap Channel Secara Interaktif
    channel_configs = {} # {channel_id: {"name": ..., "settings": ..., "tokens": [...], "bot_ids": {...}}}
    threads = [] # List untuk menyimpan thread manager channel

    log_message("Memulai konfigurasi interaktif per channel...", "INFO")

    for channel_id in input_channel_ids:
        log_message(f"Memeriksa akses & konfigurasi untuk Channel ID: {channel_id}...", "WAIT")
        accessible = False
        s_name, c_name = f"Unknown Server", f"Unknown Channel ({channel_id})"
        access_token = None # Token pertama yang berhasil akses

        # Coba akses channel menggunakan bot yang tersedia satu per satu
        for _, token, info in valid_tokens_info:
            server_name_check, channel_name_check, success = get_channel_info(channel_id, token)
            if success:
                s_name, c_name = server_name_check, channel_name_check
                accessible = True
                access_token = token # Simpan token yang berhasil
                log_message(f"Akses ke [{c_name}] di [{s_name}] berhasil diverifikasi (via Bot {info['display_name']}).", "SUCCESS")
                break # Cukup satu bot berhasil akses

        if not accessible:
            log_message(f"Gagal mengakses Channel ID {channel_id} dengan semua bot yang tersedia. Channel ini akan dilewati.", "ERROR")
            continue # Lanjut ke channel ID berikutnya

        # Jika channel bisa diakses, minta pengaturan
        channel_settings, assigned_tokens_for_channel, assigned_bot_ids_for_channel = get_channel_settings_interactive(
            channel_id, c_name, s_name, valid_tokens_info # Berikan semua bot valid sebagai pilihan
        )

        if channel_settings and assigned_tokens_for_channel:
            channel_configs[channel_id] = {
                "name": c_name,
                "settings": channel_settings,
                "tokens": assigned_tokens_for_channel,
                "bot_ids": assigned_bot_ids_for_channel
            }
            log_message(f"Konfigurasi untuk channel [{c_name}] ({channel_id}) selesai.", "INFO")
        else:
             log_message(f"Konfigurasi untuk channel [{c_name}] ({channel_id}) dibatalkan atau gagal.", "WARNING")


    # 4. Jalankan Thread Manager untuk Setiap Channel yang Terkonfigurasi
    if not channel_configs:
        log_message("Tidak ada channel yang berhasil dikonfigurasi. Program berhenti.", "CRITICAL")
        exit()

    log_message("\n" + "="*30 + " MEMULAI SEMUA MANAGER CHANNEL " + "="*30, "INFO")
    for channel_id, config in channel_configs.items():
        log_message(f"Menyiapkan thread untuk channel [{config['name']}] ({channel_id})...", "INFO")
        thread = threading.Thread(
            target=auto_reply_channel_manager,
            args=(
                channel_id,
                config['name'],
                config['settings'],
                config['tokens'],
                config['bot_ids']
            ),
            daemon=True # Set daemon=True agar thread otomatis berhenti jika main thread selesai
        )
        threads.append(thread)
        thread.start()
        time.sleep(0.5) # Beri jeda sedikit antar start thread

    log_message(f"Semua {len(threads)} thread manager channel telah dimulai.", "SUCCESS")
    log_message("Bot(s) sekarang aktif. Tekan Ctrl+C untuk menghentikan.", "INFO")

    # 5. Jaga Program Tetap Berjalan
    try:
        while True:
            time.sleep(60) # Cek setiap menit
    except KeyboardInterrupt:
        log_message("\nCtrl+C terdeteksi. Menghentikan program...", "INFO")
        log_message("Semua thread manager akan berhenti. Selamat tinggal!", "INFO")
        print(Style.RESET_ALL) # Reset warna terminal
        exit()

