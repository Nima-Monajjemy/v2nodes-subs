import os, re, subprocess, tempfile, json, time, requests, shutil, base64, sqlite3
from urllib.parse import urlparse, parse_qs
import cloudscraper

# ---------------- تنظیمات ----------------
SOURCES = {
    "in_configs.txt": "https://www.v2nodes.com/subscriptions/country/in/?key=7AB5E4B48A3F732",
    "us_configs.txt": "https://www.v2nodes.com/subscriptions/country/us/?key=7AB5E4B48A3F732",
    "sg_configs.txt": "https://www.v2nodes.com/subscriptions/country/sg/?key=7AB5E4B48A3F73",
    "fr_configs.txt": "https://www.v2nodes.com/subscriptions/country/fr/?key=7AB5E4B48A3F732"
}

DB_FILE = "tested_configs.db"
TEST_URL = "http://www.gstatic.com/generate_204"
TEST_TIMEOUT = 1.5
MAX_TEST = 6000

EXPIRY_HOURS = 12
MAX_RETEST = 40
MAX_FAILURES = 2
PURGE_INTERVAL = 3  # هر 3 بار اجرای معمولی، یک بار کل لیست پالایش می‌شود

# ---------------- توابع پایگاه داده ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tested_configs
                 (config_hash TEXT PRIMARY KEY, real_delay REAL, last_test_time REAL, fail_count INTEGER DEFAULT 0, source TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS run_counter
                 (id INTEGER PRIMARY KEY, counter INTEGER)''')
    c.execute("INSERT OR IGNORE INTO run_counter (id, counter) VALUES (1, 0)")
    conn.commit()
    conn.close()

def get_run_counter():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT counter FROM run_counter WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def set_run_counter(value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE run_counter SET counter=? WHERE id=1", (value,))
    conn.commit()
    conn.close()

def is_config_tested(config_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT real_delay FROM tested_configs WHERE config_hash=?", (config_hash,))
    res = c.fetchone()
    conn.close()
    return res is not None

def save_tested_config(config_hash, delay, source, fail=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO tested_configs (config_hash, real_delay, last_test_time, fail_count, source) VALUES (?, ?, ?, ?, ?)", (config_hash, delay, time.time(), fail, source))
    conn.commit()
    conn.close()

def delete_config(config_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM tested_configs WHERE config_hash=?", (config_hash,))
    conn.commit()
    conn.close()

def increment_fail_count(config_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE tested_configs SET fail_count = fail_count + 1, last_test_time = ? WHERE config_hash=?", (time.time(), config_hash))
    conn.commit()
    conn.close()

def get_fail_count(config_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT fail_count FROM tested_configs WHERE config_hash=?", (config_hash,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_cached_configs(source):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT config_hash, real_delay FROM tested_configs WHERE source=? ORDER BY real_delay ASC", (source,))
    res = c.fetchall()
    conn.close()
    return res

def get_expired_configs(limit, source):
    cutoff = time.time() - EXPIRY_HOURS * 3600
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT config_hash, last_test_time, fail_count FROM tested_configs WHERE last_test_time < ? AND source=? ORDER BY last_test_time ASC LIMIT ?", (cutoff, source, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# ---------------- دریافت کانفیگ‌ها از وب ----------------
def fetch_configs(url):
    print(f"🌐 استخراج از: {url}")
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    try:
        resp = scraper.get(url, timeout=20)
        if resp.status_code != 200: return []
        text = resp.text.strip()
        try:
            decoded = base64.b64decode(text).decode('utf-8')
            if any(p in decoded for p in ["vless://", "vmess://", "trojan://", "ss://"]): text = decoded
        except: pass
        configs = list(set(re.findall(r'(?:vless|vmess|trojan|ss)://[^\s<"\'\n]+', text)))
        print(f"✅ {len(configs)} کانفیگ یکتا یافت شد.")
        return configs
    except Exception as e:
        print(f"⚠️ خطای ارتباط: {e}")
        return []

# ---------------- تست Xray ----------------
def download_xray():
    url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    resp = requests.get(url, stream=True, timeout=30)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        for chunk in resp.iter_content(chunk_size=8192): tmp.write(chunk)
        zip_path = tmp.name
    xray_dir = tempfile.mkdtemp()
    shutil.unpack_archive(zip_path, xray_dir)
    xray_bin = os.path.join(xray_dir, "xray")
    os.chmod(xray_bin, 0o755)
    return xray_bin

def parse_link_to_outbound(link):
    try:
        if link.startswith("vmess://"):
            b64 = link[8:]
            padded = b64 + '=' * (4 - len(b64) % 4) if len(b64) % 4 != 0 else b64
            decoded = json.loads(base64.b64decode(padded).decode('utf-8'))
            out = {"protocol": "vmess", "settings": {"vnext": [{"address": decoded["add"], "port": int(decoded["port"]), "users": [{"id": decoded["id"], "security": decoded.get("scy", "auto")}]}]}, "streamSettings": {"network": decoded.get("net", "tcp")}}
            if decoded.get("net") == "ws": out["streamSettings"]["wsSettings"] = {"path": decoded.get("path", "/"), "headers": {"Host": decoded.get("host", decoded["add"])} if decoded.get("host") else {}}
            if decoded.get("tls") == "tls": out["streamSettings"]["security"] = "tls"; out["streamSettings"]["tlsSettings"] = {"serverName": decoded.get("sni", decoded["add"])}
            return out
        elif link.startswith("ss://"):
            parsed = urlparse(link)
            userinfo = parsed.username
            if not userinfo: return None
            try:
                padded = userinfo + '=' * (4 - len(userinfo) % 4) if len(userinfo) % 4 != 0 else userinfo
                decoded = base64.b64decode(padded).decode('utf-8')
                method, password = decoded.split(':', 1) if ':' in decoded else ("aes-256-gcm", decoded)
            except:
                method, password = userinfo.split(':', 1) if ':' in userinfo else ("aes-256-gcm", userinfo)
            return {"protocol": "shadowsocks", "settings": {"servers": [{"address": parsed.hostname, "port": int(parsed.port), "method": method, "password": password}]}, "streamSettings": {"network": "tcp", "security": "none"}}
        elif link.startswith("vless://") or link.startswith("trojan://"):
            parsed = urlparse(link)
            if link.startswith("vless://"):
                protocol, settings = "vless", {"vnext": [{"address": parsed.hostname, "port": parsed.port, "users": [{"id": parsed.username, "encryption": "none", "flow": ""}]}]}
            else:
                protocol, settings = "trojan", {"servers": [{"address": parsed.hostname, "port": parsed.port, "password": parsed.username}]}
            params = parse_qs(parsed.query)
            get_p = lambda k, d="": params.get(k, [d])[0]
            net, sec = get_p("type", "tcp"), get_p("security", "none")
            if protocol == "vless" and get_p("flow"): settings["vnext"][0]["users"][0]["flow"] = get_p("flow")
            out = {"protocol": protocol, "settings": settings, "streamSettings": {"network": net, "security": sec}}
            if net == "ws": out["streamSettings"]["wsSettings"] = {"path": get_p("path", "/"), "headers": {"Host": get_p("host")} if get_p("host") else {}}
            elif net == "tcp" and get_p("headerType") == "http": out["streamSettings"]["tcpSettings"] = {"header": {"type": "http", "request": {"headers": {"Host": get_p("host")} if get_p("host") else {}, "path": get_p("path", "/")}}}
            elif net == "grpc": out["streamSettings"]["grpcSettings"] = {"serviceName": get_p("path", "/").lstrip("/"), "multiMode": False}
            if sec == "tls": out["streamSettings"]["tlsSettings"] = {"serverName": get_p("sni", parsed.hostname), "allowInsecure": get_p("allowInsecure", "0") == "1", **({"fingerprint": get_p("fp")} if get_p("fp") else {}), **({"alpn": get_p("alpn").split(",")} if get_p("alpn") else {})}
            elif sec == "reality": out["streamSettings"]["realitySettings"] = {"serverName": get_p("sni", parsed.hostname), "fingerprint": get_p("fp", "chrome"), "publicKey": get_p("pbk"), "shortId": get_p("sid"), "spiderX": get_p("spx")}
            return out
    except: return None

def test_single_config(xray_bin, link, timeout=TEST_TIMEOUT):
    out = parse_link_to_outbound(link)
    if not out: return False, 999999
    config_path = tempfile.mktemp(suffix=".json")
    with open(config_path, "w") as f: json.dump({"inbounds": [{"listen": "127.0.0.1", "port": 10808, "protocol": "socks", "settings": {"udp": False, "auth": "noauth"}}], "outbounds": [out]}, f)
    proc = None
    try:
        proc = subprocess.Popen([xray_bin, "run", "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.5)
        res = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{time_total}", "--socks5-hostname", "127.0.0.1:10808", TEST_URL, "--connect-timeout", str(timeout)], capture_output=True, text=True, timeout=timeout + 5)
        if res.returncode == 0 and res.stdout.strip() and (latency := float(res.stdout.strip()) * 1000) < timeout * 1000: return True, latency
        return False, 999999
    except: return False, 999999
    finally:
        if proc: proc.terminate(); (proc.wait(3) if hasattr(proc, 'wait') else proc.kill())
        try: os.unlink(config_path)
        except: pass

def process_source(source_name, raw_configs, xray_bin):
    results = {}
    total = len(raw_configs)
    cached = get_cached_configs(source_name)
    for h, d in cached: results[h] = d
    print(f"📊 {len(cached)} کانفیگ از قبل کش‌شده یافت شد.")
    
    # تست کانفیگ‌های جدید
    for i, link in enumerate(raw_configs, 1):
        if is_config_tested(link): continue
        ok, d = test_single_config(xray_bin, link)
        short = link[:50] + "..."
        if ok: 
            results[link] = d
            save_tested_config(link, d, source_name)
            print(f"[{i}/{total}] ✅ {short} -> {d:.0f}ms")
        else: 
            print(f"[{i}/{total}] ❌ {short}")
            
    # بررسی مجدد کانفیگ‌های قدیمیِ همین سورس
    if expired := get_expired_configs(MAX_RETEST, source_name):
        print(f"\n🔁 بازبینی {len(expired)} کانفیگ قدیمی...")
        for h, _, _ in expired:
            ok, d = test_single_config(xray_bin, h)
            if ok: 
                results[h] = d
                save_tested_config(h, d, source_name)
            else: 
                increment_fail_count(h)
                if get_fail_count(h) >= MAX_FAILURES: 
                    delete_config(h)
                    results.pop(h, None)
                    print(f"   🗑️ کانفیگ مرده حذف شد.")
                    
    return [l for l, _ in sorted(results.items(), key=lambda x: x[1])]

def save_to_file(valid_configs, filename):
    if not valid_configs: return
    content = "\n".join(valid_configs)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(encoded)

def perform_purge():
    print("🧹 شروع عملیات پالایش کامل لیست‌ها...")
    xray_bin = download_xray()
    for filename in SOURCES.keys():
        if not os.path.exists(filename): continue
        try:
            links = set(base64.b64decode(open(filename).read().strip()).decode().split())
            results = {}
            for l in links:
                ok, d = test_single_config(xray_bin, l)
                if ok: 
                    results[l] = d
                    save_tested_config(l, d, filename)
                else: 
                    delete_config(l)
            save_to_file([l for l, _ in sorted(results.items(), key=lambda x: x[1])], filename)
            print(f"🧹 لیست {filename} پالایش شد. (تعداد سالم: {len(results)})")
        except: pass
    set_run_counter(0)
    shutil.rmtree(os.path.dirname(xray_bin), ignore_errors=True)

# ---------------- اجرا ----------------
if __name__ == "__main__":
    init_db()
    counter = get_run_counter()
    
    if counter >= PURGE_INTERVAL:
        perform_purge()
        exit(0)
        
    print(f"🔄 شمارنده اجرا: {counter}/{PURGE_INTERVAL} (حالت استخراج و تست تدریجی)\n")
    print("📥 دانلود موتور Xray-core...")
    xray_bin = download_xray()
    
    for filename, url in SOURCES.items():
        print(f"\n{'='*40}\n🚀 پردازش: {filename}\n{'='*40}")
        raw = fetch_configs(url)
        if not raw: 
            print("⚠️ کانفیگ جدیدی یافت نشد.")
            # حتی اگر کانفیگ جدید نباشد، کانفیگ‌های قدیمی در دیتابیس را در فایل نگه می‌داریم
            cached = [h for h, _ in get_cached_configs(filename)]
            if cached: save_to_file(cached, filename)
            continue
            
        valid = process_source(filename, raw[:MAX_TEST], xray_bin)
        save_to_file(valid, filename)
        print(f"📦 ذخیره نهایی: {len(valid)} کانفیگ سالم در {filename}")
        
    set_run_counter(counter + 1)
    shutil.rmtree(os.path.dirname(xray_bin), ignore_errors=True)
    print("\n🏁 پردازش تمام شد. در حال کامیت به گیت‌هاب...")
