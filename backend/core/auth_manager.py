import os
import secrets
import time
import logging
import hashlib
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load env variables
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

import sqlite3

# Initialize SQLite database for persistent user registration
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "users.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# MongoDB check & initialization
MONGO_URI = os.getenv("MONGO_URI")
_mongo_db = None

if MONGO_URI:
    try:
        from pymongo import MongoClient
        logger.info("MONGO_URI found! Initializing MongoDB client...")
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        try:
            _mongo_db = _mongo_client.get_default_database()
        except Exception:
            _mongo_db = _mongo_client["resume_ranker"]
        logger.info(f"Connected to MongoDB. Collection 'users' ready.")
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB client: {e}. Falling back to SQLite.")
        _mongo_db = None

def init_db():
    if _mongo_db is not None:
        try:
            _mongo_db.users.create_index("email", unique=True)
            logger.info("MongoDB 'users' collection unique index verified.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB index: {e}")
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    name TEXT,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    is_verified INTEGER DEFAULT 0
                )
            """)
            # Schema migration: check if name column exists, otherwise add it
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN name TEXT")
            except sqlite3.OperationalError:
                pass
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")

init_db()

def create_unverified_user(email: str, name: str, password_hash: str) -> bool:
    email_clean = email.strip().lower()
    name_clean = name.strip() if name else email_clean.split("@")[0].capitalize()
    
    if _mongo_db is not None:
        try:
            _mongo_db.users.update_one(
                {"email": email_clean},
                {
                    "$set": {
                        "email": email_clean,
                        "name": name_clean,
                        "password_hash": password_hash,
                        "created_at": time.time(),
                        "is_verified": False
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to write unverified user to MongoDB: {e}")
            return False
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users (email, name, password_hash, created_at, is_verified)
                VALUES (?, ?, ?, ?, 0)
            """, (email_clean, name_clean, password_hash, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to write unverified user to SQLite: {e}")
            return False

def verify_user_email(email: str) -> bool:
    email_clean = email.strip().lower()
    if _mongo_db is not None:
        try:
            res = _mongo_db.users.update_one(
                {"email": email_clean},
                {"$set": {"is_verified": True}}
            )
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Failed to verify user email in MongoDB: {e}")
            return False
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_verified = 1 WHERE email = ?", (email_clean,))
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success
        except Exception as e:
            logger.error(f"Failed to verify user email in SQLite: {e}")
            return False

def get_user(email: str) -> dict | None:
    email_clean = email.strip().lower()
    if _mongo_db is not None:
        try:
            doc = _mongo_db.users.find_one({"email": email_clean})
            if doc:
                return {
                    "email": doc["email"],
                    "name": doc.get("name", ""),
                    "password_hash": doc["password_hash"],
                    "is_verified": bool(doc.get("is_verified", False))
                }
        except Exception as e:
            logger.error(f"MongoDB query error for user {email_clean}: {e}")
        return None
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("SELECT email, name, password_hash, is_verified FROM users WHERE email = ?", (email_clean,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "email": row[0],
                    "name": row[1],
                    "password_hash": row[2],
                    "is_verified": bool(row[3])
                }
        except Exception as e:
            logger.error(f"Database query error for user {email_clean}: {e}")
        return None

def update_user_name(email: str, name: str) -> bool:
    email_clean = email.strip().lower()
    name_clean = name.strip()
    if _mongo_db is not None:
        try:
            res = _mongo_db.users.update_one(
                {"email": email_clean},
                {"$set": {"name": name_clean}}
            )
            return res.matched_count > 0
        except Exception as e:
            logger.error(f"Failed to update profile name in MongoDB: {e}")
            return False
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET name = ? WHERE email = ?", (name_clean, email_clean))
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success
        except Exception as e:
            logger.error(f"Failed to update profile name in SQLite: {e}")
            return False

def authenticate_user(email: str, password: str) -> bool:
    email_clean = email.strip().lower()
    
    # 1. Check default admin credentials in .env
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123456")
    if email_clean == admin_email and password == admin_password:
        return True
        
    # 2. Check SQLite database
    user = get_user(email_clean)
    if user and user["is_verified"]:
        return verify_password(password, user["password_hash"])
        
    # 3. Fallback: if email is authorized and password matches admin password
    if is_email_authorized(email_clean) and password == admin_password:
        return True
        
    return False

# In-memory session store: token -> {email, expires_at}
SESSION_STORE = {}

# In-memory OTP store: email -> {otp, expires_at}
OTP_STORE = {}

# ── Password Utilities ────────────────────────────────────────────────────────
def hash_password(password: str, salt: str = None) -> str:
    """
    Hashes a password using PBKDF2 HMAC-SHA256.
    Returns: salt:hex_hash
    """
    if not salt:
        salt = secrets.token_hex(16)
    pwd_bytes = password.encode('utf-8')
    salt_bytes = salt.encode('utf-8')
    hash_bytes = hashlib.pbkdf2_hmac('sha256', pwd_bytes, salt_bytes, 100000)
    return f"{salt}:{hash_bytes.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a password against its hash.
    """
    try:
        salt, key_hex = hashed.split(":")
        pwd_bytes = password.encode('utf-8')
        salt_bytes = salt.encode('utf-8')
        hash_bytes = hashlib.pbkdf2_hmac('sha256', pwd_bytes, salt_bytes, 100000)
        return hash_bytes.hex() == key_hex
    except Exception:
        return False

# ── Session Token Management ──────────────────────────────────────────────────
def create_session(email: str) -> str:
    """
    Creates an active session for the email and returns a token.
    """
    token = secrets.token_hex(32)
    # Session lasts for 24 hours
    expires_at = time.time() + (24 * 3600)
    SESSION_STORE[token] = {
        "email": email.strip().lower(),
        "expires_at": expires_at
    }
    return token

def verify_session(token: str) -> str | None:
    """
    Validates a session token and returns the email if active.
    """
    now = time.time()
    
    # Prune expired tokens periodically
    expired = [t for t, data in SESSION_STORE.items() if data["expires_at"] < now]
    for t in expired:
        SESSION_STORE.pop(t, None)
        
    if token in SESSION_STORE:
        data = SESSION_STORE[token]
        if data["expires_at"] > now:
            return data["email"]
        else:
            SESSION_STORE.pop(token, None)
            
    return None

def destroy_session(token: str) -> bool:
    """
    Destroys a session.
    """
    if token in SESSION_STORE:
        SESSION_STORE.pop(token, None)
        return True
    return False

# ── SMTP OTP Management ───────────────────────────────────────────────────────
def generate_otp(email: str) -> str:
    """
    Generates a 6-digit OTP and registers it in the store.
    """
    otp = "".join(secrets.choice("0123456789") for _ in range(6))
    # Valid for 5 minutes
    expires_at = time.time() + 300
    OTP_STORE[email.strip().lower()] = {
        "otp": otp,
        "expires_at": expires_at
    }
    return otp

def verify_otp(email: str, otp: str) -> bool:
    """
    Validates the OTP for an email.
    """
    now = time.time()
    email_clean = email.strip().lower()
    
    # Prune expired OTPs
    expired = [e for e, data in OTP_STORE.items() if data["expires_at"] < now]
    for e in expired:
        OTP_STORE.pop(e, None)
        
    if email_clean in OTP_STORE:
        data = OTP_STORE[email_clean]
        if data["otp"] == otp and data["expires_at"] > now:
            # Code is single-use, delete it after success
            OTP_STORE.pop(email_clean, None)
            return True
            
    return False

def send_otp_email(email: str, otp: str) -> bool:
    """
    Dispatches the OTP code via SMTP. Logs to console/output as fallback.
    """
    email_clean = email.strip().lower()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except (ValueError, TypeError):
        smtp_port = 587
        
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    
    # Print fallback log for ease of testing
    logger.info(f"=========== DEVELOPMENT CODE FOR {email_clean}: {otp} ===========")
    print(f"\n[DEV MODE] OTP verification code for {email_clean} is: {otp}\n", flush=True)
    
    if not smtp_user or not smtp_pass or smtp_user == "example@gmail.com":
        logger.warning("SMTP configuration is incomplete or missing in .env. Login using the fallback printed code above.")
        return True # Return true so testing can proceed with the console log fallback
        
    # Build HTML Message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Verification Code: {otp}"
    msg["From"] = smtp_from
    msg["To"] = email_clean
    
    html_content = f"""
    <html>
      <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f3f4f6; padding: 20px; margin: 0;">
        <div style="max-width: 500px; margin: 20px auto; background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb;">
          <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="color: #3b82f6; margin: 0; font-size: 24px;">Resume Ranker Pro</h2>
            <p style="font-size: 14px; color: #6b7280; margin-top: 5px;">Security Verification Code</p>
          </div>
          <hr style="border: none; border-top: 1px solid #e5e7eb; margin-bottom: 25px;">
          <p style="font-size: 15px; color: #374151; line-height: 1.5; margin: 0 0 15px;">Hello,</p>
          <p style="font-size: 15px; color: #374151; line-height: 1.5; margin: 0 0 25px;">Use the verification code below to log into your Resume Ranker Pro admin account. This code is valid for 5 minutes.</p>
          <div style="text-align: center; margin: 30px 0;">
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #1e3a8a; background-color: #eff6ff; padding: 12px 28px; border-radius: 8px; border: 1px dashed #bfdbfe; display: inline-block;">{otp}</span>
          </div>
          <p style="font-size: 13px; color: #ef4444; font-weight: 500; margin: 25px 0 0;">If you did not request this authentication, please ignore this email or update your credentials.</p>
          <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0 15px;">
          <p style="font-size: 11px; color: #9ca3af; text-align: center; margin: 0;">This is an automated notification. Please do not reply directly.</p>
        </div>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(f"Your verification code is: {otp}", "plain"))
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        retries = int(os.getenv("SMTP_RETRIES", "5"))
        backoff = float(os.getenv("SMTP_BACKOFF_BASE", "2.0"))
    except (ValueError, TypeError):
        retries = 5
        backoff = 2.0
        
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Connecting to SMTP server {smtp_host}:{smtp_port} (Attempt {attempt}/{retries})...")
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
                server.ehlo()
                server.starttls()
                server.ehlo()
                
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, email_clean, msg.as_string())
            server.quit()
            logger.info("SMTP OTP code email sent successfully.")
            return True
        except Exception as e:
            logger.error(f"SMTP error on attempt {attempt}: {e}")
            if attempt < retries:
                sleep_time = backoff ** attempt
                logger.info(f"Sleeping for {sleep_time:.1f}s before retrying...")
                time.sleep(sleep_time)
            else:
                logger.error("All SMTP attempts failed.")
                
    return False

# ── Google OAuth Token Exchange ───────────────────────────────────────────────
def exchange_google_code(code: str) -> dict | None:
    """
    Exchanges OAuth auth code with Google API.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")
    
    if not client_id or not client_secret or client_id.startswith("your-") or client_secret.startswith("your-"):
        logger.warning("Google OAuth credentials are not fully configured in .env.")
        return None
        
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    try:
        logger.info("Exchanging auth code with Google endpoint...")
        res = requests.post(token_url, data=payload, timeout=10)
        res.raise_for_status()
        tokens = res.json()
        
        access_token = tokens.get("access_token")
        if not access_token:
            logger.error("Missing access_token in Google OAuth exchange.")
            return None
            
        # Retrieve user email details
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        user_res = requests.get(userinfo_url, headers=headers, timeout=10)
        user_res.raise_for_status()
        
        return user_res.json()
    except Exception as e:
        logger.error(f"Google OAuth token exchange failed: {e}")
        return None

def is_email_authorized(email: str) -> bool:
    """
    Checks if an email is authorized. Returns True for all valid email addresses.
    """
    if not email:
        return False
    email_clean = email.strip().lower()
    return "@" in email_clean and "." in email_clean.split("@")[1]

def send_user_notification(
    recipient_email: str,
    name: str,
    subject: str,
    event_title: str,
    message_body: str,
    event_type: str = "info"  # "login", "logout", "register", "info"
) -> bool:
    """
    Sends a user notification email directly to the recruiter's email account with neat UI.
    Supports dynamic styles (login, logout, register) and custom time labels.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except (ValueError, TypeError):
        smtp_port = 587
        
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    
    recipient = recipient_email.strip().lower()
    user_name = name.strip() if name else recipient.split("@")[0].capitalize()
    
    from datetime import datetime
    current_time = datetime.now().strftime("%B %d, %Y - %I:%M %p")
    
    # Customise styling parameters based on event_type
    if event_type == "login":
        time_label = "Login Time"
        theme_color = "#3b82f6"  # Blue
        bg_header = "linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%)"
        bg_card = "#eff6ff"
        border_card = "#bfdbfe"
        status_text = "🟢 Active Session Started"
        icon_emoji = "🔑"
    elif event_type == "logout":
        time_label = "Logout Time"
        theme_color = "#4b5563"  # Gray
        bg_header = "linear-gradient(135deg, #374151 0%, #4b5563 100%)"
        bg_card = "#f3f4f6"
        border_card = "#e5e7eb"
        status_text = "⚪ Session Terminated"
        icon_emoji = "🔓"
    elif event_type == "register":
        time_label = "Verification Time"
        theme_color = "#10b981"  # Emerald
        bg_header = "linear-gradient(135deg, #047857 0%, #10b981 100%)"
        bg_card = "#ecfdf5"
        border_card = "#a7f3d0"
        status_text = "🟢 Profile Active & Verified"
        icon_emoji = "🎉"
    else:
        time_label = "Activity Time"
        theme_color = "#6366f1"  # Indigo
        bg_header = "linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)"
        bg_card = "#f5f3ff"
        border_card = "#ddd6fe"
        status_text = "✅ Success"
        icon_emoji = "🔔"

    logger.info(f"[USER NOTIFICATION] Recipient: {recipient} | Name: {user_name} | Subject: {subject} | Type: {event_type}")
    print(f"\n[USER NOTIFICATION] Sending to {user_name} ({recipient}) [{event_type}]: {subject}\n{message_body}\n", flush=True)
    
    if not smtp_user or not smtp_pass or smtp_user == "example@gmail.com":
        logger.warning("SMTP username or password not configured in .env. Skipping notification email.")
        return True
        
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient
    
    # Beautiful responsive HTML/CSS template
    html_content = f"""
    <html>
      <body style="font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f3f4f6; padding: 15px; margin: 0;">
        <div style="max-width: 500px; width: 100%; margin: 0 auto; background-color: #ffffff; border-radius: 16px; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05); overflow: hidden; border: 1px solid #e5e7eb; box-sizing: border-box;">
          
          <!-- Header Logo/Title with dynamic gradient -->
          <div style="background: {bg_header}; padding: 25px 20px; text-align: center; color: white; box-sizing: border-box;">
            <div style="display: inline-block; background-color: rgba(255, 255, 255, 0.2); color: white; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 16px; margin-bottom: 8px; backdrop-filter: blur(5px);">
              {icon_emoji} Resume Ranker Pro
            </div>
            <h2 style="margin: 0; font-size: 18px; font-weight: 700; letter-spacing: -0.01em;">Security Alert & System Activity</h2>
          </div>
          
          <div style="padding: 24px; box-sizing: border-box;">
            <!-- Greeting -->
            <p style="font-size: 16px; color: #111827; font-weight: 600; margin-top: 0; margin-bottom: 12px;">Hello, {user_name} 👋</p>
            <p style="font-size: 14px; color: #4b5563; line-height: 1.5; margin-top: 0; margin-bottom: 20px;">
              This is a secure confirmation of a recent activity on your recruiter profile. Below are the authentication logs for your records.
            </p>
            
            <!-- Activity Details Card (Vertical responsive blocks to prevent horizontal clipping) -->
            <div style="background-color: {bg_card}; border: 1px solid {border_card}; border-radius: 12px; padding: 18px; margin-bottom: 20px; box-sizing: border-box;">
              <h4 style="color: {theme_color}; margin-top: 0; margin-bottom: 16px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700;">
                Activity Log Summary
              </h4>
              
              <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px;">
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Recruiter Name</div>
                <div style="font-size: 14px; color: #111827; font-weight: 700; word-wrap: break-word; word-break: break-all;">{user_name}</div>
              </div>
              
              <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px;">
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Account Email</div>
                <div style="font-size: 13px; color: #111827; font-family: monospace; word-wrap: break-word; word-break: break-all;">{recipient}</div>
              </div>
              
              <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px;">
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Event Name</div>
                <div style="font-size: 14px; color: #111827; font-weight: 700;">{event_title}</div>
              </div>
              
              <div style="margin-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px;">
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">{time_label}</div>
                <div style="font-size: 14px; color: #111827; font-weight: 700; font-family: monospace;">{current_time}</div>
              </div>
              
              <div>
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; text-transform: uppercase; margin-bottom: 2px;">Current Status</div>
                <div style="font-size: 14px; color: #111827; font-weight: 700;">{status_text}</div>
              </div>
            </div>
            
            <!-- Detailed Message -->
            <div style="font-size: 13px; color: #4b5563; line-height: 1.5; margin-top: 0; margin-bottom: 20px; border-left: 4px solid {theme_color}; padding-left: 12px; font-style: italic;">
              "{message_body}"
            </div>
            
            <!-- Security Warning Footnote -->
            <div style="background-color: #fffaf0; border: 1px solid #feebc8; border-radius: 8px; padding: 12px; margin-bottom: 20px; box-sizing: border-box;">
              <p style="font-size: 11px; color: #dd6b20; margin: 0; line-height: 1.4; font-weight: 500;">
                🛡️ <b>Security Reminder:</b> If this action was not initiated by you, please update your recruiter account password immediately to secure your candidate database.
              </p>
            </div>
            
            <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 24px 0 16px;">
            
            <!-- Footer -->
            <p style="font-size: 11px; color: #9ca3af; text-align: center; margin: 0; line-height: 1.4;">
              This is an automated safety alert sent directly to your registered recruiter address.<br>
              Please do not reply directly to this email.
            </p>
          </div>
          
        </div>
      </body>
    </html>
    """
    
    plain_text = f"Hello {user_name},\n\nThis is an alert to confirm a recent activity: {event_title}.\n{time_label}: {current_time}\nStatus: {status_text}\n\nDetail: {message_body}"
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
            
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, recipient, msg.as_string())
        server.quit()
        logger.info(f"User email notification sent successfully to {recipient}.")
        return True
    except Exception as e:
        logger.error(f"Failed to send user email notification to {recipient}: {e}")
        return False

