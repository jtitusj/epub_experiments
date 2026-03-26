import requests
from bs4 import BeautifulSoup
import re

def scrape_novelbin_chapter(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    content_div = soup.find("div", id="chr-content") or soup.find("div", class_="chr-content")
    if not content_div:
        return None
    
    # Remove script tags and other noise
    for script in content_div(["script", "style", "div"]):
        if 'ads' in (script.get('class') or []) or 'ads' in (script.get('id') or ''):
            script.decompose()

    # NovelBin often has some hidden text or ads inside the content.
    # Let's just get the paragraphs.
    paragraphs = content_div.find_all("p")
    text_blocks = []
    for p in paragraphs:
        text = p.get_text(strip=True)
        if text:
            text_blocks.append(text)
            
    if not text_blocks:
        return None
        
    title = text_blocks[0]
    content = text_blocks[1:]
    
    next_link = soup.find("a", id="next_chap")
    next_url = next_link["href"] if next_link and next_link.get("href") else None
    if next_url and not next_url.startswith("http"):
        from urllib.parse import urljoin
        next_url = urljoin(url, next_url)
        
    return {
        "title": title,
        "content": content,
        "next_url": next_url
    }

if __name__ == "__main__":
    url = "https://novelbin.com/b/i-became-the-tyrant-of-a-defense-game/chapter-1-game-clear"
    data = scrape_novelbin_chapter(url)
    if data:
        print(f"Title: {data['title']}")
        print(f"Content length: {len(data['content'])} paragraphs")
        print(f"First paragraph: {data['content'][0][:100]}...")
        print(f"Next URL: {data['next_url']}")
    else:
        print("Failed to scrape.")
