import os
import yaml
import feedparser
import requests
import json
import re
import time
from datetime import datetime
from openai import OpenAI
from bs4 import BeautifulSoup

# --- CONFIG ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- AFFILIATE SETTINGS ---
AMAZON_TAG = "circuitbrea0c-20" 

# --- HELPER: CLEAN AND BUILD AMAZON LINKS ---
def build_clean_amazon_url(dirty_url):
    """
    Extracts the ASIN (Product ID) and builds a perfect link.
    Returns None if no ASIN is found.
    """
    # Regex to find ASIN (starts with B0, 10 chars) or standard ISBN-10
    # Matches: /dp/B0..., /gp/product/B0...
    asin_match = re.search(r'/(?:dp|gp/product)/(B[A-Z0-9]{9}|[0-9]{10})', dirty_url)
    
    if asin_match:
        asin = asin_match.group(1)
        # Build the cleanest possible link
        return f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
    
    return None

# --- HELPER: SCRAPE SLICKDEALS FOR HIDDEN LINKS ---
def extract_amazon_url(slickdeals_url):
    """Visits the Slickdeals page and hunts for an Amazon ASIN."""
    print(f"  - Inspecting: {slickdeals_url[:40]}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml'
    }
    try:
        time.sleep(1.5) # Polite delay
        resp = requests.get(slickdeals_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.content, 'html.parser')
        
        # Look at every link on the page
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link['href']
            # If we find a link with an ASIN, we hit the jackpot
            clean_link = build_clean_amazon_url(href)
            if clean_link:
                print(f"    -> Found Product: {clean_link}")
                return clean_link
                
    except Exception as e:
        print(f"    -> Scrape warning: {e}")
    
    return None

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching deals...")
    raw_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:4]:
                raw_deals.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": source['name'],
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
        except Exception as e:
            print(f"Skipping {source['name']}: {e}")
    return raw_deals

# --- 2. FILTER ---
def filter_deals(deals):
    seen = set()
    unique = []
    for d in deals:
        if d['link'] not in seen:
            seen.add(d['link'])
            unique.append(d)
    return unique[:9] 

# --- 3. ENRICH & REWRITE ---
def ai_enrich(deals):
    print("Processing deals...")
    enriched = []
    
    for deal in deals:
        final_link = deal['link']
        is_amazon = False
        
        # STEP A: If it's Slickdeals, try to find the Amazon Product
        if "slickdeals.net" in deal['link']:
            amazon_link = extract_amazon_url(deal['link'])
            if amazon_link:
                final_link = amazon_link
                is_amazon = True
            else:
                # Safety Fallback: Use the original link if we can't find the product
                # This prevents 404s. It sends them to SD, but that's better than a broken page.
                final_link = deal['link']
                is_amazon = False
        
        deal['link'] = final_link
        
        # STEP B: AI Writing
        try:
            prompt = f"""
            Analyze this deal: '{deal['title']}'.
            Return JSON with:
            - 'headline': Short, punchy title (max 6 words).
            - 'why_good': One sentence reason to buy.
            - 'category': Tech, Home, or Audio.
            """
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)
            deal.update(data)
        except:
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Great price."
            deal['category'] = "Deal"
            
        # Button Text Logic
        if is_amazon:
            deal['btn_text'] = "Buy on Amazon"
        else:
            deal['btn_text'] = "View Deal" # Fallback for non-Amazon
            
        enriched.append(deal)
            
    return enriched

# --- 4. GENERATE WEBSITE ---
def generate_site(deals):
    print("Generating index.html...")
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CircuitBreaker | Daily Tech Drops</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --accent: #38bdf8; }}
            body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            header {{ text-align: center; padding: 60px 0; border-bottom: 1px solid #334155; margin-bottom: 40px; }}
            h1 {{ font-size: 3rem; margin: 0; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .date {{ color: #94a3b8; margin-top: 10px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 25px; }}
            .card {{ background: var(--card); padding: 25px; border-radius: 12px; border: 1px solid #334155; transition: transform 0.2s; }}
            .card:hover {{ transform: translateY(-5px); border-color: var(--accent); }}
            .tag {{ background: #0f172a; padding: 5px 10px; border-radius: 20px; font-size: 0.8rem; color: var(--accent); text-transform: uppercase; letter-spacing: 1px; }}
            .headline {{ font-size: 1.4rem; margin: 15px 0; font-weight: 700; color: white; text-decoration: none; display: block; }}
            .why {{ color: #94a3b8; line-height: 1.6; font-size: 0.95rem; }}
            .btn {{ display: inline-block; margin-top: 20px; background: var(--accent); color: #0f172a; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; width: 100%; text-align: center; box-sizing: border-box; }}
            footer {{ text-align: center; margin-top: 80px; color: #64748b; font-size: 0.9rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>⚡ CircuitBreaker</h1>
                <p class="date">Fresh Drops for {datetime.now().strftime("%B %d, %Y")}</p>
            </header>
            <div class="grid">
    """
    
    for deal in deals:
        html += f"""
        <div class="card">
            <span class="tag">{deal['category']}</span>
            <a href="{deal['link']}" class="headline" target="_blank">{deal['headline']}</a>
            <p class="why">{deal['why_good']}</p>
            <a href="{deal['link']}" class="btn" target="_blank">{deal['btn_text']} &rarr;</a>
        </div>
        """
        
    html += """
            </div>
            <footer>
                <p>Managed by AI. Affiliate links earn support.</p>
            </footer>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w") as f:
        f.write(html)
    print("Website generated.")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        filtered = filter_deals(raw)
        final = ai_enrich(filtered)
        generate_site(final)
