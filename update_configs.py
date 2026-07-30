import os, re, base64, subprocess
import cloudscraper

# ---------------- تنظیمات منابع ----------------
# دیکشنری شامل نام فایل خروجی و لینک مربوط به آن
SOURCES = {
    "in_configs.txt": "https://www.v2nodes.com/subscriptions/country/in/?key=7AB5E4B48A3F732",
    "us_configs.txt": "https://www.v2nodes.com/subscriptions/country/us/?key=7AB5E4B48A3F732",
    "sg_configs.txt": "https://www.v2nodes.com/subscriptions/country/sg/?key=7AB5E4B48A3F73",
    "fr_configs.txt": "https://www.v2nodes.com/subscriptions/country/fr/?key=7AB5E4B48A3F732"
}

# ---------------- توابع استخراج ----------------
def fetch_configs(url):
    print(f"🌐 در حال دریافت از: {url}")
    # استفاده از cloudscraper برای عبور از کلودفلر
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    
    try:
        resp = scraper.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"⚠️ خطا در دریافت (کد {resp.status_code})")
            return []
            
        text = resp.text.strip()
        
        # تلاش برای دیکد کردن Base64 (زیرا لینک‌های سابسکریپشن معمولاً انکود شده هستند)
        try:
            decoded_text = base64.b64decode(text).decode('utf-8')
            # اگر پس از دیکد شدن، ساختار کانفیگ‌ها در آن پیدا شد، از متن دیکد شده استفاده می‌کنیم
            if any(p in decoded_text for p in ["vless://", "vmess://", "trojan://", "ss://"]):
                text = decoded_text
        except Exception:
            pass # اگر دیکد نشد یا خطا داد، از همان متن خام اولیه استفاده می‌کنیم
            
        # استخراج دقیق لینک‌ها
        configs = re.findall(r'(?:vless|vmess|trojan|ss)://[^\s<"\'\n]+', text)
        
        # حذف موارد تکراری
        configs = list(set(configs))
        print(f"✅ {len(configs)} کانفیگ استخراج شد.")
        return configs
        
    except Exception as e:
        print(f"⚠️ خطای ارتباط: {e}")
        return []

# ---------------- ذخیره‌سازی فایل‌ها ----------------
def save_to_file(configs, filename):
    if not configs:
        return
    # تبدیل مجدد لیست کانفیگ‌ها به فرمت استاندارد Base64 برای سابسکریپشن کلاینت‌ها
    content = "\n".join(configs)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(encoded)

# ---------------- ابزار Git ----------------
def git_commit_all():
    print("\n🔄 در حال ثبت تغییرات در گیت‌هاب...")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    
    # اضافه کردن فقط فایل‌هایی که با موفقیت ساخته شده‌اند
    for f in SOURCES.keys():
        if os.path.exists(f): 
            subprocess.run(["git", "add", f], check=True)
            
    # بررسی اینکه آیا اصلاً تغییری رخ داده است؟
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if result.returncode == 0: 
        print("   ↳ بدون تغییر جدید، commit انجام نشد.")
        return
        
    subprocess.run(["git", "commit", "-m", "🔄 Update v2nodes subscriptions"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    print("   ↳ تغییرات با موفقیت در مخزن ثبت شد.")

# ---------------- اجرای اصلی برنامه ----------------
if __name__ == "__main__":
    print("🚀 شروع فرآیند استخراج...\n")
    
    for filename, url in SOURCES.items():
        configs = fetch_configs(url)
        if configs:
            save_to_file(configs, filename)
            print(f"📦 کانفیگ‌ها در فایل {filename} ذخیره شدند.\n")
        else:
            print(f"⚠️ برای {filename} هیچ دیتایی ثبت نشد.\n")
            
    git_commit_all()
    print("🏁 پایان.")
