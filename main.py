from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import requests
import os

app = FastAPI()
security = HTTPBasic()

# Načtení konfigurace z prostředí
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_URL}/api"

# Načteme API klíče uživatelů z prostředí
USER_KEYS = {}
users_env = os.getenv("USERS", "")
for pair in users_env.split(","):
    if ":" in pair:
        username, api_key = pair.split(":", 1)
        USER_KEYS[username] = api_key

def fetch_from_api(endpoint: str, api_key: str):
    """Obecná funkce pro volání API s uživatelským API klíčem"""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    print(f"📡 Fetching: {url}")  # Debugging

    try:
        response = requests.get(url, headers=headers, timeout=10)  # Timeout 10s
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="API Timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Chyba API: {str(e)}")

@app.get("/opds/{username}")
def opds_root(username: str):
    """Vrátí seznam knihoven pro konkrétního uživatele"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = fetch_from_api("/libraries", api_key)

    feed = f"""
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
        <title>Libraries of {username}</title>
    """

    for library in data.get("libraries", []):
        feed += f"""
        <entry>
            <title>{library["name"]}</title>
            <link href="/opds/{username}/library/{library['id']}" rel="subsection" type="application/atom+xml"/>
        </entry>
        """

    feed += "</feed>"
    return Response(content=feed, media_type="application/atom+xml")

@app.get("/opds/{username}/library/{library_id}")
def opds_library(username: str, library_id: str):
    """Seznam knih v konkrétní knihovně pro konkrétního uživatele"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = fetch_from_api(f"/libraries/{library_id}/items", api_key)

    print(f"📥 API odpověď obsahuje {len(data.get('results', []))} položek")

    feed = f"""
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
        <title>Books of {username}</title>
    """

    for book in data.get("results", []):
        print(f"🔍 Zpracovávám: {book.get('id')}")

        ebook_format = book.get("media", {}).get("ebookFormat", None)
        if not ebook_format:
            print(f"⏭ Přeskakuji: {book.get('id')} (chybí ebookFormat)")
            continue

        title = book.get("media", {}).get("metadata", {}).get("title", "Neznámý název")
        book_id = book.get("id", "")
        download_path = f"{AUDIOBOOKSHELF_API}/items/{book_id}/download?token={api_key}"
        cover_url = f"{AUDIOBOOKSHELF_API}/items/{book_id}/cover?format=jpeg"

        print(f"✅ Přidávám knihu: {title} ({ebook_format})")

        feed += f"""
        <entry>
            <title>{title}</title>
            <id>{book_id}</id>
            <link href="{download_path}" rel="http://opds-spec.org/acquisition/open-access" type="application/{ebook_format}"/>
            <link href="{cover_url}" rel="http://opds-spec.org/image" type="image/jpeg"/>
        </entry>
        """

    feed += "</feed>"
    return Response(content=feed, media_type="application/atom+xml")



@app.get("/")
def index():
    return Response(content="""
    <!DOCTYPE html>
    <html lang='cs'>
    <head>
        <meta charset='UTF-8'>
        <title>OPDS Přihlášení</title>
    </head>
    <body>
        <h1>Vítejte v OPDS serveru</h1>
        <form action="/opds/catalog">
            <button type='submit'>Zobrazit knihovny</button>
        </form>
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

# Uložení souborů
with open("Dockerfile", "w") as f:
    f.write(DOCKERFILE)

with open("docker-compose.yml", "w") as f:
    f.write(docker_compose)
