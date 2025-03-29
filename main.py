from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import Response, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import aiohttp
import asyncio
import os
import icons
from lxml import etree

app = FastAPI()
security = HTTPBasic()

# Load configuration from environment variables
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_URL}/api"

# Load user API keys from environment variables
USER_KEYS = {}
users_env = os.getenv("USERS", "")
for pair in users_env.split(","):
    if ":" in pair:
        username, api_key = pair.split(":", 1)
        USER_KEYS[username] = api_key

async def fetch_from_api(endpoint: str, api_key: str):
    """General function to call API with user's API key"""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    print(f"📡 Fetching: {url}")  # Debugging

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                return await response.json()
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="API Timeout")
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=500, detail=f"API Error: {str(e)}")

async def get_download_urls_from_item(id: str, api_key: str):
    """Use the item ID to get the download URL"""
    item = await fetch_from_api(f"/items/{id}", api_key)
    ebook_inos = [{"ino":file.get("ino"),"filename":file.get("metadata").get("filename")} for file in item.get("libraryFiles", []) if "ebook" in file.get("fileType", "")]
    return ebook_inos

def filter_ebook_items(data, jsonPath="media.metadata.title", sortReverse=False):
    """Find items in a library that have an ebook file. Return the results sorted by a field in a specific order"""
    # Filter results to include only items with an ebook file
    filtered_results = [result for result in data.get("results", []) if "ebookFormat" in result.get("media", {}) and result.get("media").get("ebookFormat",None)]

    # Function to extract value based on jsonPath
    def extract_value(item, path):
        keys = path.split('.')
        for key in keys:
            item = item.get(key, None)
            if item is None:
                break
        return item

    # Sort the filtered results based on the extracted value and sortReverse flag
    sorted_results = sorted(filtered_results, key=lambda x: extract_value(x, jsonPath), reverse=sortReverse)

    return sorted_results

@app.get("/opds/{username}")
async def opds_root(username: str):
    """Returns a list of libraries for a specific user"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = await fetch_from_api("/libraries", api_key)
    feed = etree.Element("feed", xmlns="http://www.w3.org/2005/Atom", nsmap={"opds": "http://opds-spec.org/2010/catalog"})
    title = etree.SubElement(feed, "title")
    title.text = f"{username}'s Libraries"
    
    libraries = data.get("libraries", [])
    if len(libraries) == 1:
        return RedirectResponse(url=f"/opds/{username}/library/{libraries[0].get('id', '')}", status_code=302)

        
    for library in data.get("libraries", []):
        entry = etree.SubElement(feed, "entry")
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = library["name"]
        link = etree.SubElement(entry, "link", href=f"/opds/{username}/library/{library['id']}", rel="subsection", type="application/atom+xml")
        link_icon = etree.SubElement(entry, "link", href=f"data:image/png;base64,{icons.library}", rel="http://opds-spec.org/image", type="image/png")

    feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
    return Response(content=feed_xml, media_type="application/atom+xml")

@app.get("/opds/{username}/library/{library_id}")
async def opds_library(username: str, library_id: str):
    """List of books in a specific library for a specific user"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = await fetch_from_api(f"/libraries/{library_id}/items", api_key)

    print(f"📥 API response contains {len(data.get('results', []))} items")

    feed = etree.Element("feed", xmlns="http://www.w3.org/2005/Atom", nsmap={"opds": "http://opds-spec.org/2010/catalog"})
    title = etree.SubElement(feed, "title")
    title.text = f"{username}'s books"

    library_items = filter_ebook_items(data)

    tasks = []

    for book in library_items:
        print(f"🔍 Processing: {book.get('id')}")

        book_id = book.get("id", "")

        tasks.append(get_download_urls_from_item(book_id, api_key))

    ebook_inos_list = await asyncio.gather(*tasks)

    for book, ebook_inos in zip(library_items, ebook_inos_list):
        ebook_format = book.get("media", {}).get("ebookFormat", None)

        for ebook in ebook_inos:
            ino, filename = ebook.get("ino"), ebook.get("filename")
            entry_title_text = book.get("media", {}).get("metadata", {}).get("title", "Unknown Title")
            book_id = book.get("id", "")

            download_path = f"{AUDIOBOOKSHELF_API}/items/{book_id}/file/{ino}/download?token={api_key}" 
            cover_url = f"{AUDIOBOOKSHELF_API}/items/{book_id}/cover?format=jpeg"

            print(f"✅ Adding book: {entry_title_text} ({ebook_format})")

            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = entry_title_text
            entry_id = etree.SubElement(entry, "id")
            entry_id.text = book_id
            entry_filename = etree.SubElement(entry, "content", type="text")
            entry_filename.text = filename
            link_download = etree.SubElement(entry, "link", href=download_path, rel="http://opds-spec.org/acquisition/open-access", type=f"application/{ebook_format}")
            link_cover = etree.SubElement(entry, "link", href=cover_url, rel="http://opds-spec.org/image", type="image/jpeg")

    feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
    return Response(content=feed_xml, media_type="application/atom+xml")

@app.get("/")
def index():
    return Response(content="""
    <!DOCTYPE html>
    <html lang='en'>
    <head>
        <meta charset='UTF-8'>
        <title>OPDS Login</title>
    </head>
    <body>
        <h1>Welcome to the OPDS server</h1>
    </body>
    </html>
    """, media_type="text/html")

# Dockerfile
DOCKERFILE = """
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

# docker-compose.yml
docker_compose = """
version: '3.8'
services:
  opds:
    image: ghcr.io/petr-prikryl/opds-abs:latest
    ports:
      - "8000:8000"
    environment:
      - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378
      - USERS=John:API_KEY_1,Jan:API_KEY_2,guest:API_KEY_3
"""

# Save files
with open("Dockerfile", "w") as f:
    f.write(DOCKERFILE)

with open("docker-compose.yml", "w") as f:
    f.write(docker_compose)
