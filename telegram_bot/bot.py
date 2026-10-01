"""
NIKOLA Telegram Bot - Full implementation with all commands and handlers.
"""

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
import platform

import httpx
import psutil
import pyautogui
from PIL import Image
from telegram import Update, File
from telegram.ext import (
    Application, ContextTypes, CommandHandler,
    MessageHandler, filters, ConversationHandler,
    CallbackQueryHandler
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
import sys
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from backend.logger import get_logger

logger = get_logger(__name__)

# Security guard & allowlist
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
_allowed_raw = os.getenv("TELEGRAM_ALLOWED_USERS", str(ALLOWED_USER_ID))
TELEGRAM_ALLOWED_USERS = set(int(u.strip()) for u in _allowed_raw.split(",") if u.strip().lstrip('-').isdigit())
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
NIKOLA_API_KEY = os.getenv("NIKOLA_API_KEY", "")

_original_async_client = httpx.AsyncClient

class NikolaAsyncClient(_original_async_client):
    def __init__(self, *args, **kwargs):
        headers = dict(kwargs.pop('headers', {}) or {})
        headers['X-API-Key'] = NIKOLA_API_KEY
        kwargs['headers'] = headers
        super().__init__(*args, **kwargs)

httpx.AsyncClient = NikolaAsyncClient

# Conversation states
ASKING = 1
CLEARING = 2

# Rate limiting tracker: {user_id: [timestamp1, timestamp2, ...]}
from collections import defaultdict
_user_request_timestamps = defaultdict(list)

async def check_authorization(update: Update) -> bool:
    """Check if user is authorized and rate limited. Log unauthorized attempts."""
    user_id = update.effective_user.id if update.effective_user else 0
    username = update.effective_user.username if update.effective_user else "unknown"
    
    if user_id not in TELEGRAM_ALLOWED_USERS and user_id != ALLOWED_USER_ID:
        logger.warning(
            "Unauthorized access attempt",
            user_id=user_id,
            username=username,
            timestamp=datetime.utcnow().isoformat()
        )
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return False
    
    # Rate limiting: Max 10 requests per user per minute
    now = time.time()
    _user_request_timestamps[user_id] = [t for t in _user_request_timestamps[user_id] if now - t < 60]
    if len(_user_request_timestamps[user_id]) >= 10:
        logger.warning("Rate limit exceeded", user_id=user_id)
        if update.message:
            await update.message.reply_text("Warning: Rate limit exceeded (max 10 requests per minute).")
        return False
    _user_request_timestamps[user_id].append(now)
    return True


# === Command Handlers ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start - System info."""
    if not await check_authorization(update):
        return
    
    try:
        # Get system info
        cpu_percent = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime = psutil.boot_time()
        
        message = f"""I am **Nikola**, your local AI agent\\.

**System Status:**
\\- OS: `{platform.system()} {platform.release()}`
\\- CPU: `{cpu_percent}%`
\\- RAM: `{ram.used // (1024**3)} / {ram.total // (1024**3)} GB`
\\- Disk: `{disk.used // (1024**3)} / {disk.total // (1024**3)} GB`
\\- Boot Time: `{datetime.fromtimestamp(uptime).strftime('%Y-%m-%d %H:%M:%S')}`"""
        
        await update.message.reply_text(message, parse_mode="MarkdownV2")
        logger.info("Start command executed")
    
    except Exception as e:
        logger.error("Start command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /ask - Ask question."""
    if not await check_authorization(update):
        return ConversationHandler.END
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /ask <question>")
            return ConversationHandler.END
        
        query = " ".join(args)
        
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{BACKEND_URL}/ask",
                json={"query": query, "use_rag": True, "source": "telegram"}
            )
            
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "")
                sources = data.get("sources", [])
                
                message = answer
                if sources:
                    message += "\n\n**Sources:**"
                    for source in sources:
                        message += f"\n• {source}"
                
                # Escape markdown
                message = message.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
                
                await update.message.reply_text(message, parse_mode="MarkdownV2")
                logger.info("Ask command executed", query=query[:50])
            else:
                await update.message.reply_text(f"Backend error: {response.status_code}")
                logger.error("Ask backend error", status=response.status_code)
    
    except Exception as e:
        logger.error("Ask command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")
    
    return ConversationHandler.END


async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /screenshot - Send desktop screenshot."""
    if not await check_authorization(update):
        return
    
    try:
        await update.message.reply_text("Processing... ⏳")
        
        loop = asyncio.get_event_loop()
        
        # Take screenshot
        async def get_screenshot():
            return await loop.run_in_executor(None, pyautogui.screenshot)
        
        img = await get_screenshot()
        
        # Save to temp file (Windows-safe)
        import tempfile
        temp_file = os.path.join(tempfile.gettempdir(), "nikola_screenshot.jpg")
        img.save(temp_file, "JPEG", quality=85)
        
        # Send photo
        with open(temp_file, "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption=f"Live desktop — {datetime.utcnow().isoformat()}"
            )
        
        logger.info("Screenshot sent")
    
    except Exception as e:
        logger.error("Screenshot command failed", error=str(e))
        await update.message.reply_text(f"Screenshot failed: {str(e)}")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /get - Retrieve indexed file."""
    if not await check_authorization(update):
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /get <filename>")
            return
        
        filename = " ".join(args)
        
        # Check if absolute path
        abs_path = Path(filename)
        found_paths = []
        if abs_path.is_absolute() and abs_path.is_file():
            found_paths = [abs_path]
        else:
            # Search in vault, Downloads, and Desktop
            for base in [Path.home() / "vault", Path.home() / "Downloads", Path.home() / "Desktop"]:
                if not base.exists():
                    continue
                for file in base.rglob("*"):
                    if filename.lower() in file.name.lower() and file.is_file():
                        found_paths.append(file)
        
        if not found_paths:
            await update.message.reply_text("File not found. Use /list.")
            return
        
        # Send first found file
        file_path = found_paths[0]
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=file_path.name)
        
        logger.info("File sent", filename=file_path.name)
    
    except Exception as e:
        logger.error("Get command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list - Get indexing status."""
    if not await check_authorization(update):
        return
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Get status
            status_response = await client.get(f"{BACKEND_URL}/status")
            
            # Get files
            files_response = await client.get(f"{BACKEND_URL}/rag/files")
            
            if status_response.status_code == 200 and files_response.status_code == 200:
                status = status_response.json()
                files_data = files_response.json()
                
                uptime = status.get("uptime_seconds", 0)
                uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"
                
                message = f"**Index Status**\n"
                message += f"Uptime: `{uptime_str}`\n"
                message += f"Files: `{files_data.get('total_files', 0)}`\n"
                message += f"Chunks: `{files_data.get('total_chunks', 0)}`\n\n"
                
                files = files_data.get("files", [])
                if files:
                    message += "**Indexed Files:**\n"
                    for file in files:
                        size_mb = file.get("size_bytes", 0) / (1024**2)
                        message += f"• `{file.get('filename')}` — `{file.get('chunks')}` chunks — `{size_mb:.1f}` MB\n"
                
                await update.message.reply_text(message)
                logger.info("List command executed")
            else:
                await update.message.reply_text("Backend error")
    
    except Exception as e:
        logger.error("List command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /solve - Analyze screen."""
    if not await check_authorization(update):
        return
    
    try:
        await update.message.reply_text("Scanning screen... ⏳")
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{BACKEND_URL}/solve-screen")
            
            if response.status_code == 200:
                data = response.json()
                description = data.get("description", "")
                solution = data.get("solution", "")
                
                message = f"👁 **What I see:**\n{description}\n\n💡 **Solution:**\n{solution}"
                await update.message.reply_text(message)
                logger.info("Solve command executed")
            else:
                await update.message.reply_text("Solve failed")
    
    except Exception as e:
        logger.error("Solve command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def remember_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remember - Save profile field."""
    if not await check_authorization(update):
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /remember <field> <value>")
            return
        
        field = args[0]
        value = " ".join(args[1:])
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{BACKEND_URL}/autofill/profile",
                params={"field": field, "value": value}
            )
            
            if response.status_code == 200:
                masked_value = value[:2] + "***"
                await update.message.reply_text(f"Remembered: {field} = {masked_value}")
                logger.info("Remember command executed", field=field)
            else:
                await update.message.reply_text("Remember failed")
    
    except Exception as e:
        logger.error("Remember command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profile - Show profile fields."""
    if not await check_authorization(update):
        return
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BACKEND_URL}/autofill/profile")
            
            if response.status_code == 200:
                data = response.json()
                fields = data.get("fields", [])
                
                message = "**Profile Fields:**\n"
                if fields:
                    for field in fields:
                        message += f"• `{field}`\n"
                else:
                    message += "No fields saved yet."
                
                message = message.replace("_", "\\_")
                await update.message.reply_text(message, parse_mode="MarkdownV2")
                logger.info("Profile command executed")
            else:
                await update.message.reply_text("Get profile failed")
    
    except Exception as e:
        logger.error("Profile command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /files - RAG file list."""
    if not await check_authorization(update):
        return
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BACKEND_URL}/rag/files")
            
            if response.status_code == 200:
                data = response.json()
                files = data.get("files", [])
                
                message = f"**Indexed files \\({len(files)}\\):**\n"
                
                for file in files:
                    chunks = file.get("chunks", 0)
                    size_mb = file.get("size_bytes", 0) / (1024**2)
                    filename = file.get("filename", "")
                    
                    message += f"• `{filename}` — `{chunks}` chunks — `{size_mb:.1f}` MB\n"
                
                message = message.replace("_", "\\_")
                await update.message.reply_text(message, parse_mode="MarkdownV2")
                logger.info("Files command executed")
            else:
                await update.message.reply_text("Get files failed")
    
    except Exception as e:
        logger.error("Files command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove - Remove indexed file."""
    if not await check_authorization(update):
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /remove <filename>")
            return
        
        filename = " ".join(args)
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{BACKEND_URL}/rag/remove",
                json={"filename": filename}
            )
            
            if response.status_code == 200:
                data = response.json()
                chunks = data.get("chunks_deleted", 0)
                await update.message.reply_text(f"Removed: `{filename}` — `{chunks}` chunks")
                logger.info("Remove command executed", filename=filename)
            elif response.status_code == 404:
                await update.message.reply_text("File not found")
            else:
                await update.message.reply_text("Remove failed")
    
    except Exception as e:
        logger.error("Remove command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def clearall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /clearall - Start clear confirmation."""
    if not await check_authorization(update):
        return ConversationHandler.END
    
    message = "⚠️ **Warning:** This will delete ALL indexed files and profile data. Are you sure?\n\nReply with /confirmclear within 30 seconds to proceed."
    message = message.replace("_", "\\_").replace("*", "\\*")
    
    await update.message.reply_text(message, parse_mode="MarkdownV2")
    
    # Store pending flag
    context.user_data["pending_clear"] = time.time()
    logger.info("Clear all initiated")
    
    return CLEARING


async def confirmclear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /confirmclear - Execute clear."""
    if not await check_authorization(update):
        return ConversationHandler.END
    
    try:
        # Check if clear was initiated and pending
        pending_time = context.user_data.get("pending_clear")
        if not pending_time or time.time() - pending_time > 30:
            await update.message.reply_text("Clear timeout or not initiated. Use /clearall first.")
            return ConversationHandler.END
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{BACKEND_URL}/rag/clear-all",
                json={"confirm": True}
            )
            
            if response.status_code == 200:
                data = response.json()
                chunks = data.get("chunks_deleted", 0)
                files = data.get("files_removed", 0)
                
                await update.message.reply_text(
                    f"✅ Cleared: `{chunks}` chunks, `{files}` files",
                    parse_mode="MarkdownV2"
                )
                logger.info("Clear all executed", chunks=chunks, files=files)
            else:
                await update.message.reply_text("Clear failed")
        
        context.user_data.pop("pending_clear", None)
    
    except Exception as e:
        logger.error("Confirmclear command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")
    
    return ConversationHandler.END


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /run - Execute shell command (disabled by default)."""
    if not await check_authorization(update):
        return
    
    if not os.getenv("RUN_COMMANDS", "false").lower() == "true":
        await update.message.reply_text("Shell execution is disabled.")
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /run <command>")
            return
        
        cmd = " ".join(args)
        
        loop = asyncio.get_event_loop()
        
        async def run_cmd():
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            output = stdout.decode()[:4000]
            if stderr:
                output += "\n" + stderr.decode()[:2000]
            
            return output
        
        output = await run_cmd()
        formatted = f"`{output}`"
        formatted = formatted.replace("_", "\\_").replace("*", "\\*")
        
        await update.message.reply_text(formatted, parse_mode="MarkdownV2")
        logger.info("Run command executed", cmd=cmd[:50])
    
    except Exception as e:
        logger.error("Run command failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


# === Message Handler ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command text messages."""
    if not await check_authorization(update):
        return
    
    try:
        text = update.message.text
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{BACKEND_URL}/nl/command",
                json={"text": text}
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("auto_executed") is False and data.get("interpretations"):
                    keyboard = []
                    for interp in data.get("interpretations", [])[:3]:
                        desc = interp.get("description", "")
                        conf = int(interp.get("confidence", 0) * 100)
                        intent = interp.get("intent", "")
                        cb_data = f"intent_{intent}:{text[:30]}"
                        keyboard.append([InlineKeyboardButton(f"{desc} ({conf}%)", callback_data=cb_data)])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text("I'm not sure what you meant. Did you mean:", reply_markup=reply_markup)
                    return
                
                if data.get("action") == "screenshot":
                    result = data.get("result", {})
                    file_path = result.get("file")
                    if file_path and Path(file_path).exists():
                        with open(file_path, "rb") as f:
                            await update.message.reply_photo(photo=f)
                        Path(file_path).unlink()
                else:
                    description = data.get("description", "")
                    success = data.get("success", False)
                    
                    message = description
                    if data.get("was_healed"):
                        message += f"\n\n↻ {data.get('healing_explanation')}"
                        
                    if not success and data.get("error"):
                        message += f"\n\nError: {data.get('error')}"
                    else:
                        result_data = data.get("result", {})
                        if result_data:
                            import json
                            formatted_result = json.dumps(result_data, indent=2)
                            if len(formatted_result) > 3000:
                                formatted_result = formatted_result[:3000] + "\n...[truncated]"
                            message += f"\n\nResults:\n```json\n{formatted_result}\n```"
                    await update.message.reply_text(message)
                
                logger.info("Message handled", text=text[:50])
            else:
                await update.message.reply_text("Backend error")
    
    except Exception as e:
        logger.error("Message handler failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


# === Voice Handler ===

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages."""
    if not await check_authorization(update):
        return
    
    try:
        voice = update.message.voice
        
        # Download audio
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        
        # Transcribe
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{BACKEND_URL}/voice/transcribe",
                files={"file": ("audio.ogg", audio_bytes)}
            )
            
            if response.status_code == 200:
                data = response.json()
                transcript = data.get("text", "")
                
                # Process as NL command
                nl_response = await client.post(
                    f"{BACKEND_URL}/nl/command",
                    json={"text": transcript}
                )
                
                if nl_response.status_code == 200:
                    nl_data = nl_response.json()
                    description = nl_data.get("description", "")
                    
                    message = f"**Heard:** {transcript}\n\n{description}"
                    message = message.replace("_", "\\_").replace("*", "\\*")
                    
                    await update.message.reply_text(message, parse_mode="MarkdownV2")
                    logger.info("Voice processed", text=transcript[:50])
                else:
                    await update.message.reply_text(f"Heard: {transcript}")
            else:
                await update.message.reply_text("Transcription failed")
    
    except Exception as e:
        logger.error("Voice handler failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


# === File Handler ===

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file uploads."""
    if not await check_authorization(update):
        return
    
    try:
        document = update.message.document
        
        # Download file to vault
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        
        vault_path = Path.home() / "vault"
        vault_path.mkdir(exist_ok=True)
        
        file_path = vault_path / document.file_name
        file_path.write_bytes(file_bytes)
        
        # Index file
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{BACKEND_URL}/index",
                json={"file_path": str(file_path)}
            )
            
            if response.status_code == 200:
                data = response.json()
                chunks = data.get("chunks_added", 0)
                
                await update.message.reply_text(
                    f"Indexed: `{document.file_name}` — `{chunks}` chunks",
                    parse_mode="MarkdownV2"
                )
                logger.info("File indexed", filename=document.file_name, chunks=chunks)
            else:
                await update.message.reply_text("Indexing failed")
    
    except Exception as e:
        logger.error("File handler failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")


async def browse_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update): return
    try:
        target_dir = " ".join(context.args) if context.args else os.getenv("VAULT_PATH", "C:/")
        target_path = Path(target_dir)
        if not target_path.exists() or not target_path.is_dir():
            await update.message.reply_text(f"Directory not found: `{target_dir}`", parse_mode="MarkdownV2")
            return
        
        items = list(target_path.iterdir())
        dirs = [d.name + "/" for d in items if d.is_dir()]
        files = [f.name for f in items if f.is_file()]
        
        message = f"📁 *{target_path.absolute()}*\n\n"
        if dirs:
            message += "*Directories:*\n" + "\n".join([f"`{d}`" for d in dirs[:20]]) + "\n\n"
        if files:
            message += "*Files:*\n" + "\n".join([f"`{f}`" for f in files[:20]])
            
        if len(items) > 40:
            message += f"\n\n_...and {len(items) - 40} more items_"
            
        # Escape markdown v2 reserved chars except the ones we explicitly used manually above
        # Safest is just using Markdown, not MarkdownV2, because filenames have crazy chars
        await update.message.reply_text(message, parse_mode="Markdown")
        logger.info("Browse command executed", path=str(target_path))
    except Exception as e:
        logger.error("Browse failed", error=str(e))
        await update.message.reply_text(f"Error: {str(e)}")

async def cat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update): return
    try:
        if not context.args:
            await update.message.reply_text("Usage: /cat <filepath>")
            return
            
        target_file = Path(" ".join(context.args))
        if not target_file.exists() or not target_file.is_file():
            await update.message.reply_text("File not found.")
            return
            
        content = target_file.read_text(encoding='utf-8', errors='replace')
        if len(content) > 3000:
            content = content[:3000] + "\n\n...[TRUNCATED]"
            
        await update.message.reply_text(f"📄 *{target_file.name}*\n```text\n{content}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update): return
    try:
        if not context.args:
            await update.message.reply_text("Usage: /search <query>")
            return
            
        query = " ".join(context.args).lower()
        vault = Path(os.getenv("VAULT_PATH", "C:/"))
        
        await update.message.reply_text(f"🔍 Searching for '{query}' in {vault}...")
        
        results = []
        for path in vault.rglob(f"*{query}*"):
            if path.is_file():
                results.append(str(path.relative_to(vault) if vault in path.parents else path))
            if len(results) >= 20:
                break
                
        if results:
            msg = "*Found:*\n" + "\n".join([f"`{p}`" for p in results])
        else:
            msg = "No results found."
            
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def workflows_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_authorization(update): return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BACKEND_URL}/workflow/list")
            if response.status_code == 200:
                workflows = response.json()
                if not workflows:
                    await update.message.reply_text("No workflows yet.")
                    return
                for wf in workflows:
                    actions = " → ".join([a[0] for a in wf.get('actions', [])])
                    freq = wf.get('frequency', 0)
                    hash_val = wf.get('pattern_hash')
                    keyboard = [
                        [
                            InlineKeyboardButton("▶ Run", callback_data=f"wf_run_{hash_val}"),
                            InlineKeyboardButton("🗑 Delete", callback_data=f"wf_del_{hash_val}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(f"`{actions}`\nUsed: {freq}x", reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await update.message.reply_text("Failed to get workflows.")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    try:
        if data.startswith("wf_run_"):
            hash_val = data[7:]
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(f"{BACKEND_URL}/workflow/execute", json={"pattern_hash": hash_val})
                if res.status_code == 200:
                    await query.edit_message_text(f"{query.message.text}\n\n✅ Executed workflow.")
                else:
                    await query.edit_message_text(f"{query.message.text}\n\n❌ Execution failed.")
        elif data.startswith("wf_del_"):
            hash_val = data[7:]
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.delete(f"{BACKEND_URL}/workflow/{hash_val}")
                if res.status_code == 200:
                    await query.edit_message_text(f"{query.message.text}\n\n🗑 Deleted.")
        elif data.startswith("intent_"):
            parts = data.split(":", 1)
            intent = parts[0][7:]
            text = parts[1] if len(parts) > 1 else ""
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(f"{BACKEND_URL}/nl/execute-intent", json={"query": text, "chosen_intent": intent})
                if res.status_code == 200:
                    result_data = res.json()
                    msg = result_data.get("description", "Executed.")
                    if result_data.get("was_healed"):
                        msg += f"\n\n↻ {result_data.get('healing_explanation')}"
                    await query.edit_message_text(f"Executed: {msg}")
    except Exception as e:
        logger.error(f"Callback error: {e}")




# === Main ===

def _kill_other_bot_instances():
    """Kill any other bot.py processes to prevent 409 Conflict."""
    import os as _os
    import sys
    import tempfile
    
    lock_file = _os.path.join(tempfile.gettempdir(), "nikola_bot.lock")
    try:
        # Open lockfile exclusively
        if _os.path.exists(lock_file):
            try:
                _os.remove(lock_file)
            except OSError:
                pass # Currently locked by active bot
                
        fd = _os.open(lock_file, _os.O_CREAT | _os.O_EXCL | _os.O_RDWR)
        # Keep open for duration of script
        _os.environ['_NIKOLA_LOCK_FD'] = str(fd)
    except OSError:
        # File is locked! Gracefully exit because another bot is running.
        logger.info("Another bot instance is running. Shutting down gracefully natively.")
        sys.exit(0)


async def main():
    """Start the Telegram bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set")
        return
    
    # Kill any other running bot instances first
    _kill_other_bot_instances()
    await asyncio.sleep(2)  # Let Telegram release the polling lock
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("screenshot", screenshot_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("solve", solve_command))
    app.add_handler(CommandHandler("remember", remember_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("files", files_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("browse", browse_command))
    app.add_handler(CommandHandler("ls", browse_command))
    app.add_handler(CommandHandler("cat", cat_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("workflows", workflows_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Conversation handlers
    ask_handler = ConversationHandler(
        entry_points=[CommandHandler("ask", ask_command)],
        states={ASKING: [MessageHandler(filters.TEXT, ask_command)]},
        fallbacks=[CommandHandler("ask", ask_command)],
        conversation_timeout=300
    )
    
    clearall_handler = ConversationHandler(
        entry_points=[CommandHandler("clearall", clearall_command)],
        states={CLEARING: [CommandHandler("confirmclear", confirmclear_command)]},
        fallbacks=[CommandHandler("clearall", clearall_command)],
        conversation_timeout=30
    )
    
    app.add_handler(ask_handler)
    app.add_handler(clearall_handler)
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    logger.info("Telegram bot started")
    
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        # Keep the bot running
        import signal
        stop_event = asyncio.Event()
        def set_stop(*args): stop_event.set()
        if platform.system() != 'Windows':
            asyncio.get_running_loop().add_signal_handler(signal.SIGINT, set_stop)
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, set_stop)
        else:
            # simple sleep loop on windows
            while not stop_event.is_set():
                await asyncio.sleep(1)
                
    except Exception as e:
        logger.error("Bot startup failed", error=str(e))
    finally:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
