import os
import requests
import sys
import threading
import time
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from microservices.news_crawler_service import news_db

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
if OLLAMA_BASE_URL:
    OLLAMA_URL = OLLAMA_BASE_URL
else:
    OLLAMA_URL = "http://localhost:11434"

LLM_MODEL = "gemma2"

def query_vllm(prompt, system="You are a helpful assistant."):
    """Send a prompt to vLLM/Ollama for summarization."""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 1024
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/v1/chat/completions", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[Summarization Failed: {e}]"

def crawl_news_task_sync(job_id):
    job = news_db.get_job(job_id)
    if not job:
        return
        
    try:
        news_db.update_job_status(job_id, "Running", "Starting search...")
        
        # SEARCH
        keywords_list = [k.strip() for k in job['keywords'].split(",") if k.strip()]
        
        # map time_limit to google news format
        time_limit_map = {"d": "1d", "w": "7d", "m": "1m"}
        time_suffix = ""
        if job.get("time_limit") in time_limit_map:
            time_suffix = f" when:{time_limit_map[job['time_limit']]}"
        
        all_results = []
        import urllib.parse
        for kw in keywords_list:
            news_db.update_job_status(job_id, "Running", f"Searching for: {kw}...")
            try:
                # Delay to avoid immediate rate limit
                time.sleep(1)
                
                search_query = kw + time_suffix
                q = urllib.parse.quote_plus(search_query)
                rss_url = f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"
                
                res = requests.get(rss_url, timeout=10)
                soup = BeautifulSoup(res.content, 'xml')
                items = soup.find_all('item')[:10]
                
                for item in items:
                    title = item.title.text if item.title else "No Title"
                    link = item.link.text if item.link else ""
                    desc = item.description.text if item.description else title
                    
                    # Clean up HTML in description
                    desc_soup = BeautifulSoup(desc, 'html.parser')
                    clean_desc = desc_soup.get_text()
                    
                    all_results.append({
                        "title": title,
                        "url": link,
                        "body": clean_desc
                    })
            except Exception as e:
                print(f"Search error for '{kw}': {e}")
                        
        if not all_results:
            news_db.update_job_status(job_id, "Failed", "No results found or rate limited for all keywords.")
            return
            
        # Deduplicate by URL
        seen_urls = set()
        raw_results = []
        for r in all_results:
            url = r.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                raw_results.append(r)
                
        # Limit to max 10 to avoid too much summarization time
        raw_results = raw_results[:10]
        
        news_db.update_job_status(job_id, "Running", f"Found {len(raw_results)} unique articles. Scraping...")
        
        total = len(raw_results)
        for i, article in enumerate(raw_results):
            title = article.get("title", "No Title")
            url = article.get("url", "")
            snippet = article.get("body", "")
            published = article.get("date", "Unknown Date")
            
            news_db.update_job_status(job_id, "Running", f"Processing {i+1}/{total}: {title[:30]}...")
            
            # Try to scrape the full text
            full_text = snippet
            try:
                page_resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                if page_resp.status_code == 200:
                    soup = BeautifulSoup(page_resp.text, 'html.parser')
                    paragraphs = soup.find_all('p')
                    scraped = " ".join([p.get_text() for p in paragraphs])
                    if len(scraped) > 200:
                        # Truncate to reasonable length for summary to save time
                        full_text = scraped[:4000] 
            except Exception:
                pass # fallback to snippet
                
            system = (
                "Sen profesyonel bir finans ve haber analistisin. "
                "Görevin, sana verilen haber metinlerini veya başlıkları kurumsal bir dille, SADECE TÜRKÇE (Turkish) kullanarak özetlemektir. "
                "ASLA Çince veya başka bir dilde kelime kullanma. Cümleleri uydurma."
            )
            
            prompt = (
                f"Haber Başlığı: {title}\n\n"
                f"İçerik: {full_text}\n\n"
                "Lütfen bu haberi portföy yöneticileri için en fazla 5 cümleyle, net ve tamamen Türkçe olarak özetle. "
                "Eğer metin çok kısaysa, sadece ne anlatıldığını belirt ve detay uydurma."
            )
            
            summary = query_vllm(prompt, system=system)
            
            news_db.save_article(job_id, title, url, snippet, summary, published)
            
        news_db.update_job_status(job_id, "Completed", f"Successfully processed {total} articles.")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        news_db.update_job_status(job_id, "Failed", f"Error: {e}")

def crawl_news_task(job_id):
    thread = threading.Thread(target=crawl_news_task_sync, args=(job_id,))
    thread.daemon = True
    thread.start()
