# OPDS Server for Audiobookshelf

This project provides an OPDS (Open Publication Distribution System) server that fetches books from the **Audiobookshelf API** and presents them in OPDS format, making it easy to browse and download books in supported OPDS clients.

## 🚀 Features

- **Fetch books & libraries** from the **Audiobookshelf API**
- **Supports OPDS** for easy integration with reading apps
- **Simple authentication** using API key
- **Dockerized** for easy deployment
- **Lightweight web interface** 

## 🚀 To DO
  -  **OPDS-PS**
  -  **Web interface**
  -  **Auth**

## Confirmed Working clients
 - **PocketBook Reader iOS (some heavy PDFs dont work)**

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

- **OPDS Root:** `http://localhost:8000/opds`
- **Web Interface:** `http://localhost:8000/`

You can use an OPDS-compatible reader (e.g., **Calibre, KOReader, Thorium Reader**) to access your books.

## ⚙ Configuration

You can configure the server using environment variables:

```yaml
services:
  opds:
     environment:
      - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378
      - USERS=John:API_KEY_1,Jan:API_KEY_2,guest:API_KEY_3
      - LANGUAGE=cs # Set the language to Czech (cs) or English (en)

```

Replace `API_KEY_N` with your **Audiobookshelf API key** if authentication is required. CHange names For John, Jan and guest as you want 

## 🐳 Running from GitHub Container Registry (GHCR)

You can use the pre-built Docker image:

```bash
docker run -d -p 8000:8000 --env AUDIOBOOKSHELF_URL=http://audiobookshelf:13378 ghcr.io/petr-prikryl/opds-abs:latest
```

Or use `docker-compose.yml` directly:

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/petr-prikryl/OPDS-ABS/refs/heads/master/docker-compose.yml
docker-compose up -d
```

## 📜 License

This project is licensed under the **MIT License**. See `LICENSE` for details.

## 🙌 Contributing

Pull requests are welcome! If you find a bug or want to suggest improvements, open an **issue** on GitHub.

---

Made with ❤️ for Audiobookshelf users.

