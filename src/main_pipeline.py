import os
import yaml
import feedparser
import requests
import json
import re
import urllib.parse
from datetime import datetime
from openai import OpenAI

# --- CONFIG ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
AMAZON_TAG = "circuitbrea0c-20"

# --- ASSETS ---
FALLBACK_IMGS = {
    "Tech": "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=800&q=80",
    "Home": "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&q=80",
    "Audio": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800&q=80",
    "Default": "https://images.unsplash.com/photo-1526738549149-8e07eca6c147?w=800&q=80"
}

# --- HELPER: EXTRACT IMAGE ---
def extract_image(entry):
    content = str(entry.get('summary', '')) + str(entry.get('content', ''))
    match = re.search(r'<img[^>]+src="([^">]+)"', content)
    if match: return match.group(1)
    return None

# --- HELPER: FIND ASIN ---
def find_asin(text):
    if not text: return None
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'amazon\.com.*/([A-Z0-9]{10})',
        r'%2Fdp%2F([A-Z0-9]{10})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(1)
    return None

# --- HELPER: GENERATE SMART SEARCH LINK ---
def create_amazon_search_link(title):
    """
    Cleans the title and creates an Amazon Search URL with your Affiliate Tag.
    """
    # Remove junk words to make the search better
    junk = ["sale", "deal", "price", "drop", "off", "coupon", "amazon", "at", "for", "only", "$", "lowest"]
    words = title.lower().split()
    clean_words = [w for w in words if w not in junk and not w.isdigit()]
    
    # Take the first 5 meaningful words (e.g., "Sony WH-1000XM5 Headphones Black")
    search_query = " ".join(clean_words[:5])
    encoded_query = urllib.parse.quote(search_query)
    
    return f"https://www.amazon.com/s?k={encoded_query}&tag={AMAZON_TAG}"

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching deals with Fallback Strategy...")
    raw_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            
            for entry in feed.entries[:6]: # Check top 6 from each source
                
                # 1. Try to find Direct ASIN
                blob = str(entry.link) + str(entry.get('summary', ''))
                asin = find_asin(blob)
                
                if asin:
                    # BEST CASE: Direct Product Link
                    final_link = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                    match_type = "Direct"
                else:
                    # FALLBACK: Search Link
                    final_link = create_amazon_search_link(entry.title)
                    match_type = "Search"
                
                img_url = extract_image(entry)
                
                raw_deals.append({
                    "title": entry.title,
                    "link": final_link,
                    "img": img_url,
                    "type": match_type,
                    "source": source['name']
                })
                
        except Exception as e:
            print(f"Error reading {source['name']}: {e}")
            
    # Deduplicate
    seen = set()
    unique = []
    for d in raw_deals:
        if d['title'] not in seen:
            seen.add(d['title'])
            unique.append(d)
    
    # Ensure we have plenty of deals (up to 18)
    print(f"Found {len(unique)} deals total.")
    return list(unique)[:18]

# --- 2. AI ENRICHMENT ---
def ai_enrich(deals):
    print("AI Rewriting...")
    enriched = []
    for deal in deals:
        try:
            prompt = f"""
            Analyze deal: '{deal['title']}'.
            JSON Output:
            - 'headline': Clean Product Name (max 6 words).
            - 'why_good': 6-word benefit.
            - 'discount_guess': Estimate discount (e.g. "Sale").
            - 'category': Tech, Home, or Audio.
            """
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)
            deal.update(data)
            
            # Assign Fallback Image if missing
            if not deal['img']:
                deal['img'] = FALLBACK_IMGS.get(deal.get('category'), FALLBACK_IMGS['Default'])
                
            enriched.append(deal)
        except:
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Check price on Amazon."
            deal['discount_guess'] = "DEAL"
            deal['category'] = "Tech"
            if not deal.get('img'): deal['img'] = FALLBACK_IMGS['Default']
            enriched.append(deal)
    return enriched

# --- 3. GENERATE WEBSITE ---
def generate_site(deals):
    print("Building Website...")
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CircuitBreaker | AI Deal Hunter</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #38bdf8; --amazon: #f59e0b; }}
            body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
            .nav {{ padding: 20px; text-align: center; border-bottom: 1px solid #334155; }}
            .logo {{ font-size: 1.5rem; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            
            .hero {{ text-align: center; padding: 60px 20px; background: radial-gradient(circle at top, #1e293b 0%, #0f172a 100%); }}
            h1 {{ font-size: 2.5rem; margin-bottom: 10px; }}
            .subtitle {{ color: #94a3b8; font-size: 1.1rem; max-width: 600px; margin: 0 auto; }}
            
            .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 25px; }}
            
            .card {{ background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid #334155; transition: transform 0.2s; position: relative; display: flex; flex-direction: column; }}
            .card:hover {{ transform: translateY(-5px); border-color: var(--accent); }}
            
            .badge {{ position: absolute; top: 10px; left: 10px; background: var(--accent); color: #0f172a; padding: 4px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: bold; }}
            
            .card-img {{ width: 100%; height: 180px; object-fit: cover; background: #020617; }}
            .card-body {{ padding: 15px; display: flex; flex-direction: column; flex-grow: 1; }}
            
            .headline {{ font-size: 1.1rem; font-weight: 600; margin: 0 0 10px 0; line-height: 1.3; }}
            .why {{ color: #cbd5e1; font-size: 0.9rem; margin-bottom: 15px; flex-grow: 1; }}
            
            .btn {{ background: var(--amazon); color: #0f172a; text-decoration: none; padding: 10px; border-radius: 6px; text-align: center; font-weight: bold; display: block; transition: opacity 0.2s; }}
            .btn:hover {{ opacity: 0.9; }}
            
            footer {{ text-align: center; margin-top: 60px; padding: 40px; color: #64748b; border-top: 1px solid #334155; font-size: 0.8rem; }}
        </style>
    </head>
    <body>
        <div class="nav"><div class="logo">⚡ CircuitBreaker</div></div>
        <div class="hero">
            <h1>AI-Powered Deal Hunter</h1>
            <p class="subtitle">Let AI search the web for you to find the best Amazon deals.</p>
        </div>
        
        <div class="container">
            <div class="grid">
    """
    
    if not deals:
        html += "<p style='grid-column: 1/-1; text-align: center;'>System maintenance. Checking feeds...</p>"
        
    for deal in deals:
        html += f"""
        <div class="card">
            <div class="badge">{deal['discount_guess']}</div>
            <img src="{deal['img']}" class="card-img" loading="lazy">
            <div class="card-body">
                <div class="headline">{deal['headline']}</div>
                <div class="why">"{deal['why_good']}"</div>
                <a href="{deal['link']}" class="btn" target="_blank">View on Amazon &rarr;</a>
            </div>
        </div>
        """
        
    html += """
            </div>
        </div>
        <footer>
            <p>CircuitBreaker is a participant in the Amazon Services LLC Associates Program.</p>
        </footer>
    </body>
    </html>
    """
    
    with open("index.html", "w") as f:
        f.write(html)
    print("Website generated.")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        final = ai_enrich(raw)
        generate_site(final)
    else:
        generate_site([])
