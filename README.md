# OPDS Server for Audiobookshelf

[![Docstring Check](https://github.com/petr-prikryl/OPDS-ABS/actions/workflows/docstring-check.yml/badge.svg)](https://github.com/petr-prikryl/OPDS-ABS/actions/workflows/docstring-check.yml)

This project provides an OPDS (Open Publication Distribution System) server that fetches books from the **Audiobookshelf API** and presents them in OPDS format, making it easy to browse and download books in supported OPDS clients.

## 🚀 Features

- **Fetch books & libraries** from the **Audiobookshelf API**
- **Supports OPDS** for easy integration with reading apps
- **Simple authentication** using Audiobookshelf username and password
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

## 🛠 Installation & Usage

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

You can control pagination behavior through the `ITEMS_PER_PAGE` environment variable:

- Set a positive number (e.g., 25) to enable pagination with that page size
- Set to 0 to disable pagination and show all items in a single feed

Pagination helps improve performance and load times when dealing with large libraries.

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
