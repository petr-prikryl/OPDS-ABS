# OPDS Server for Audiobookshelf

[![Docstring Check](https://github.com/petr-prikryl/OPDS-ABS/actions/workflows/docstring-check.yml/badge.svg)](https://github.com/petr-prikryl/OPDS-ABS/actions/workflows/docstring-check.yml)

This project provides an OPDS (Open Publication Distribution System) server that fetches books from the **Audiobookshelf API** and presents them in OPDS format, making it easy to browse and download books in supported OPDS clients.

## 🚀 Features

- **Fetch books & libraries** from the **Audiobookshelf API**
- **Supports OPDS** for easy integration with reading apps
- **Multiple authentication methods**:
  - Basic auth with Audiobookshelf username and password
  - API key authentication for better security and flexibility
  - Bearer token authentication for API clients
- **Pagination support** for better performance with large libraries
- **Dockerized** for easy deployment
- **Lightweight web interface**

## 🚀 To DO
  -  **Enhanced web interface**
  -  **Improved Auth**

## Confirmed Working clients
 - **PocketBook Reader iOS and Android**
 - **KOreader**
 - **Moon+ Reader Pro Android**

## 🔐 Authentication Methods

OPDS-ABS supports multiple authentication methods to connect to your Audiobookshelf server:

### Username and Password

The standard authentication method using your Audiobookshelf username and password:

```
Username: your_abs_username
Password: your_abs_password
```

This method always works regardless of configuration settings.

### API Key Authentication

For improved security, you can use an API key instead of your password. This is useful for clients where you don't want to store your actual password. **Note: API Key authentication must be enabled with the `API_KEY_AUTH_ENABLED=true` environment variable.**

#### How to Get Your Audiobookshelf API Key

1. Log into your Audiobookshelf web interface
2. Click on your user icon in the top-right corner
3. Select "User Settings"
4. Find the "API Key" section
5. Copy your existing API key or generate a new one

#### Option 1: Basic Auth with API Key (Recommended for OPDS Clients)
```
Username: your_abs_username
Password: your_audiobookshelf_api_key
```
Most OPDS clients support this authentication method. Use your Audiobookshelf API key in place of your password.

#### Option 2: Bearer Token (For API Clients)
For direct API access, you can use the API key as a Bearer token:
```
Authorization: Bearer your_audiobookshelf_api_key
```

The server will automatically determine your username from the API key by querying Audiobookshelf.

This method matches Audiobookshelf's native API authentication behavior.

### Switching Between Authentication Methods

If you need to switch between different authentication methods, you can use the following environment variables:

1. `API_KEY_AUTH_ENABLED=false` - Disables all API key authentication, forcing the use of username/password only
2. `AUTH_TOKEN_CACHING=false` - Disables token caching, ensuring each request is authenticated fresh (useful when testing)

### Security notes

- Feed links **never contain your Audiobookshelf token**. Your reader must send HTTP
  Basic credentials with each request (all mainstream OPDS clients do). Tokens in URLs
  used to end up in access logs, proxy logs and reader history.
- A request without credentials is always answered with a `401` challenge. The server
  never serves a catalog from a previously cached session.
- Cached tokens are keyed by the exact credential that was accepted, so a wrong
  password cannot ride on someone else's cached session.
- ABS tokens are kept in memory only and are never written to `cache.pkl`.
- `/admin/cache/*` requires an Audiobookshelf administrator account.
- If you expose OPDS-ABS to the internet, put it behind HTTPS.

## 🛠 Installation & Usage

### 1️⃣ **Run the pre-built image**

No clone is needed. Download the compose file and start it:

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/petr-prikryl/OPDS-ABS/refs/heads/master/docker-compose.yml
docker compose up -d
```

Or with plain Docker:

```bash
docker run -d -p 8000:8000 \
  --env AUDIOBOOKSHELF_INTERNAL_URL=http://audiobookshelf:13378 \
  --env AUDIOBOOKSHELF_EXTERNAL_URL=https://abs.example.com \
  --env PUID=$(id -u) \
  --env PGID=$(id -g) \
  --volume ./data:/app/opds_abs/data \
  ghcr.io/petr-prikryl/opds-abs:latest
```

### 2️⃣ **Run from source (optional)**

```bash
git clone https://github.com/petr-prikryl/OPDS-ABS.git
cd OPDS-ABS
docker compose up -d --build
```

### 3️⃣ **Access the OPDS feed**

- **OPDS Root:** `http://localhost:8000/opds/`
- **Web Interface:** `http://localhost:8000/`

You can use an OPDS-compatible reader (e.g., **KOReader, Moon+ Reader, PocketBook**) to access your books.

When the reader asks for credentials, enter your **Audiobookshelf username and password**.
Do not paste the token from your browser session — it expires and is not a login credential.
If you prefer not to store your password in the reader, use an ABS API key as the password
(see above).

### How the container talks to Audiobookshelf

Two URLs are used, and they are not interchangeable:

- `AUDIOBOOKSHELF_INTERNAL_URL` — used by OPDS-ABS for API calls. It must be reachable
  **from inside the container**.
- `AUDIOBOOKSHELF_EXTERNAL_URL` — written into feed links for covers and downloads. It
  must be reachable **from your reader** (usually the public URL).

Typical setups:

| Where Audiobookshelf runs | `AUDIOBOOKSHELF_INTERNAL_URL` |
|---|---|
| Same Docker network | `http://audiobookshelf:13378` (service name) |
| Docker host | `http://host.docker.internal:13378` (add `extra_hosts: ["host.docker.internal:host-gateway"]` on Linux) |
| Another machine | `http://192.168.1.10:13378` |

If the container has to use the host network (e.g. on Synology), set `network_mode: host`,
drop the `ports:` block and point `AUDIOBOOKSHELF_INTERNAL_URL` at the host address.

## ⚙ Configuration

You can configure the server using environment variables in your docker-compose.yml file:

```yaml
services:
  opds:
     environment:
      # User/Group settings for proper file permissions
      - PUID=1000  # Set to your user's UID
      - PGID=1000  # Set to your user's GID

      # Connection settings
      # Legacy: AUDIOBOOKSHELF_URL is supported for backward compatibility
      # - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378
      # Recommended: set internal and/or external URLs
      - AUDIOBOOKSHELF_INTERNAL_URL=http://audiobookshelf
      - AUDIOBOOKSHELF_EXTERNAL_URL=http://abs.example.com

      # Feature toggles
      - AUTH_ENABLED=true
      - API_KEY_AUTH_ENABLED=true
      - CACHE_PERSISTENCE_ENABLED=true

      # Performance settings
      - OPDS_LOG_LEVEL=INFO
      - ITEMS_PER_PAGE=25  # Set to 0 to disable pagination
```

### Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `AUDIOBOOKSHELF_URL` | (Legacy) Main URL of your Audiobookshelf server. If set, used for both internal and external. | `http://localhost` |
| `AUDIOBOOKSHELF_INTERNAL_URL` | Internal URL for container-to-container communication. If only this or EXTERNAL is set, that value is used for both. | `http://localhost` |
| `AUDIOBOOKSHELF_EXTERNAL_URL` | External URL for client downloads and images. If only this or INTERNAL is set, that value is used for both. | `http://localhost` |
| `AUTH_ENABLED` | Enable/disable authentication | `true` |
| `API_KEY_AUTH_ENABLED` | Enable/disable API key authentication (set to `false` to only allow username/password) | `true` |
| `AUTH_TOKEN_CACHING` | Enable/disable token caching (set to `false` to force re-authentication on each request) | `true` |
| `PAGINATION_ENABLED` | Enable/disable pagination entirely (overrides ITEMS_PER_PAGE) | `true` |
| `PUID` | User ID for file ownership | `1000` |
| `PGID` | Group ID for file ownership | `1000` |
| `ITEMS_PER_PAGE` | Number of items per page, 0 to disable pagination | `25` |
| `OPDS_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `CACHE_PERSISTENCE_ENABLED` | Enable/disable cache persistence | `true` |
| `UVICORN_RELOAD` | Enable uvicorn auto-reload (development only; it keeps an idle container busy) | `false` |

## 🐳 Running from GitHub Container Registry (GHCR)

You can use the pre-built Docker image:


```bash
docker run -d -p 8000:8000 \
  --env AUDIOBOOKSHELF_INTERNAL_URL=http://audiobookshelf:13378 \
  --env AUDIOBOOKSHELF_EXTERNAL_URL=http://abs.hlm.ing:13378 \
  --env PUID=$(id -u) \
  --env PGID=$(id -g) \
  --volume ./data:/app/opds_abs/data \
  ghcr.io/petr-prikryl/opds-abs:latest
```

# Legacy support
# You may still use AUDIOBOOKSHELF_URL for both internal and external if desired.

Or use `docker-compose.yml` directly:

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/petr-prikryl/OPDS-ABS/refs/heads/master/docker-compose.yml
docker-compose up -d
```

## 📦 Advanced Docker Usage

### Custom User Permissions

The Docker container supports custom user IDs to ensure proper file ownership when mounting volumes:

```bash
# Find your user and group IDs
id -u  # Your user ID (PUID)
id -g  # Your group ID (PGID)
```

Update your docker-compose.yml with these values to ensure proper file permissions.

### Pagination

You can control pagination behavior through two environment variables:

- `PAGINATION_ENABLED`: Set to `false` to completely disable pagination across all feeds
- `ITEMS_PER_PAGE`: Set a positive number (e.g., 25) for page size, or 0 to disable pagination but keep the option

For most users, setting `PAGINATION_ENABLED=false` is the simplest way to disable pagination completely. Using `ITEMS_PER_PAGE=0` is an alternative that keeps the pagination code active but shows all items.

Pagination helps improve performance and load times when dealing with large libraries, but disabling it can be useful for smaller libraries or when using clients that work better with complete feeds.

## 🙌 Contributing

Pull requests are welcome! If you find a bug or want to suggest improvements, open an **issue** on GitHub.

### Development Setup

1. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

2. Set up pre-commit hooks:
   ```bash
   pre-commit install
   ```

3. Before submitting a PR, ensure your code passes all checks:
   ```bash
   ./docstring-check.py
   ```

For more information about our documentation standards, see [DOCS_STANDARDS.md](DOCS_STANDARDS.md).

---

Made with ❤️ for Audiobookshelf users.
