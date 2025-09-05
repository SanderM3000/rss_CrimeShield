import uuid
import os
import json
import webbrowser
from urllib.parse import urlparse, urljoin
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict

import psycopg2
import psycopg2.extras as extras
from dotenv import load_dotenv

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

import pandas as pd
import requests
import feedparser
from PIL import Image, ImageTk
from bs4 import BeautifulSoup

# -------------------- Config --------------------
DEFAULT_FEEDS = [
    "https://www.vrt.be/vrtnws/nl.rss.articles.xml",  # VRT NWS (NL)
]
CSV_OUT = Path("vrt_nws_latest.csv")
FEEDS_JSON = Path("feeds.json")
MEDIA_DIR = Path("media")
POLL_SECONDS = 600          # 10 minutes
SOURCE_FALLBACK = "RSS Feed"

THUMBNAIL_MAX_W = 320
THUMBNAIL_MAX_H = 240

# -------------------- DB helpers --------------------
def pg_connect():
    """
    Reads credentials from .env file
    """
    load_dotenv()
    
    # Get environment variables with validation
    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    
    # Validate required credentials
    if not all([host, database, user, password]):
        raise ValueError("Missing required database credentials in environment variables")
    
    try:
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            dbname=database,
            user=user,
            password=password,
            sslmode='require'  # Force SSL for security
        )
        # Make psycopg2 adapt Python uuid.UUID automatically
        extras.register_uuid(conn_or_curs=conn)
        return conn
    except psycopg2.Error as e:
        raise ConnectionError(f"Failed to connect to database: {e}")


UPSERT_SQL = """
INSERT INTO rss_article (
    article_id, title, published_time, author, description,
    url, image_url, source_name, source_feed_url, fetched_at_utc
) VALUES %s
ON CONFLICT (article_id) DO UPDATE SET
    title            = EXCLUDED.title,
    published_time   = EXCLUDED.published_time,
    author           = EXCLUDED.author,
    description      = EXCLUDED.description,
    url              = EXCLUDED.url,
    image_url        = EXCLUDED.image_url,
    source_name      = EXCLUDED.source_name,
    source_feed_url  = EXCLUDED.source_feed_url,
    fetched_at_utc   = EXCLUDED.fetched_at_utc;
"""

def safe_uuid(val) -> uuid.UUID:
    try:
        return uuid.UUID(str(val))
    except Exception:
        # fallback to a random UUID if something is malformed
        return uuid.uuid4()

def df_to_rows(df: pd.DataFrame):
    """Map DataFrame -> tuples for UPSERT_SQL, robust to index and bad UUIDs."""
    if df is None or df.empty:
        return []

    needed = [
        "article_id","title","published_time_utc","author","description",
        "url","image_url","source_name","source_feed_url","fetched_at_utc"
    ]
    for c in needed:
        if c not in df.columns:
            df[c] = None

    # IMPORTANT: ensure .iloc indexing lines up with loop index
    df = df.reset_index(drop=True)

    pub = pd.to_datetime(df["published_time_utc"], errors="coerce", utc=True)
    fet = pd.to_datetime(df["fetched_at_utc"], errors="coerce", utc=True)

    rows = []
    for idx, r in df.iterrows():
        rows.append((
            safe_uuid(r["article_id"]),
            (r["title"] or "")[:10000],
            (pub.iloc[idx].to_pydatetime() if pd.notna(pub.iloc[idx]) else None),
            (r["author"] or None),
            (r["description"] or None),
            (r["url"] or None) or None,
            (r["image_url"] or None) or None,
            (r["source_name"] or None) or None,
            (r["source_feed_url"] or None) or None,
            (fet.iloc[idx].to_pydatetime() if pd.notna(fet.iloc[idx]) else datetime.now(timezone.utc)),
        ))
    return rows


def upsert_articles(df: pd.DataFrame, page_size: int = 1000) -> int:
    rows = df_to_rows(df)
    if not rows:
        return 0
    conn = pg_connect()
    try:
        with conn, conn.cursor() as cur:
            extras.execute_values(cur, UPSERT_SQL, rows, page_size=page_size)
        return len(rows)
    finally:
        conn.close()

def debug_dsn():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select current_database(), current_schema(), current_user")
            print("[DB]", cur.fetchone())
    finally:
        conn.close()

def ensure_table_exists():
    ddl = """
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
    CREATE INDEX IF NOT EXISTS idx_rss_article_published_time
      ON rss_article (published_time DESC);
    CREATE INDEX IF NOT EXISTS idx_rss_article_url ON rss_article (url);
    """
    conn = pg_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(ddl)
    finally:
        conn.close()

# -------------------- General helpers --------------------
def s(x) -> str:
    """Safe string: None/NaN -> '', else str(x)."""
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x)

def gen_article_id(url: Optional[str]) -> str:
    if not url:
        return str(uuid.uuid4())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))

def to_iso(dt_struct) -> Optional[str]:
    """Feedparser time_struct -> ISO8601 UTC string."""
    if not dt_struct:
        return None
    try:
        dt = datetime(*dt_struct[:6])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def first_media_url(entry) -> Optional[str]:
    """Try common RSS media fields: media:content, media:thumbnail, enclosure."""
    mc = getattr(entry, "media_content", None)
    if mc and isinstance(mc, list):
        for m in mc:
            url = m.get("url")
            if url:
                return url
    mt = getattr(entry, "media_thumbnail", None)
    if mt and isinstance(mt, list):
        for m in mt:
            url = m.get("url")
            if url:
                return url
    enc = getattr(entry, "enclosures", None)
    if enc and isinstance(enc, list):
        for e in enc:
            url = e.get("href") or e.get("url")
            if url:
                return url
    return None

def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure every row has a stable non-empty article_id (prefer URL-derived)."""
    cols = [
        "article_id","title","published_time_utc","author","description",
        "url","image_url","source_name","source_feed_url","fetched_at_utc"
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    df = df.fillna("").astype(str)
    # Backfill missing IDs from URL or random
    mask_missing = df["article_id"].str.strip().eq("")
    if mask_missing.any():
        df.loc[mask_missing, "article_id"] = df.loc[mask_missing, "url"].apply(
            lambda u: gen_article_id(u) if u else str(uuid.uuid4())
        )
    return df[cols]

def dedupe_df(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate article_ids, keep first; sort by published time desc; normalize."""
    df = normalize_ids(df)
    if not df.empty:
        df = df.drop_duplicates(subset=["article_id"], keep="first")
    if "published_time_utc" in df.columns:
        dt = pd.to_datetime(df["published_time_utc"], errors="coerce", utc=True)
        df = df.assign(__sort_key=dt).sort_values("__sort_key", ascending=False, kind="stable").drop(columns="__sort_key")
        df["published_time_utc"] = dt.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return normalize_ids(df)

def load_feeds() -> List[str]:
    if FEEDS_JSON.exists():
        try:
            data = json.loads(FEEDS_JSON.read_text(encoding="utf-8"))
            feeds = [f for f in data if isinstance(f, str)]
            return feeds or DEFAULT_FEEDS[:]
        except Exception:
            return DEFAULT_FEEDS[:]
    else:
        FEEDS_JSON.write_text(json.dumps(DEFAULT_FEEDS, ensure_ascii=False, indent=2), encoding="utf-8")
        return DEFAULT_FEEDS[:]

def save_feeds(feeds: List[str]):
    FEEDS_JSON.write_text(json.dumps(feeds, ensure_ascii=False, indent=2))

def seems_like_feed_url(u: str) -> bool:
    """Heuristic: accept URLs that look like RSS/Atom feed endpoints."""
    if not u or "://" not in u:
        return False
    L = u.lower()
    return any(tok in L for tok in (".xml", "/feed", "rss", "atom"))

# -------------------- Fetching --------------------
def fetch_feed_rows(feed_url: str) -> pd.DataFrame:
    fp = feedparser.parse(feed_url)
    fetched_at = datetime.now(timezone.utc).isoformat()
    source_name = s(getattr(fp.feed, "title", None)) or urlparse(feed_url).netloc or SOURCE_FALLBACK

    rows = []
    for e in getattr(fp, "entries", []):
        title = getattr(e, "title", None)
        url = getattr(e, "link", None)
        pub_iso = to_iso(getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None))
        author = getattr(e, "author", None) or e.get("dc_creator") or e.get("creator")
        description = getattr(e, "summary", None) or getattr(e, "description", None)
        image_url = first_media_url(e)

        # NOTE: filtering based on words has been intentionally removed.

        rows.append({
            "article_id": gen_article_id(url),
            "title": s(title),
            "published_time_utc": s(pub_iso),
            "author": s(author),
            "description": s(description),
            "url": s(url),
            "image_url": s(image_url),
            "source_name": s(source_name),
            "source_feed_url": s(feed_url),
            "fetched_at_utc": fetched_at,
        })

    return dedupe_df(pd.DataFrame(rows, dtype=str))

def fetch_all_feeds(feed_urls: List[str]) -> pd.DataFrame:
    frames = []
    for u in feed_urls:
        try:
            frames.append(fetch_feed_rows(u))
        except Exception:
            pass
    if frames:
        df = pd.concat(frames, ignore_index=True)
    else:
        df = pd.DataFrame()
    return dedupe_df(df)

# -------------------- CSV merge cache --------------------
def load_existing() -> pd.DataFrame:
    if CSV_OUT.exists():
        try:
            df = pd.read_csv(CSV_OUT, dtype=str)
            cleaned = dedupe_df(df)
            if len(cleaned) != len(df):
                cleaned.to_csv(CSV_OUT, index=False)
            return cleaned
        except Exception:
            return dedupe_df(pd.DataFrame())
    return dedupe_df(pd.DataFrame())

def save_csv(df: pd.DataFrame):
    dedupe_df(df).to_csv(CSV_OUT, index=False)

def merge_new(existing: pd.DataFrame, freshly: pd.DataFrame):
    """Return (combined_df, new_ids_set)."""
    freshly = dedupe_df(freshly)
    existing = dedupe_df(existing)

    if existing.empty:
        added = freshly
        total = added
        new_ids = set(added["article_id"].tolist())
    else:
        existing_ids = set(existing["article_id"].astype(str))
        freshly["article_id"] = freshly["article_id"].astype(str)
        mask_new = ~freshly["article_id"].isin(existing_ids)
        added = freshly.loc[mask_new]
        total = pd.concat([existing, added], ignore_index=True)
        total = dedupe_df(total)
        new_ids = set(added["article_id"].tolist())

    return total, new_ids

# -------------------- Images --------------------
def ensure_media_dir():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

def local_image_path(article_id: str, image_url: str) -> Path:
    ext = ".jpg"
    if isinstance(image_url, str):
        base = image_url.split("?")[0].lower()
        for guess in (".jpg", ".jpeg", ".png", ".webp"):
            if base.endswith(guess):
                ext = guess
                break
    return MEDIA_DIR / f"{article_id}{ext}"

def download_image(article_id: str, image_url: Optional[str], timeout=10) -> Optional[Path]:
    if not image_url or not isinstance(image_url, str):
        return None
    ensure_media_dir()
    path = local_image_path(article_id, image_url)
    if path.exists():
        return path
    try:
        r = requests.get(image_url, timeout=timeout)
        r.raise_for_status()
        path.write_bytes(r.content)
        return path
    except Exception:
        return None

# -------------------- Feed discovery --------------------
def discover_feed_urls(page_url: str, timeout=10) -> List[str]:
    """Fetch a normal webpage and look for <link rel='alternate' type='application/rss+xml|atom+xml'>."""
    try:
        resp = requests.get(page_url, timeout=timeout, headers={"User-Agent": "FeedDiscovery/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        feeds: List[str] = []
        for link in soup.find_all("link", attrs={"rel": ["alternate", "ALTERNATE"]}):
            typ = (link.get("type") or "").lower()
            if typ in ("application/rss+xml", "application/atom+xml", "application/rdf+xml"):
                href = link.get("href")
                if href:
                    feeds.append(urljoin(page_url, href))
        seen = set(); uniq=[]
        for f in feeds:
            if f not in seen:
                seen.add(f); uniq.append(f)
        return uniq
    except Exception:
        return []

# -------------------- Tkinter App --------------------
class VrtDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Live RSS Monitor (Desktop)")
        self.geometry("1280x800")
        self.minsize(1000, 650)

        # State
        self.feeds = load_feeds()
        self.existing_df = load_existing()
        self.current_df = self.existing_df.copy()
        self.current_image_tk = None
        self.seconds_left = POLL_SECONDS
        self.last_update = None
        self.auto_download_new = tk.BooleanVar(value=True)
        self.iid_to_article_id: Dict[str, str] = {}  # UI iid -> true article_id mapping

        # DB boot check
        try:
            debug_dsn()            # prints DB, schema, user to your console
            ensure_table_exists()  # makes sure the table is there
        except Exception as e:
            print(f"[DB init] {type(e).__name__}: {e}")

        # UI
        self.create_widgets()
        self.populate_table(self.current_df)
        self.bind("<Control-u>", lambda e: self.upsert_selected())

        # Loops
        self.after(1000, self.tick_countdown)             # 1s countdown
        self.after(POLL_SECONDS * 1000, self.poll_once)   # first scheduled poll

    # UI layout
    def create_widgets(self):
        # Top bar
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.status_var = tk.StringVar(value=self.status_line())
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.LEFT)

        ttk.Button(top, text="Upsert selected", command=self.upsert_selected).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Upsert all listed", command=self.upsert_all_listed).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Refresh now", command=self.poll_now).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Export to Excel", command=self.export_excel).pack(side=tk.RIGHT, padx=6)

        # Main split
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=6)

        # Left: table
        left_frame = ttk.Frame(main)
        self.tree = ttk.Treeview(
            left_frame,
            columns=("when", "title", "author", "source"),
            show="headings",
            selectmode="extended",
            height=25
        )
        self.tree.heading("when", text="Published (UTC)")
        self.tree.heading("title", text="Title")
        self.tree.heading("author", text="Author")
        self.tree.heading("source", text="Source")

        self.tree.column("when", width=170, anchor=tk.W)
        self.tree.column("title", width=740, anchor=tk.W)
        self.tree.column("author", width=160, anchor=tk.W)
        self.tree.column("source", width=200, anchor=tk.W)

        vsb = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        self.tree.tag_configure("new", foreground="#0a7", font=("Segoe UI", 9, "bold"))

        left_frame.pack(fill=tk.BOTH, expand=True)
        main.add(left_frame, weight=3)

        # Right: details + sources manager
        right = ttk.Notebook(main)
        main.add(right, weight=2)

        # Tab 1: Details
        details = ttk.Frame(right)
        right.add(details, text="Details")

        self.detail_title = ttk.Label(details, text="Select an article", font=("Segoe UI", 12, "bold"), wraplength=460, justify=tk.LEFT)
        self.detail_title.pack(anchor="w", pady=(0, 6))

        self.detail_meta = ttk.Label(details, text="", wraplength=460, justify=tk.LEFT, foreground="#555")
        self.detail_meta.pack(anchor="w", pady=(0, 8))

        self.image_label = ttk.Label(details)
        self.image_label.pack(anchor="w", pady=(0, 8))

        ttk.Checkbutton(details, text="Auto-download thumbnails for new items", variable=self.auto_download_new).pack(anchor="w", pady=(0,8))

        ttk.Label(details, text="Description:").pack(anchor="w")
        self.detail_desc = ScrolledText(details, height=12, wrap=tk.WORD)
        self.detail_desc.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.detail_desc.configure(state=tk.DISABLED)

        btns = ttk.Frame(details)
        btns.pack(anchor="w", pady=6)
        self.open_btn = ttk.Button(btns, text="Open article in browser", command=self.open_in_browser, state=tk.DISABLED)
        self.open_btn.pack(side=tk.LEFT, padx=4)

        # Selection binding
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # Tab 2: Sources
        sources = ttk.Frame(right)
        right.add(sources, text="Sources")

        src_top = ttk.Frame(sources)
        src_top.pack(fill=tk.X, pady=(6,4))
        ttk.Label(src_top, text="Active RSS/Atom feeds (polled every 10 min):").pack(side=tk.LEFT)

        middle = ttk.Frame(sources)
        middle.pack(fill=tk.BOTH, expand=True)

        self.feeds_list = tk.Listbox(middle, activestyle="dotbox")
        self.refresh_feeds_listbox()
        self.feeds_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6), pady=4)

        side_btns = ttk.Frame(middle)
        side_btns.pack(side=tk.LEFT, fill=tk.Y, pady=4)
        ttk.Button(side_btns, text="Remove selected", command=self.remove_selected_feed).pack(fill=tk.X, pady=2)

        add_frame = ttk.Frame(sources)
        add_frame.pack(fill=tk.X, pady=8)
        ttk.Label(add_frame, text="Add feed URL:").pack(side=tk.LEFT)
        self.add_entry = ttk.Entry(add_frame, width=60)
        self.add_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(add_frame, text="Add", command=self.add_feed).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(add_frame, text="Find feed on page", command=self.find_feed_on_page).pack(side=tk.LEFT)

        tip = ("Use direct RSS/Atom links when possible.\n"
               "Paste a normal page URL and click 'Find feed on page' to auto-discover RSS if exposed.")
        ttk.Label(sources, text=tip, foreground="#666", justify=tk.LEFT).pack(anchor="w", padx=2, pady=(4,8))

    def refresh_feeds_listbox(self):
        self.feeds_list.delete(0, tk.END)
        for f in self.feeds:
            self.feeds_list.insert(tk.END, f)

    def populate_table(self, df: pd.DataFrame, new_ids: Optional[set] = None):
        df = dedupe_df(df)
        self.current_df = df

        self.tree.delete(*self.tree.get_children())
        self.iid_to_article_id.clear()

        new_ids = new_ids or set()
        seen_iids = set()
        for i, (_, row) in enumerate(df.iterrows()):
            true_id = s(row.get("article_id"))
            iid = true_id if true_id else f"row_{i}_{uuid.uuid4().hex[:6]}"
            if iid in seen_iids:
                iid = f"{iid}-{i}"
            seen_iids.add(iid)
            self.iid_to_article_id[iid] = true_id

            when = s(row.get("published_time_utc"))
            title = s(row.get("title"))
            author = s(row.get("author"))
            source = s(row.get("source_name"))
            tags = ("new",) if true_id in new_ids else ()
            self.tree.insert("", tk.END, iid=iid, values=(when, title, author, source), tags=tags)

    # -------- Polling / Countdown --------
    def tick_countdown(self):
        self.seconds_left -= 1
        if self.seconds_left < 0:
            self.seconds_left = 0
        self.status_var.set(self.status_line())
        if self.seconds_left == 0:
            self.poll_once(reschedule=True)
        self.after(1000, self.tick_countdown)

    def status_line(self) -> str:
        mm = self.seconds_left // 60
        ss = self.seconds_left % 60
        nxt = f"Next auto-refresh in {mm:02d}:{ss:02d}"
        if self.last_update:
            return f"{nxt}  |  Last update: {self.last_update}"
        return nxt

    def poll_now(self):
        self.poll_once(reschedule=True)

    def poll_once(self, reschedule=True):
        try:
            fresh = fetch_all_feeds(self.feeds)
            combined, new_ids = merge_new(self.current_df, fresh)

            # Persist to Postgres (non-fatal on error)
            try:
                to_write = combined[combined["article_id"].isin(new_ids)].copy() if new_ids else pd.DataFrame(columns=combined.columns)
                written = upsert_articles(to_write)
                print(f"[DB] Upserted {written} row(s).")
            except Exception as db_err:
                msg = f"DB upsert error: {type(db_err).__name__}: {db_err}"
                self.status_var.set(msg)
                print(msg)

            if new_ids and self.auto_download_new.get():
                for aid in new_ids:
                    r = combined.loc[combined["article_id"] == aid].iloc[0]
                    download_image(aid, s(r.get("image_url")))
            if new_ids:
                save_csv(combined)
                self.populate_table(combined, new_ids=new_ids)
                msg = f"Added {len(new_ids)} new item(s). Total: {len(self.current_df)}"
            else:
                self.populate_table(combined, new_ids=set())
                msg = f"No new items. Total: {len(self.current_df)}"
            self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.seconds_left = POLL_SECONDS
            self.status_var.set(self.status_line() + "  |  " + msg)
        except Exception as e:
            self.status_var.set(f"Polling error: {e}")
        if reschedule:
            self.after(POLL_SECONDS * 1000, self.poll_once)

    # -------- Selection / Details --------
    def on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        article_id = self.iid_to_article_id.get(iid, iid)
        row = self.current_df[self.current_df["article_id"] == article_id]
        if row.empty:
            return
        r = row.iloc[0]

        title = s(r.get("title")) or "(no title)"
        when = s(r.get("published_time_utc"))
        author = s(r.get("author"))
        src = s(r.get("source_name"))
        url = s(r.get("url"))
        desc = s(r.get("description"))
        img_url = s(r.get("image_url"))

        self.detail_title.config(text=title)
        meta_parts = [p for p in [when, author, src] if p]
        self.detail_meta.config(text=" · ".join(meta_parts))

        self.detail_desc.configure(state=tk.NORMAL)
        self.detail_desc.delete("1.0", tk.END)
        self.detail_desc.insert(tk.END, desc)
        self.detail_desc.configure(state=tk.DISABLED)

        self.current_image_tk = None
        self.image_label.config(image="", text="")

        img_path = download_image(article_id, img_url)
        if img_path and img_path.exists():
            try:
                im = Image.open(img_path)
                im.thumbnail((THUMBNAIL_MAX_W, THUMBNAIL_MAX_H))
                self.current_image_tk = ImageTk.PhotoImage(im)
                self.image_label.config(image=self.current_image_tk)
            except Exception:
                self.image_label.config(text="(Image failed to load)")
        else:
            self.image_label.config(text="(No image)")

        self.open_btn.config(state=(tk.NORMAL if url else tk.DISABLED))

    def open_in_browser(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        article_id = self.iid_to_article_id.get(iid, iid)
        row = self.current_df[self.current_df["article_id"] == article_id]
        if row.empty:
            return
        url = s(row.iloc[0].get("url"))
        if url:
            try:
                webbrowser.open(url)
            except Exception as e:
                messagebox.showerror("Open URL", f"Could not open URL:\n{e}")

    def export_excel(self):
        """One-click Excel export (avoids locking during regular polling)."""
        try:
            out_xlsx = Path("vrt_nws_latest.xlsx")
            tmp = out_xlsx.with_name(f"{out_xlsx.stem}.tmp{out_xlsx.suffix}")
            with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
                self.current_df.to_excel(xw, index=False, sheet_name="VRT_NWS")
            os.replace(tmp, out_xlsx)
            messagebox.showinfo("Export", f"Excel exported to:\n{out_xlsx.resolve()}")
        except PermissionError:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            alt = Path(f"vrt_nws_latest_{ts}.xlsx")
            with pd.ExcelWriter(alt, engine="openpyxl") as xw:
                self.current_df.to_excel(xw, index=False, sheet_name="VRT_NWS")
            messagebox.showwarning("Export",
                                   f"Excel file was locked. Wrote fallback:\n{alt.resolve()}")
        except Exception as e:
            messagebox.showerror("Export", f"Failed to export Excel:\n{e}")

    # -------- Manual upsert actions --------
    def get_selection_ids(self) -> List[str]:
        """Return article_ids for the currently selected rows (supports multi-select)."""
        sel_iids = list(self.tree.selection())
        ids: List[str] = []
        for iid in sel_iids:
            aid = self.iid_to_article_id.get(iid, iid)
            if aid:
                ids.append(aid)
        # De-dup, preserve order
        seen = set()
        uniq = []
        for a in ids:
            if a not in seen:
                seen.add(a); uniq.append(a)
        return uniq

    def upsert_dataframe(self, df: pd.DataFrame, label: str):
        """Common helper to upsert a DataFrame and report status."""
        df = dedupe_df(df)
        if df.empty:
            messagebox.showinfo("Upsert", f"No rows to upsert for: {label}")
            return
        try:
            written = upsert_articles(df)
            self.status_var.set(self.status_line() + f"  |  [DB] Upserted {written} row(s) ({label}).")
            messagebox.showinfo("Upsert", f"Upserted {written} row(s) to database.\n\n{label}")
        except Exception as db_err:
            msg = f"DB upsert error: {type(db_err).__name__}: {db_err}"
            self.status_var.set(msg)
            messagebox.showerror("Upsert failed", msg)

    def upsert_selected(self):
        """Upsert only the selected rows in the table."""
        sel_ids = self.get_selection_ids()
        if not sel_ids:
            messagebox.showinfo("Upsert selected", "Select one or more rows first.")
            return
        # Build subset DataFrame by article_id
        df = self.current_df[self.current_df["article_id"].isin(sel_ids)].copy()
        self.upsert_dataframe(df, label=f"Selected {len(sel_ids)} article(s)")

    def upsert_all_listed(self):
        """Upsert all rows currently listed in the table (what you see after filters/merge)."""
        self.upsert_dataframe(self.current_df.copy(), label="All listed articles")


    # -------- Manage sources --------
    def add_feed(self):
        u = s(self.add_entry.get()).strip()
        if not u:
            return
        if not seems_like_feed_url(u):
            messagebox.showwarning(
                "Not a feed URL",
                "This looks like a normal webpage, not an RSS/Atom feed.\n\n"
                "Either paste a direct feed link (often ends in .xml or '/feed'),\n"
                "or use 'Find feed on page' with a normal URL."
            )
            return
        if u in self.feeds:
            messagebox.showinfo("Already added", "That feed is already in your list.")
            return
        try:
            fp = feedparser.parse(u)
            if not getattr(fp, "entries", None):
                raise ValueError("No entries found in this feed.")
        except Exception as e:
            messagebox.showerror("Invalid feed", f"Could not read this feed:\n{e}")
            return

        self.feeds.append(u)
        save_feeds(self.feeds)
        self.refresh_feeds_listbox()
        self.add_entry.delete(0, tk.END)
        messagebox.showinfo("Feed added", "Feed added. It will be included on the next refresh.")

    def find_feed_on_page(self):
        u = s(self.add_entry.get()).strip()
        if not u:
            return
        found = discover_feed_urls(u)
        if not found:
            messagebox.showwarning(
                "No feeds found",
                "No RSS/Atom feeds were discovered on that page.\n"
                "Some sites don't publish public feeds for all sections."
            )
            return
        choices = [f for f in found if f not in self.feeds]
        if not choices:
            messagebox.showinfo("Already added", "Discovered feeds are already in your list.")
            return
        self.feeds.append(choices[0])
        save_feeds(self.feeds)
        self.refresh_feeds_listbox()
        self.add_entry.delete(0, tk.END)
        messagebox.showinfo("Feed discovered",
                            f"Added:\n{choices[0]}\n\nIt will be included on the next refresh.")

    def remove_selected_feed(self):
        sel = list(self.feeds_list.curselection())
        if not sel:
            return
        idx = sel[0]
        url = self.feeds[idx]
        if len(self.feeds) == 1:
            messagebox.showwarning("Cannot remove", "Keep at least one feed.")
            return
        del self.feeds[idx]
        save_feeds(self.feeds)
        self.refresh_feeds_listbox()
        messagebox.showinfo("Feed removed", f"Removed:\n{url}\n\nIt will be excluded on the next refresh.")

# -------------------- Main --------------------
def main():
    # quick connection print + ensure table exists once on startup
    try:
        debug_dsn()
        ensure_table_exists()
    except Exception as e:
        print(f"[DB init] {type(e).__name__}: {e}")

    app = VrtDesktopApp()
    app.mainloop()

if __name__ == "__main__":
    main()
