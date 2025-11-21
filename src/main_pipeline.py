import os
import yaml
import feedparser
import requests
import json
import time
import re
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

# --- HELPER: EXTRACT REAL AMAZON LINK ---
def extract_amazon_url(slickdeals_url):
    """Visits the Slickdeals page and finds the hidden Amazon link."""
    print(f"  - Digging for Amazon link in: {slickdeals_url[:40]}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    try:
        # Be polite to the server
        time.sleep(1) 
        resp = requests.get(slickdeals_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.content, 'html.parser')
        
        # Find all links
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link['href']
            # Look for Amazon links
            if "amazon.com" in href:
                # Sometimes SD wraps them, sometimes they are direct
                # We want the clean URL. 
                # If it's a redirect (slickdeals.net/?u2=...), we might just take the first one we find
                # But usually, the "See Deal" button is what we want.
                print(f"    -> Found Amazon Link!")
                return href
            
            # Check for amzn.to shortlinks
            if "amzn.to" in href:
                return href
                
    except Exception as e:
        print(f"    -> Failed to extract: {e}")
    
    return None

# --- HELPER: MONETIZE LINKS ---
def monetize_url(url):
    """Stamps the link with your ID."""
    if not url: return None
    
    if "amazon.com" in url:
        # Remove existing tags if any
        if "tag=" in url:
            url = re.sub(r'tag=[^&]+', f'tag={AMAZON_TAG}', url)
        elif "?" in url:
            url = url + f"&tag={AMAZON_TAG}"
        else:
            url = url + f"?tag={AMAZON_TAG}"
            
    return url

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching deals...")
    raw_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            # Get top 4
            for entry in feed.entries[:4]:
                raw_deals.append({
                    "title": entry.title,
                    "link": entry.link, # This starts as the Slickdeals link
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
        # STEP A: If it's Slickdeals, try to find the REAL link
        if "slickdeals.net" in deal['link']:
            real_link = extract_amazon_url(deal['link'])
            if real_link:
                # If we found an Amazon link, swap it!
                deal['link'] = real_link
            else:
                # If we couldn't find one, keep the SD link (better than nothing)
                pass
        
        # STEP B: Monetize whatever link we have
        deal['link'] = monetize_url(deal['link'])
        
        # STEP C: AI Writing
        try:
            prompt = f"""
            Analyze this deal: '{deal['title']}'.
            Return JSON with:
            - 'headline': Short title (max 6 words).
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
            enriched.append(deal)
        except Exception:
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Check price."
            deal['category'] = "Deal"
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
            <a href="{deal['link']}" class="btn" target="_blank">Get Deal on Amazon &rarr;</a>
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
