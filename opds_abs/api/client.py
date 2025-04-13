"""Client for interacting with Audiobookshelf API"""
import asyncio
import logging
import aiohttp
from fastapi import HTTPException

from opds_abs.config import AUDIOBOOKSHELF_API, USER_KEYS, API_KEY

logger = logging.getLogger(__name__)

async def fetch_from_api(endpoint: str, params: dict = None, username: str = None):
    """General function to call API with user's API key"""
    # Use the specified user's API key if provided, otherwise use the default
    api_key = USER_KEYS.get(username, API_KEY) if username else API_KEY
    
    if not api_key:
        error_msg = f"No API key available{'for user '+username if username else ''}"
        logger.error(error_msg)
        raise HTTPException(status_code=401, detail=error_msg)
        
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    logger.info(f"📡 Fetching: {url}{' with params ' + str(params) if params else ''}")

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
            logger.error(f"Timeout error for {url}: {str(timeout_error)}")
            raise HTTPException(
                    status_code=504,
                    detail="504: Timeout"
            ) from timeout_error
        except aiohttp.ClientError as client_error:
            logger.error(f"Client error for {url}: {str(client_error)}")
            raise HTTPException(
                    status_code=500,
                    detail=f"500: {str(client_error)}"
            ) from client_error

async def get_download_urls_from_item(item_id: str, username: str = None):
    """Use the item ID to get the download URL"""
    try:
        item = await fetch_from_api(f"/items/{item_id}", username=username)
        ebook_inos = []
        for file in item.get("libraryFiles", []):
            if "ebook" in file.get("fileType", ""):
                ebook_inos.append({
                    "ino":          file.get("ino"),
                    "filename":     file.get("metadata", {}).get("filename", ""),
                    "download_url": ""
                })
        return ebook_inos
    except Exception as e:
        logger.error(f"Error getting download URLs for item {item_id}: {str(e)}")
        return []