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

## � Authentication Methods

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

## �🛠 Installation & Usage

### 1️⃣ **Clone the repository**

```bash
git clone https://github.com/petr-prikryl/opds-abs.git
cd opds-abs
```

### 2️⃣ **Run with Docker Compose**

Ensure **Docker** and **Docker Compose** are installed, then run:

```bash
docker-compose up -d
```

This will start the OPDS server.

### 3️⃣ **Access the OPDS feed**

- **OPDS Root:** `http://localhost:8000/opds/`
- **Web Interface:** `http://localhost:8000/`

You can use an OPDS-compatible reader (e.g., **Calibre, KOReader, Thorium Reader**) to access your books.

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
      - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378

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
| `AUDIOBOOKSHELF_URL` | URL of your Audiobookshelf server | `http://localhost:13378` |
| `AUTH_ENABLED` | Enable/disable authentication | `true` |
| `API_KEY_AUTH_ENABLED` | Enable/disable API key authentication (set to `false` to only allow username/password) | `true` |
| `AUTH_TOKEN_CACHING` | Enable/disable token caching (set to `false` to force re-authentication on each request) | `true` |
| `PAGINATION_ENABLED` | Enable/disable pagination entirely (overrides ITEMS_PER_PAGE) | `true` |
| `PUID` | User ID for file ownership | `1000` |
| `PGID` | Group ID for file ownership | `1000` |
| `ITEMS_PER_PAGE` | Number of items per page, 0 to disable pagination | `25` |
| `OPDS_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `CACHE_PERSISTENCE_ENABLED` | Enable/disable cache persistence | `true` |

## 🐳 Running from GitHub Container Registry (GHCR)

You can use the pre-built Docker image:

```bash
docker run -d -p 8000:8000 \
  --env AUDIOBOOKSHELF_URL=http://audiobookshelf:13378 \
  --env PUID=$(id -u) \
  --env PGID=$(id -g) \
  --volume ./data:/app/opds_abs/data \
  ghcr.io/petr-prikryl/opds-abs:latest
```

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
