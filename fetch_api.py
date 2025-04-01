"""Grab data from Audiobookshelf endpoints"""
import asyncio
import logging
import aiohttp
from fastapi import HTTPException
from config import AUDIOBOOKSHELF_API, API_KEY

async def fetch_from_api(endpoint: str, params: dict = None):
    """General function to call API with user's API key"""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    print(f"📡 Fetching: {url}{' with params ' + str(params) if params else ''}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                    url,
                    params=params if params else {},
                    headers=headers,
                    timeout=10
                ) as response:
                response.raise_for_status()
                return await response.json()
        except asyncio.TimeoutError as timeout_error:
            raise HTTPException(
                    status_code=504,
                    detail="504: Timeout"
            ) from timeout_error
        except aiohttp.ClientError as client_error:
            raise HTTPException(
                    status_code=500,
                    detail=f"500: {str(client_error)}"
            ) from client_error

async def get_download_urls_from_item(item_id: str):
    """Use the item ID to get the download URL"""
    item = await fetch_from_api(f"/items/{item_id}")
    ebook_inos = []
    for file in item.get("libraryFiles", []):
        if "ebook" in file.get("fileType", ""):
            ebook_inos.append({
                "ino":          file.get("ino"),
                "filename":     file.get("metadata").get("filename"),
                "download_url": ""
            })
    return ebook_inos
