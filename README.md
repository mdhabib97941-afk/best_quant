# 🏛️ TITAN INSTITUTIONAL QUANT WEB DASHBOARD
### (Live Whale Radar & Inflow Dump/Pump Countdown)

স্বাগতম! এটি **Titan Quant System**-এর অফিসিয়াল ও সম্পূর্ণ আল্ট্রা-ক্লিন (Ultra-Clean) ওয়েব সংস্করণ। এখানে কোনো বাড়তি টেস্ট ফাইল, পুরনো ব্যাকটেস্ট বা রিসার্চ ড্রাফট নেই — শুধুমাত্র লাইভ ওয়েবসাইট এবং ব্যাকএন্ড অ্যালগো ইঞ্জিনগুলো সুন্দরভাবে সাজানো রয়েছে।

---

## 📂 এই ফোল্ডারের ফাইল তালিকা (Total: 32 Clean Files)

```
Titan_Web_Live/
│
├── 🚀 app.py                        <-- মাস্টার ক্লাউড সার্ভার রানার (Render & Local)
├── 📄 render.yaml                   <-- Render.com ১-ক্লিক অটো কনফিগারেশন
├── 📄 Procfile                      <-- ক্লাউড প্রসেস ফাইল (web: python app.py)
├── 📄 requirements.txt              <-- মাত্র ৩টি লাইব্রেরি (requests, websockets, urllib3)
├── 📄 .gitignore                    <-- ক্যাশ ও টেম্পোরারি ফাইল ক্লিনার
├── 📄 .env.example                  <-- এনভায়রনমেন্ট ভেরিয়েবল টেমপ্লেট
├── 📄 README.md                     <-- এই গাইড
│
└── 📁 core/                         <-- মূল ওয়েবসাইট ও হোয়েল রাডার ইঞ্জিন
    ├── quant_dashboard_server.py    (মূল ওয়েবসাইট ও ইন্টারঅ্যাক্টিভ এইচটিএমএল ড্যাশবোর্ড)
    ├── whale_smart_tracker.py       (হোয়েল পজিশন ও ট্র্যাপ ট্র্যাকার)
    ├── coinbase_institutional_radar.py (কয়েনবেজ প্রিমিয়াম ও স্পট ভেটো ইঞ্জিন)
    ├── iceberg_order_engine.py      (লাইভ আইসবার্গ বায়ার/সেলার পাওয়ার ডিটেক্টর)
    ├── dragonfly_titan_brain.py     (L2/L3 মাইক্রোস্ট্রাকচার ও ড্রাগনফ্লাই গেট ইঞ্জিন)
    ├── short_squeeze_sentinel.py    (শর্ট স্কুইজ রেডার)
    ├── long_squeeze_sentinel.py     (লং লিকুইডেশন রেডার)
    ├── telegram_daemon_loop.py      (টেলিগ্রাম অ্যালার্ট লুপ)
    ├── telegram_day_unlock_trader.py(টেলিগ্রাম সেটআপ সেন্ডার)
    ├── whale_lifecycle_sentinel.py  (হোয়েল লাইফসাইকেল সেন্টিনেল)
    └── ... (কোর ডাটাবেস ও স্টেট ফাইলসমূহ)
```

---

## 🚀 GitHub & Render.com হোস্টিং গাইড (২ মিনিটে লাইভ)

### ধাপ ১: GitHub-এ আপলোড
1. [GitHub.com](https://github.com)-এ গিয়ে একটি **New Repository** তৈরি করুন (যেমন: `titan-web-live`)।
2. আপনার কম্পিউটারের টার্মিনালে এই কমান্ডগুলো রান করুন:
   ```bash
   cd "C:\Users\Ashraf\.gemini\antigravity\scratch\Titan_Web_Live"
   git init
   git add .
   git commit -m "feat: ultra-clean titan web dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/titan-web-live.git
   git push -u origin main
   ```
   *(অথবা GitHub Desktop দিয়ে `Titan_Web_Live` ফোল্ডারটি অ্যাড করে Push করুন)*।

---

### ধাপ ২: Render.com-এ ২৪/৭ ফ্রিতে চালু করা
1. [Render.com](https://render.com)-এ লগইন করে **"New +" ➔ "Web Service"** সিলেক্ট করুন।
2. আপনার তৈরি করা `titan-web-live` রিপোজিটরিটি সিলেক্ট করুন।
3. সেটিংসগুলো মিলিয়ে নিন:
   * **Name:** `titan-web-live`
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python app.py`
   * **Instance Type:** `Free` ($0/month)
4. **Environment Variables (টেলিগ্রাম অ্যালার্টের জন্য):**
   * `ENABLE_DRAGONFLY` = `true`
   * `ENABLE_TELEGRAM` = `true`
   * `TELEGRAM_BOT_TOKEN` = `8918704289:AAFg33hZSpa0XrUTFah4TakDBx6ryrAHHgU`
   * `TELEGRAM_CHAT_ID` = `7736288854`
5. **"Deploy Web Service"** বাটনে ক্লিক করুন!

🎉 মাত্র ২ মিনিটের মধ্যে আপনার পার্সোনাল ওয়েবসাইট লিঙ্ক লাইভ হয়ে যাবে:  
🌐 **`https://titan-web-live.onrender.com`**
