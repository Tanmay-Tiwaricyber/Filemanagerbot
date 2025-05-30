import logging
import json
import os
import re
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
    ContextTypes
)

# Configuration
TOKEN = "" #add your bot token
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
FILE_STORE_PATH = os.path.join(DATA_DIR, "file_store.json")
FILE_STORE_BATCH_PATH = os.path.join(DATA_DIR, "file_store_batch.json")
STATS_PATH = os.path.join(DATA_DIR, "stats.json")
BATCHES_PATH = os.path.join(DATA_DIR, "batches.json")
REQUESTS_PATH = os.path.join(DATA_DIR, "requests.json")
REVIEWS_PATH = os.path.join(DATA_DIR, "reviews.json")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class FileManager:
    @staticmethod
    def load_data(filepath: str, default=None):
        if default is None:
            default = {}
        try:
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
        return default

    @staticmethod
    def save_data(filepath: str, data):
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving {filepath}: {e}")

class BotDatabase:
    def __init__(self):
        self.file_store = FileManager.load_data(FILE_STORE_PATH)
        self.file_store_batch = FileManager.load_data(FILE_STORE_BATCH_PATH)
        self.stats = FileManager.load_data(STATS_PATH, {
            "downloads": {},
            "users": {},
            "batch_downloads": {}
        })
        self.batches = FileManager.load_data(BATCHES_PATH)
        self.requests = FileManager.load_data(REQUESTS_PATH)
        self.reviews = FileManager.load_data(REVIEWS_PATH)

    def save_all(self):
        FileManager.save_data(FILE_STORE_PATH, self.file_store)
        FileManager.save_data(os.path.join(DATA_DIR, "file_store_batch.json"), self.file_store_batch)
        FileManager.save_data(STATS_PATH, self.stats)
        FileManager.save_data(BATCHES_PATH, self.batches)
        FileManager.save_data(REQUESTS_PATH, self.requests)
        FileManager.save_data(REVIEWS_PATH, self.reviews)

db = BotDatabase()

# ======================
# Core Bot Functionality
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📦 View Batches", callback_data="cmd_listbatches")],
        [InlineKeyboardButton("❓ Help", callback_data="cmd_help")]
    ]
    await update.message.reply_text(
        "📁 Welcome to File Manager Bot! By Silent Programmer\n"
        "Use /help to see available commands.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 <b>Main Commands</b>:
/search - Search for files (add keyword after command)
/search_batch - Search for batches (add keyword after command)
/topfiles - Most downloaded files
/userstats - Top active users
/request - Request a file (add filename after command)
/rate - Rate a file (add filename and rating 1-5)

📦 <b>Batch Commands</b>:
/createbatch - Create new batch (add name and optional description)
/addtobatch - Add files to batch (add batch name)
/listbatches - List all batches
/batchinfo - Get batch details (add batch name)
/editbatch - Edit batch description (add name and new description)
/done - Finish adding to batch

💡 <b>Batch Management</b>:
• Use /batchinfo to view batch details
• Click "Edit Description" to modify batch info
• Click "Delete Batch" to remove a batch
• Only batch creators can edit or delete their batches
"""
    await update.message.reply_text(help_text, parse_mode="HTML")

# ==================
# File Management
# ==================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    doc = update.message.document
    file_id = doc.file_id
    file_name = doc.file_name
    file_size = doc.file_size

    # Check batch mode
    if 'current_batch' in context.user_data:
        batch_name = context.user_data['current_batch']
        return await _add_to_batch(update, batch_name, file_id, file_name, file_size)

    # Normal upload - use file_store.json
    # Generate unique file key based on timestamp to avoid duplicates
    file_key = f"file_{int(datetime.now().timestamp())}"
    db.file_store[file_key] = {
        "id": file_id,
        "name": file_name,
        "size": file_size,
        "uploaded_by": user.id,
        "upload_date": datetime.now().isoformat()
    }
    db.save_all()

    await update.message.reply_text(f"✅ File '{file_name}' saved successfully!")

async def _add_to_batch(update: Update, batch_name: str, file_id: str, file_name: str, file_size: int):
    if batch_name not in db.batches:
        await update.message.reply_text("❌ Batch no longer exists!")
        return

    # Use file_store_batch.json for batch files
    # Generate unique file key based on timestamp to avoid duplicates
    file_key = f"file_{int(datetime.now().timestamp())}"
    db.file_store_batch[file_key] = {
        "id": file_id,
        "name": file_name,
        "size": file_size,
        "batch": batch_name,
        "upload_date": datetime.now().isoformat(),
        "uploaded_by": update.message.from_user.id
    }

    if "files" not in db.batches[batch_name]:
        db.batches[batch_name]["files"] = []
    db.batches[batch_name]["files"].append(file_key)

    db.save_all()
    await update.message.reply_text(
        f"✅ Added '{file_name}' to batch '{batch_name}'!\n"
        "Send more files or /done to finish."
    )

# ==================
# Search Functionality
# ==================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /search <query>")

    query = " ".join(context.args).lower()
    # Search in both file stores
    normal_results = {
        k: v for k, v in db.file_store.items()
        if "name" in v and query in v["name"].lower()
    }

    # Don't include batch files in normal search
    if not normal_results:
        return await update.message.reply_text("🔍 No files found. Try /request to ask for it or use /search_batch for files in batches.")

    keyboard = [
        [InlineKeyboardButton(
            f"{v['name']} ({v.get('size', 0) // 1024}KB)",
            callback_data=f"file_{k}"
        )]
        for k, v in normal_results.items()
    ]

    await update.message.reply_text(
        f"📂 Found {len(normal_results)} files:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def search_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /search_batch <query>")

    query = " ".join(context.args).lower()

    # Exact match first
    exact_matches = {
        name: data for name, data in db.batches.items()
        if query == name.lower()
    }

    # Partial matches if no exact matches
    matches = exact_matches if exact_matches else {
        name: data for name, data in db.batches.items()
        if query in name.lower()
    }

    if not matches:
        # Suggest similar
        suggestions = [
            name for name in db.batches
            if any(word in name.lower() for word in query.split())
        ][:5]

        msg = "🔍 No batches found."
        if suggestions:
            msg += "\n\nDid you mean:\n" + "\n".join(f"• {name}" for name in suggestions)
        return await update.message.reply_text(msg)

    keyboard = [
        [InlineKeyboardButton(
            f"{name} ({len(data.get('files', []))} files)",
            callback_data=f"batch_{name}"
        )]
        for name, data in matches.items()
    ]

    await update.message.reply_text(
        f"📦 Found {len(matches)} batches:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================
# Batch Management
# ==================

async def create_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /createbatch <name> [description]")

    args = context.args
    batch_name = args[0]
    description = " ".join(args[1:]) if len(args) > 1 else ""

    if batch_name in db.batches:
        return await update.message.reply_text("⚠️ Batch already exists!")

    db.batches[batch_name] = {
        "description": description,
        "created_by": update.message.from_user.id,
        "created_at": datetime.now().isoformat(),
        "files": []
    }
    db.save_all()

    await update.message.reply_text(
        f"✅ Batch '{batch_name}' created!\n"
        f"Description: {description or 'None'}\n\n"
        "Use /addtobatch to add files."
    )

async def add_to_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /addtobatch <name>")

    batch_name = " ".join(context.args)
    if batch_name not in db.batches:
        return await update.message.reply_text("❌ Batch doesn't exist!")

    context.user_data['current_batch'] = batch_name
    await update.message.reply_text(
        f"🔄 Ready to add files to '{batch_name}'.\n"
        "Send me files now or /done when finished."
    )

async def done_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'current_batch' not in context.user_data:
        return await update.message.reply_text("⚠️ Not currently adding to any batch!")

    batch_name = context.user_data.pop('current_batch')
    count = len(db.batches[batch_name]["files"])
    await update.message.reply_text(
        f"✅ Finished adding to '{batch_name}'!\n"
        f"Total files: {count}\n"
        f"Use /batchinfo {batch_name} for details."
    )

async def list_batches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.batches:
        return await update.message.reply_text("ℹ️ No batches created yet.")

    batches = sorted(
        db.batches.items(),
        key=lambda x: len(x[1]["files"]),
        reverse=True
    )

    # Create keyboard with batch buttons
    keyboard = []
    for name, data in batches[:20]:  # Limit to top 20
        keyboard.append([
            InlineKeyboardButton(
                f"{name} ({len(data['files'])} files)",
                callback_data=f"batch_{name}"
            )
        ])

    if len(batches) > 20:
        keyboard.append([InlineKeyboardButton("📄 Show More", callback_data="cmd_showmore")])

    await update.message.reply_text(
        "📦 Available Batches:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def batch_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /batchinfo <name>")

    batch_name = " ".join(context.args)
    if batch_name not in db.batches:
        return await update.message.reply_text("❌ Batch not found!")

    batch = db.batches[batch_name]
    creator = await context.bot.get_chat(batch["created_by"])

    msg = f"📦 <b>{batch_name}</b>\n\n"
    msg += f"📝 <i>{batch.get('description', 'No description')}</i>\n\n"
    msg += f"👤 Created by: {creator.first_name}\n"
    msg += f"📅 Created on: {batch['created_at'][:10]}\n"
    msg += f"📂 Files: {len(batch['files'])}\n"
    msg += f"⬇️ Downloads: {db.stats['batch_downloads'].get(batch_name, 0)}"

    # Add edit buttons if user is the creator
    keyboard = []
    if update.message.from_user.id == batch["created_by"]:
        keyboard = [
            [InlineKeyboardButton("✏️ Edit Description", callback_data=f"edit_desc_{batch_name}")],
            [InlineKeyboardButton("🗑️ Delete Batch", callback_data=f"delete_batch_{batch_name}")]
        ]

    await update.message.reply_text(
        msg, 
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def edit_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("ℹ️ Usage: /editbatch <name> <new description>")

    batch_name = context.args[0]
    new_description = " ".join(context.args[1:])

    if batch_name not in db.batches:
        return await update.message.reply_text("❌ Batch not found!")

    batch = db.batches[batch_name]
    if update.message.from_user.id != batch["created_by"]:
        return await update.message.reply_text("❌ Only the batch creator can edit it!")

    batch["description"] = new_description
    db.save_all()

    await update.message.reply_text(
        f"✅ Batch '{batch_name}' updated!\n"
        f"New description: {new_description}"
    )

# ==================
# File Delivery
# ==================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Answer callback query immediately to prevent loading state
    await query.answer("Processing...")

    data = query.data
    user = query.from_user

    try:
        # Handle command callbacks
        if data == "cmd_listbatches":
            if not db.batches:
                return await query.edit_message_text("ℹ️ No batches created yet.")
            
            batches = sorted(
                db.batches.items(),
                key=lambda x: len(x[1]["files"]),
                reverse=True
            )

            keyboard = []
            for name, data in batches[:20]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{name} ({len(data['files'])} files)",
                        callback_data=f"batch_{name}"
                    )
                ])

            if len(batches) > 20:
                keyboard.append([InlineKeyboardButton("📄 Show More", callback_data="cmd_showmore")])

            await query.edit_message_text(
                "📦 Available Batches:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        elif data == "cmd_help":
            help_text = """
📚 <b>Main Commands</b>:
/search - Search for files (add keyword after command)
/search_batch - Search for batches (add keyword after command)
/topfiles - Most downloaded files
/userstats - Top active users
/request - Request a file (add filename after command)
/rate - Rate a file (add filename and rating 1-5)

📦 <b>Batch Commands</b>:
/createbatch - Create new batch (add name and optional description)
/addtobatch - Add files to batch (add batch name)
/listbatches - List all batches
/batchinfo - Get batch details (add batch name)
/editbatch - Edit batch description (add name and new description)
/done - Finish adding to batch

💡 <b>Batch Management</b>:
• Use /batchinfo to view batch details
• Click "Edit Description" to modify batch info
• Click "Delete Batch" to remove a batch
• Only batch creators can edit or delete their batches
"""
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="cmd_back")]]
            await query.edit_message_text(
                help_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        elif data == "cmd_back":
            keyboard = [
                [InlineKeyboardButton("📦 View Batches", callback_data="cmd_listbatches")],
                [InlineKeyboardButton("❓ Help", callback_data="cmd_help")]
            ]
            await query.edit_message_text(
                "📁 Welcome to File Manager Bot! By Silent Programmer\n"
                "Use /help to see available commands.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Handle existing callbacks
        if data.startswith("batch_"):
            batch_name = data[6:]
            return await _show_batch_files(query, batch_name, user)

        # Handle file download
        if data.startswith("file_"):
            file_key = data[5:]
            return await _send_file(query, file_key, user)

        # Handle batch editing
        if data.startswith("edit_desc_"):
            batch_name = data[10:]
            if batch_name not in db.batches:
                return await query.edit_message_text("❌ Batch no longer exists!")
            
            batch = db.batches[batch_name]
            if user.id != batch["created_by"]:
                return await query.edit_message_text("❌ Only the batch creator can edit it!")

            # Store batch name in user data for the next message
            context.user_data['editing_batch'] = batch_name
            await query.edit_message_text(
                f"✏️ Editing description for batch '{batch_name}'\n"
                f"Current description: {batch.get('description', 'No description')}\n\n"
                "Please send the new description in your next message."
            )

        # Handle batch deletion
        if data.startswith("delete_batch_"):
            batch_name = data[12:]
            if batch_name not in db.batches:
                return await query.edit_message_text("❌ Batch no longer exists!")
            
            batch = db.batches[batch_name]
            if user.id != batch["created_by"]:
                return await query.edit_message_text("❌ Only the batch creator can delete it!")

            # Delete batch and its files
            for file_key in batch.get("files", []):
                if file_key in db.file_store_batch:
                    del db.file_store_batch[file_key]
            del db.batches[batch_name]
            db.save_all()

            await query.edit_message_text(f"✅ Batch '{batch_name}' has been deleted!")
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await query.edit_message_text(
            "❌ An error occurred. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="cmd_listbatches")
            ]])
        )

async def _show_batch_files(query, batch_name: str, user):
    try:
        if batch_name not in db.batches:
            return await query.edit_message_text(
                "❌ Batch no longer exists!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Batches", callback_data="cmd_listbatches")
                ]])
            )

        files = db.batches[batch_name]["files"]
        if not files:
            return await query.edit_message_text(
                "ℹ️ This batch is empty.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Batches", callback_data="cmd_listbatches")
                ]])
            )

        # Track batch view
        db.stats["batch_downloads"][batch_name] = db.stats["batch_downloads"].get(batch_name, 0) + 1
        db.save_all()

        # Create keyboard with file buttons
        keyboard = []
        for file_key in files:
            if file_key in db.file_store_batch:
                file_data = db.file_store_batch[file_key]
                file_size = format_size(file_data.get("size", 0))
                keyboard.append([
                    InlineKeyboardButton(
                        f"{file_data['name']} ({file_size})",
                        callback_data=f"file_{file_key}"
                    )
                ])

        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 Back to Batches", callback_data="cmd_listbatches")])

        await query.edit_message_text(
            f"📂 Files in '{batch_name}':",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error showing batch files: {e}")
        await query.edit_message_text(
            "❌ An error occurred while loading files. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Batches", callback_data="cmd_listbatches")
            ]])
        )

def format_size(size_bytes):
    """Convert size in bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

async def _send_file(query, file_key: str, user):
    try:
        # Check both file stores
        if file_key in db.file_store:
            file_data = db.file_store[file_key]
        elif file_key in db.file_store_batch:
            file_data = db.file_store_batch[file_key]
        else:
            return await query.edit_message_text(
                "❌ File no longer available!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="cmd_listbatches")
                ]])
            )

        # Track download stats
        db.stats["downloads"][file_data["name"]] = db.stats["downloads"].get(file_data["name"], 0) + 1
        db.stats["users"][str(user.id)] = db.stats["users"].get(str(user.id), 0) + 1
        db.save_all()

        # Format file size
        file_size = format_size(file_data.get("size", 0))

        # Send the file and store the message
        sent_message = await query.message.reply_document(
            file_data["id"],
            caption=f"📄 {file_data['name']}\n"
                   f"📦 Size: {file_size}\n"
                   f"👤 Requested by: {user.mention_markdown()}\n"
                   f"⏱️ This message will be deleted in 5 minutes",
            parse_mode="Markdown"
        )

        # Schedule message deletion after 5 minutes
        async def delete_messages():
            try:
                await asyncio.sleep(300)  # 5 minutes
                await sent_message.delete()
                await query.message.delete()
                if query.message.reply_to_message and query.message.reply_to_message.from_user.id == query.message.bot.id:
                    await query.message.reply_to_message.delete()
            except Exception as e:
                logger.error(f"Error deleting messages: {e}")

        # Start the deletion task
        asyncio.create_task(delete_messages())

    except Exception as e:
        logger.error(f"Error sending file: {e}")
        await query.edit_message_text(
            "❌ Error sending file. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="cmd_listbatches")
            ]])
        )

# ==================
# Statistics
# ==================

async def top_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.stats["downloads"]:
        return await update.message.reply_text("ℹ️ No download data yet.")

    top = sorted(
        db.stats["downloads"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    msg = "🏆 <b>Top 10 Files</b>:\n\n"
    msg += "\n".join(
        f"{i+1}. {name} - {count} downloads"
        for i, (name, count) in enumerate(top)
    )

    await update.message.reply_text(msg, parse_mode="HTML")

async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.stats["users"]:
        return await update.message.reply_text("ℹ️ No user data yet.")

    top_users = sorted(
        db.stats["users"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    msg = "🏆 <b>Top 10 Users</b>:\n\n"
    for i, (user_id, count) in enumerate(top_users):
        try:
            user = await context.bot.get_chat(int(user_id))
            name = user.username or user.first_name
            msg += f"{i+1}. @{name} - {count} downloads\n"
        except:
            msg += f"{i+1}. User {user_id} - {count} downloads\n"

    await update.message.reply_text(msg, parse_mode="HTML")

# ==================
# Bot Setup
# ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle batch description editing
    if 'editing_batch' in context.user_data:
        batch_name = context.user_data.pop('editing_batch')
        if batch_name not in db.batches:
            return await update.message.reply_text("❌ Batch no longer exists!")

        batch = db.batches[batch_name]
        if update.message.from_user.id != batch["created_by"]:
            return await update.message.reply_text("❌ Only the batch creator can edit it!")

        new_description = update.message.text
        batch["description"] = new_description
        db.save_all()

        await update.message.reply_text(
            f"✅ Batch '{batch_name}' updated!\n"
            f"New description: {new_description}"
        )
        return

    # Handle normal document upload
    if update.message.document:
        await handle_document(update, context)

def main():
    # Configure application with concurrency settings
    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)  # Enable concurrent updates
        .build()
    )

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("search_batch", search_batch))
    app.add_handler(CommandHandler("topfiles", top_files))
    app.add_handler(CommandHandler("userstats", user_stats))

    # Batch commands
    app.add_handler(CommandHandler("createbatch", create_batch))
    app.add_handler(CommandHandler("addtobatch", add_to_batch))
    app.add_handler(CommandHandler("done", done_adding))
    app.add_handler(CommandHandler("listbatches", list_batches))
    app.add_handler(CommandHandler("batchinfo", batch_info))
    app.add_handler(CommandHandler("editbatch", edit_batch))

    # Handlers
    app.add_handler(MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Try to set up job queue if available
    try:
        job_queue = app.job_queue
        if job_queue is not None:
            # Add periodic cleanup job (every 6 minutes)
            job_queue.run_repeating(cleanup_expired_messages, interval=360, first=10)
            logger.info("Job queue initialized successfully")
        else:
            logger.warning("Job queue not available. Message cleanup will be handled by individual tasks.")
    except Exception as e:
        logger.warning(f"Could not initialize job queue: {e}. Message cleanup will be handled by individual tasks.")

    logger.info("🤖 Bot is running with concurrent updates enabled...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

async def cleanup_expired_messages(context: ContextTypes.DEFAULT_TYPE):
    """Periodic cleanup of expired messages"""
    try:
        # Get current time
        current_time = datetime.now()
        
        # Clean up expired messages (older than 5 minutes)
        for message_id, message_data in list(context.bot_data.get('expired_messages', {}).items()):
            if (current_time - message_data['timestamp']).total_seconds() > 300:  # 5 minutes
                try:
                    await context.bot.delete_message(
                        chat_id=message_data['chat_id'],
                        message_id=message_id
                    )
                except Exception as e:
                    logger.error(f"Error deleting expired message {message_id}: {e}")
                finally:
                    del context.bot_data['expired_messages'][message_id]
    except Exception as e:
        logger.error(f"Error in cleanup job: {e}")

if __name__ == "__main__":
    main()
