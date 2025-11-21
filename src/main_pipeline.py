import os
import yaml
import feedparser
import requests
import json
import time
from datetime import datetime
from openai import OpenAI
from bs4 import BeautifulSoup

# --- SETUP ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
BEEHIIV_API_KEY = os.environ.get("BEEHIIV_API_KEY")
BEEHIIV_PUB_ID = os.environ.get("BEEHIIV_PUB_ID")

# --- STEP 1: INGEST ---
def fetch_deals():
    print("--- Step 1: Fetching Deals ---")
    raw_deals = []
    for source in config['sources']:
        print(f"Checking {source['name']}...")
        try:
            feed = feedparser.parse(source['url'])
            for entry in feed.entries[:10]: # Check top 10 from each
                raw_deals.append({
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.get('summary', ''),
                    "source": source['name']
                })
        except Exception as e:
            print(f"Error fetching {source['name']}: {e}")
    print(f"Total raw deals found: {len(raw_deals)}")
    return raw_deals

# --- STEP 2: FILTER ---
def filter_deals(deals):
    print("--- Step 2: Filtering ---")
    filtered = []
    excludes = [x.lower() for x in config['filters']['keywords_exclude']]
    
    for deal in deals:
        title_lower = deal['title'].lower()
        if any(bad_word in title_lower for bad_word in excludes):
            continue
        filtered.append(deal)
        
    # Remove duplicates based on link
    unique_deals = {v['link']:v for v in filtered}.values()
    print(f"Deals after filtering: {len(unique_deals)}")
    return list(unique_deals)[:config['content']['deals_per_issue']]

# --- STEP 3: AI ENRICHMENT ---
def ai_rewrite(deals):
    print("--- Step 3: AI Writing ---")
    enriched = []
    for deal in deals:
        print(f"Rewriting: {deal['title']}...")
        prompt = f"""
        Act as an expert tech shopper. Rewrite this deal for the 'CircuitBreaker' newsletter.
        Original Title: {deal['title']}
        Original Link: {deal['link']}
        
        Output strictly Valid JSON with these keys:
        - "headline": A punchy, witty title (max 8 words).
        - "body": A 2-sentence explanation of why this is a good deal.
        - "cta": A short call to action (e.g. "Snag it now").
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={ "type": "json_object" }
            )
            content = json.loads(response.choices[0].message.content)
            deal.update(content)
            enriched.append(deal)
            time.sleep(1) # Avoid rate limits
        except Exception as e:
            print(f"AI Error: {e}")
            
    return enriched

# --- STEP 4: PUBLISH TO BEEHIIV ---
def publish_draft(deals):
    print("--- Step 4: Publishing to Beehiiv ---")
    
    # Build HTML
    date_str = datetime.now().strftime('%B %d, %Y')
    html_content = f"<p>Good morning. Here are the top tech drops for {date_str}.</p><hr>"
    
    for deal in deals:
        html_content += f"""
        <div style="margin-bottom: 25px;">
            <h2 style="margin-bottom: 5px;"><a href="{deal['link']}">{deal['headline']}</a></h2>
            <p style="margin-top: 0;">{deal['body']}</p>
            <p><strong><a href="{deal['link']}">{deal['cta']} &rarr;</a></strong></p>
        </div>
        """
    
    html_content += f"<hr><p><small>{config['footer_text']}</small></p>"

    url = f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts"
    headers = {
        "Authorization": f"Bearer {BEEHIIV_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "title": f"CircuitBreaker: {date_str}",
        "content": {
            "body": html_content,
            "thumbnail": "" 
        },
        "audience": "all",
        "platform": "both",
        "status": "draft" # Start as draft for safety
    }
    
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in [200, 201]:
        print("SUCCESS: Draft created in Beehiiv!")
    else:
        print(f"FAILED: Beehiiv API said: {resp.text}")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        selected = filter_deals(raw)
        if selected:
            final = ai_rewrite(selected)
            publish_draft(final)
        else:
            print("No deals passed the filter.")
    else:
        print("No raw deals found.")
