# VRT RSS Desktop Monitor

A comprehensive desktop application for monitoring and aggregating RSS/Atom news feeds with PostgreSQL storage and local image caching.

## Overview

The VRT RSS Desktop Monitor is a Python-based news aggregation tool that automatically polls multiple RSS/Atom feeds, stores articles in a PostgreSQL database, and provides an intuitive desktop interface for browsing news content. Originally designed for monitoring VRT NWS (Belgian news), it supports any RSS/Atom feed source.

![Application Interface](https://img.shields.io/badge/Interface-Tkinter_Desktop-blue)
![Database](https://img.shields.io/badge/Database-PostgreSQL-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)

## Key Features

### 📡 **Multi-Feed RSS Aggregation**
- Monitors multiple RSS/Atom feeds simultaneously
- Automatic polling every 10 minutes (configurable)
- Support for RSS 2.0, Atom 1.0, and RDF feeds
- Intelligent feed discovery from webpage URLs

### 🗄️ **PostgreSQL Integration**
- Persistent article storage with UUID-based deduplication
- Efficient upsert operations to handle feed updates
- Indexed queries for fast article retrieval
- Secure SSL connections to cloud databases

### 🖥️ **Desktop Interface**
- Clean two-panel layout for browsing articles
- Real-time feed updates with visual new article indicators
- Article details with thumbnail images
- Built-in browser integration for full article reading

### 🖼️ **Image Management**
- Automatic thumbnail downloading and caching
- Local image storage to reduce bandwidth usage
- Image resizing and optimization for display
- Support for JPG, PNG, WebP formats

### 📊 **Data Export**
- One-click Excel export functionality
- CSV backup for offline access
- Data persistence between application sessions

## Architecture

### Data Flow
```
RSS Feeds → Feed Parser → DataFrame Processing → PostgreSQL Storage
                                ↓
                         Local CSV Cache ← Tkinter GUI ← Image Cache
```

### Core Components

1. **Feed Processing Engine**
   - Uses `feedparser` library for robust RSS/Atom parsing
   - Handles various feed formats and encoding issues
   - Extracts metadata including images from media namespaces

2. **Database Layer**
   - PostgreSQL with `psycopg2` for high-performance operations
   - UUID-based article identification for reliable deduplication
   - Optimized schema with proper indexing

3. **GUI Framework**
   - Tkinter-based desktop interface for cross-platform compatibility
   - Responsive layout with keyboard navigation support
   - Real-time updates without blocking the interface

4. **Image Pipeline**
   - Concurrent image downloading with timeout handling
   - Local caching system to minimize repeated downloads
   - Automatic thumbnail generation for consistent display

## Installation & Setup

### Prerequisites
- Python 3.8 or higher
- PostgreSQL database (local or cloud-hosted)
- Virtual environment (recommended)

### Quick Start

1. **Clone and Setup Environment**
   ```bash
   git clone <repository-url>
   cd python_scraper
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Database Configuration**
   Create a `.env` file in the project root:
   ```env
   PGHOST=your-postgres-host
   PGPORT=5432
   PGDATABASE=your-database-name
   PGUSER=your-username
   PGPASSWORD=your-password
   ```

3. **Run Application**
   ```bash
   python vrt_rss_desktop.py
   ```

### Database Setup

The application automatically creates the required table structure:

```sql
CREATE TABLE IF NOT EXISTS rss_article (
    article_id      uuid PRIMARY KEY,
    title           text NOT NULL,
    published_time  timestamptz,
    author          text,
    description     text,
    url             text,
    image_url       text,
    source_name     text,
    source_feed_url text,
    fetched_at_utc  timestamptz NOT NULL
);
```

## Usage Guide

### Managing RSS Feeds

**Adding Feeds:**
1. Navigate to the "Sources" tab
2. Paste an RSS/Atom feed URL
3. Click "Add" to validate and include the feed

**Feed Discovery:**
1. Paste any website URL in the feed input
2. Click "Find feed on page" to auto-discover RSS feeds
3. The application will scan for `<link rel="alternate">` tags

**Removing Feeds:**
1. Select a feed from the active feeds list
2. Click "Remove selected" (minimum one feed required)

### Browsing Articles

**Article List:**
- Articles are sorted by publication time (newest first)
- New articles appear in **bold green** text
- Click any article to view full details

**Article Details:**
- View full title, publication info, and description
- Thumbnail images load automatically if available
- Click "Open article in browser" to read the full content

### Data Management

**Excel Export:**
- Click "Export to Excel" for a timestamped spreadsheet
- Includes all article metadata and publication dates
- Handles file locking with automatic fallback naming

**Local Storage:**
- Articles cached in `vrt_nws_latest.csv`
- Images stored in `media/` directory
- Feed configuration saved in `feeds.json`

## Configuration

### Polling Settings
```python
POLL_SECONDS = 600  # 10 minutes between feed checks
```

### Image Settings
```python
THUMBNAIL_MAX_W = 320  # Maximum thumbnail width
THUMBNAIL_MAX_H = 240  # Maximum thumbnail height
```

### Default Feeds
The application ships with Belgian news sources:
- VRT NWS (Flemish public broadcaster)
- Bruzz Brussels news
- Het Laatste Nieuws

## Development

### Project Structure
```
python_scraper/
├── vrt_rss_desktop.py    # Main application (single file)
├── requirements.txt      # Python dependencies
├── feeds.json           # RSS feed configuration
├── .env                 # Database credentials (create this)
├── .gitignore          # Git ignore file
├── media/              # Cached thumbnail images
└── vrt_nws_latest.csv  # Article data cache
```

### Key Dependencies
- **pandas**: Data manipulation and CSV handling
- **requests**: HTTP requests for feeds and images
- **feedparser**: RSS/Atom feed parsing
- **Pillow**: Image processing and thumbnails
- **psycopg2-binary**: PostgreSQL connectivity
- **python-dotenv**: Environment variable management

### Extending the Application

**Adding New Feed Sources:**
The application supports any valid RSS/Atom feed. Popular news sources include:
- Reuters: `https://feeds.reuters.com/reuters/topNews`
- BBC: `http://feeds.bbci.co.uk/news/rss.xml`
- Associated Press: `https://feeds.apnews.com/rss/apf-topnews`

**Database Customization:**
Modify the `ensure_table_exists()` function to add custom fields or indexes for specific use cases.

## Security Considerations

### Credential Management
- **Never** commit `.env` files to version control
- Use dedicated database users with minimal required permissions
- Enable SSL connections for production databases
- Rotate database passwords regularly

### Network Security
- All HTTP requests include timeout protection
- SSL certificate validation for HTTPS feeds
- User-agent headers for responsible web scraping

## Troubleshooting

### Common Issues

**Database Connection Errors:**
```bash
# Test connection manually
python -c "from vrt_rss_desktop import debug_dsn; debug_dsn()"
```

**Feed Parsing Issues:**
- Verify feed URL returns valid XML
- Check for network connectivity issues
- Some feeds may have IP-based rate limiting

**Image Loading Problems:**
- Ensure write permissions for `media/` directory
- Check available disk space for image cache
- Some images may require specific user agents

**Performance Issues:**
- Monitor database query performance with large article counts
- Consider archiving old articles periodically
- Adjust polling frequency based on feed update rates

## License

This project is intended for educational and personal use. Respect robots.txt files and feed publisher guidelines when adding new sources.

## Contributing

When contributing to this project:
1. Maintain the single-file architecture
2. Follow the established error handling patterns
3. Test with various RSS feed formats
4. Ensure backward compatibility with existing data

For security vulnerabilities, please report privately rather than through public issues.

---

**Built with ❤️ for news enthusiasts and data aggregation learners**
