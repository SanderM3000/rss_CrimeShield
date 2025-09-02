# Cursor Rules for VRT RSS Desktop Monitor

## Project Overview
This is a **Desktop RSS News Aggregator** application built with Python/Tkinter that monitors multiple RSS/Atom feeds, stores articles in PostgreSQL, and provides a local desktop interface for browsing news articles with thumbnail images.

## Architecture & Design Principles

### Core Components
1. **RSS Feed Parser** - Fetches and parses RSS/Atom feeds using `feedparser`
2. **Database Layer** - PostgreSQL integration with `psycopg2` for persistent article storage
3. **Desktop GUI** - Tkinter-based interface with article browsing and feed management
4. **Image Handler** - Downloads and caches article thumbnails locally
5. **Data Pipeline** - CSV export/import with deduplication and merge logic

### Key Design Patterns
- **Single-file monolith** - Keep all functionality in `vrt_rss_desktop.py`
- **Data normalization** - All DataFrames use consistent column structure
- **Robust error handling** - Non-fatal errors for network/DB operations
- **Secure credentials** - Environment variables via `.env` file only
- **Local caching** - Images and CSV backup for offline access

## Development Rules

### Security & Credentials
- **NEVER** hardcode database credentials in source code
- **ALWAYS** use environment variables loaded from `.env` file
- **ENSURE** `.env` is in `.gitignore` to prevent credential leaks
- **REQUIRE** SSL connections to PostgreSQL (`sslmode='require'`)
- **VALIDATE** all environment variables before database connections

### Database Operations
- **USE** UUID primary keys for articles (generated from URL hash)
- **IMPLEMENT** upsert operations (INSERT ... ON CONFLICT DO UPDATE)
- **MAINTAIN** proper indexes on `published_time` and `url` columns
- **HANDLE** connection failures gracefully (app should continue working)
- **BATCH** database operations for performance

### Data Handling
- **NORMALIZE** all DataFrames through `dedupe_df()` function
- **DEDUPLICATE** articles by `article_id` before storage
- **SORT** articles by published time (newest first)
- **VALIDATE** required columns exist in all DataFrames
- **SANITIZE** string inputs with `s()` helper function

### GUI Development
- **MAINTAIN** two-panel layout (article list + details/sources)
- **USE** Treeview for article display with proper column sizing
- **IMPLEMENT** real-time countdown timer for next refresh
- **PROVIDE** visual feedback for new articles (bold green text)
- **ENABLE** keyboard navigation and selection

### Feed Management
- **SUPPORT** RSS and Atom feed formats
- **VALIDATE** feed URLs before adding to collection
- **IMPLEMENT** auto-discovery from webpage URLs
- **MAINTAIN** persistent feed list in `feeds.json`
- **REQUIRE** at least one active feed at all times

### Image Handling
- **DOWNLOAD** thumbnails to local `media/` directory
- **CACHE** images by article ID to avoid re-downloads
- **RESIZE** images to max 320x240 pixels for display
- **HANDLE** missing/broken images gracefully
- **SUPPORT** common formats: jpg, jpeg, png, webp

## Code Style & Structure

### Function Organization
```
# Config constants (top of file)
# Database helpers
# General utility functions  
# Data fetching and parsing
# CSV merge and caching
# Image download and processing
# Feed discovery
# Tkinter GUI class
# Main entry point
```

### Error Handling Strategy
- **Network errors** - Log and continue (feeds might be temporarily down)
- **Database errors** - Display message but don't crash app
- **Image errors** - Show placeholder text, continue operation
- **Parse errors** - Skip malformed entries, process valid ones
- **File I/O errors** - Create fallback files with timestamps

### Performance Guidelines
- **POLL** feeds every 10 minutes (600 seconds) by default
- **BATCH** database operations with `page_size=1000`
- **LIMIT** string lengths (title max 10000 chars)
- **CACHE** existing data in memory to reduce DB queries
- **OPTIMIZE** DataFrame operations with proper indexing

## Dependencies & Environment

### Required Packages
- `pandas` - Data manipulation and CSV handling
- `requests` - HTTP requests for feeds and images
- `feedparser` - RSS/Atom feed parsing
- `Pillow` - Image processing and thumbnails
- `beautifulsoup4` - HTML parsing for feed discovery
- `psycopg2-binary` - PostgreSQL database connectivity
- `python-dotenv` - Environment variable management
- `openpyxl` - Excel export functionality

### Environment Variables Required
```bash
PGHOST=your-postgres-host
PGPORT=5432
PGDATABASE=your-database-name
PGUSER=your-username
PGPASSWORD=your-password
```

## Testing & Debugging

### Database Connection Testing
- Use `debug_dsn()` to verify connection parameters
- Test `ensure_table_exists()` on startup
- Validate schema matches expected structure

### Feed Validation
- Test new feeds with `feedparser.parse()` before adding
- Verify feed discovery works on target websites
- Check handling of various RSS/Atom formats

### Error Scenarios to Handle
- Network timeouts during feed polling
- PostgreSQL connection drops
- Malformed RSS feeds
- Missing or corrupted images
- File permission errors for CSV/Excel export

## Deployment & Distribution

### Local Setup
1. Create virtual environment: `python -m venv venv`
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file with database credentials
4. Run application: `python vrt_rss_desktop.py`

### Production Considerations
- **NEVER** commit `.env` file to version control
- **USE** dedicated database user with minimal permissions
- **MONITOR** disk space for image cache in `media/` directory
- **BACKUP** PostgreSQL database regularly
- **ROTATE** database passwords periodically

## Modification Guidelines

### Adding New Features
- **EXTEND** existing classes rather than creating new modules
- **MAINTAIN** backward compatibility with existing data
- **UPDATE** database schema with proper migrations
- **TEST** with various RSS feed formats

### UI Changes
- **PRESERVE** keyboard accessibility
- **MAINTAIN** responsive layout for different screen sizes
- **FOLLOW** platform UI conventions (Windows/Mac/Linux)
- **PROVIDE** status feedback for long-running operations

### Database Schema Changes
- **USE** proper ALTER TABLE statements in `ensure_table_exists()`
- **MAINTAIN** existing indexes and constraints
- **BACKUP** data before schema modifications
- **VALIDATE** migrations with test data

## AI Assistant Guidelines

When working on this project:
1. **PRIORITIZE** security - never expose credentials
2. **MAINTAIN** the monolithic structure - don't split into multiple files
3. **PRESERVE** existing functionality while adding improvements
4. **TEST** database connections before making schema changes
5. **VALIDATE** RSS feeds before adding to the system
6. **FOLLOW** the established error handling patterns
7. **RESPECT** the polling interval to avoid overwhelming feed servers
8. **MAINTAIN** data consistency between CSV and PostgreSQL storage
