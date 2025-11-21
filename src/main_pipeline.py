import os
import yaml
import feedparser
import requests
import json
import re
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
# High-quality fallback images if the feed is missing one
FALLBACK_IMGS = {
    "Tech": "https://images.unsplash.com/photo-1550009158-9ebf69173e03?w=800&q=80",
    "Home": "https://images.unsplash.com/photo-1584622050111-993a426fbf0a?w=800&q=80",
    "Audio": "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800&q=80",
    "Default": "https://images.unsplash.com/photo-1526738549149-8e07eca6c147?w=800&q=80"
}

# --- HELPER: EXTRACT IMAGE FROM FEED ---
def extract_image(entry):
    """Finds the largest image available in the feed entry."""
    content = str(entry.get('summary', '')) + str(entry.get('content', ''))
    
    # Try to find the deal image
    match = re.search(r'<img[^>]+src="([^">]+)"', content)
    if match:
        return match.group(1)
    return None

# --- HELPER: FIND AMAZON ID (ASIN) ---
def find_asin(text):
    """Extracts the 10-character Amazon ID (e.g. B08XYZ...)"""
    if not text: return None
    # Patterns for various Amazon URL structures
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'amazon\.com.*/([A-Z0-9]{10})',
        r'%2Fdp%2F([A-Z0-9]{10})' # Encoded URL
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(1)
    return None

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching Amazon-Only Inventory...")
    clean_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            
            for entry in feed.entries:
                # We scan the Link and Description for an Amazon ID
                blob = str(entry.link) + str(entry.get('summary', ''))
                asin = find_asin(blob)
                
                if asin:
                    # WE HAVE A MATCH.
                    # Build a direct money link.
                    money_link = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                    img_url = extract_image(entry)
                    
                    clean_deals.append({
                        "title": entry.title,
                        "link": money_link,
                        "img": img_url,
                        "asin": asin,
                        "category": "Tech" if "tech" in source['name'].lower() else "Home"
                    })
        except Exception as e:
            print(f"Feed Error {source['name']}: {e}")
            
    # Deduplicate (Don't show the same product twice)
    unique_deals = {d['asin']:d for d in clean_deals}.values()
    
    # Return top 12
    print(f"Found {len(unique_deals)} valid Amazon deals.")
    return list(unique_deals)[:12]

# --- 2. AI ENRICHMENT ---
def ai_enrich(deals):
    print("AI Analyst working...")
    enriched = []
    for deal in deals:
        try:
            prompt = f"""
            You are a shopping assistant. Write for this Amazon deal: '{deal['title']}'.
            Output JSON:
            - 'headline': A specific product name (e.g. "Sony WH-1000XM5 Headphones").
            - 'why_good': A 6-word punchy reason to buy (e.g. "Lowest price in 30 days").
            - 'discount_guess': Estimate the discount (e.g. "40% OFF").
            """
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)
            deal.update(data)
            
            # Fallback Image Logic
            if not deal['img']:
                deal['img'] = FALLBACK_IMGS.get(deal['category'], FALLBACK_IMGS['Default'])
                
            enriched.append(deal)
        except:
            # Basic Fallback
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Limited time Amazon deal."
            deal['discount_guess'] = "DEAL"
            if not deal.get('img'): deal['img'] = FALLBACK_IMGS['Default']
            enriched.append(deal)
    return enriched

# --- 3. GENERATE WEBSITE ---
def generate_site(deals):
    print("Building Dashboard...")
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CircuitBreaker | AI Amazon Finder</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #38bdf8; --amazon: #ff9900; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
            
            /* Navbar */
            .nav {{ padding: 20px; display: flex; justify-content: center; border-bottom: 1px solid #334155; }}
            .logo {{ font-size: 1.5rem; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            
            /* Hero */
            .hero {{ text-align: center; padding: 60px 20px; }}
            h1 {{ font-size: 2.5rem; margin-bottom: 10px; }}
            .subtitle {{ color: #94a3b8; font-size: 1.1rem; max-width: 600px; margin: 0 auto; }}
            
            /* Grid */
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 25px; }}
            
            /* Cards */
            .card {{ background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid #334155; transition: transform 0.2s; position: relative; }}
            .card:hover {{ transform: translateY(-5px); border-color: var(--accent); }}
            
            .badge {{ position: absolute; top: 10px; left: 10px; background: var(--accent); color: #0f172a; padding: 4px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: bold; }}
            
            .card-img {{ width: 100%; height: 180px; object-fit: cover; background: #020617; }}
            .card-body {{ padding: 15px; display: flex; flex-direction: column; height: 140px; }}
            
            .headline {{ font-size: 1.1rem; font-weight: 600; margin: 0 0 10px 0; line-height: 1.3; flex-grow: 1; }}
            .why {{ color: #cbd5e1; font-size: 0.9rem; margin-bottom: 15px; }}
            
            .btn {{ background: var(--amazon); color: #000; text-decoration: none; padding: 10px; border-radius: 6px; text-align: center; font-weight: bold; display: block; transition: opacity 0.2s; }}
            .btn:hover {{ opacity: 0.9; }}
            
            footer {{ text-align: center; margin-top: 60px; padding: 40px; color: #64748b; border-top: 1px solid #334155; font-size: 0.8rem; }}
        </style>
    </head>
    <body>
        <div class="nav">
            <div class="logo">⚡ CircuitBreaker</div>
        </div>
        
        <div class="hero">
            <h1>AI-Powered Deal Hunter</h1>
            <p class="subtitle">Our AI scans thousands of price drops to find the best Amazon deals for you automatically.</p>
        </div>
        
        <div class="container">
            <div class="grid">
    """
    
    if not deals:
        html += "<p style='grid-column: 1/-1; text-align: center;'>Scanning Amazon... Check back in 1 hour.</p>"
    
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
            <p>CircuitBreaker is a participant in the Amazon Services LLC Associates Program.<br>
            We earn commissions from qualifying purchases.</p>
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
