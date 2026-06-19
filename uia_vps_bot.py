# uia_vps_bot.py
"""
UIA HOST - Advanced VPS Management Bot
Created by REONDEV
Version: 3.0.0
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import re
import sys
from dataclasses import dataclass
from enum import Enum

# ============================================================
# CONFIGURATION
# ============================================================

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'UIA HOST')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '0'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
EMBED_COLOR = 0x0a0a1a  # Dark background with subtle blue
ACCENT_COLOR = 0x00d4ff  # Cyan accent
SUCCESS_COLOR = 0x00ff88
ERROR_COLOR = 0xff3366
WARNING_COLOR = 0xffaa00

# Branding
BRAND_LOGO = "https://imgur.com/a/s06G4ew"  # Replace with UIA HOST logo
BRAND_FOOTER = "UIA HOST VPS Manager • Premium Virtual Private Servers"
BRAND_THUMBNAIL = "https://imgur.com/a/s06G4ew"

# OS Options for VPS Creation and Reinstall
OS_OPTIONS = [
    {"label": "🟣 Ubuntu 20.04 LTS", "value": "ubuntu:20.04", "emoji": "🐧"},
    {"label": "🟣 Ubuntu 22.04 LTS", "value": "ubuntu:22.04", "emoji": "🐧"},
    {"label": "🟣 Ubuntu 24.04 LTS", "value": "ubuntu:24.04", "emoji": "🐧"},
    {"label": "🔴 Debian 10 (Buster)", "value": "images:debian/10", "emoji": "📦"},
    {"label": "🔴 Debian 11 (Bullseye)", "value": "images:debian/11", "emoji": "📦"},
    {"label": "🔴 Debian 12 (Bookworm)", "value": "images:debian/12", "emoji": "📦"},
    {"label": "🔴 Debian 13 (Trixie)", "value": "images:debian/13", "emoji": "📦"},
]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('uia_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('uia_vps_bot')

# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect('uia_vps.db')
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Admins table
    cur.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id TEXT PRIMARY KEY
    )''')
    cur.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (str(MAIN_ADMIN_ID),))
    
    # VPS table
    cur.execute('''CREATE TABLE IF NOT EXISTS vps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        container_name TEXT UNIQUE NOT NULL,
        ram TEXT NOT NULL,
        cpu TEXT NOT NULL,
        storage TEXT NOT NULL,
        config TEXT NOT NULL,
        os_version TEXT DEFAULT 'ubuntu:22.04',
        status TEXT DEFAULT 'stopped',
        suspended INTEGER DEFAULT 0,
        whitelisted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        shared_with TEXT DEFAULT '[]',
        suspension_history TEXT DEFAULT '[]',
        plan TEXT DEFAULT 'Standard'
    )''')
    
    # Settings table
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    
    settings_init = [
        ('cpu_threshold', '90'),
        ('ram_threshold', '90'),
        ('auto_backup', '1'),
        ('maintenance_mode', '0'),
    ]
    for key, value in settings_init:
        cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    
    # Port allocations
    cur.execute('''CREATE TABLE IF NOT EXISTS port_allocations (
        user_id TEXT PRIMARY KEY,
        allocated_ports INTEGER DEFAULT 0
    )''')
    
    # Port forwards
    cur.execute('''CREATE TABLE IF NOT EXISTS port_forwards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        vps_container TEXT NOT NULL,
        vps_port INTEGER NOT NULL,
        host_port INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )''')
    
    # Audit logs
    cur.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT NOT NULL
    )''')
    
    # Tickets table
    cur.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        created_at TEXT NOT NULL,
        closed_at TEXT
    )''')
    
    conn.commit()
    conn.close()

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def get_setting(key: str, default: Any = None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps')
    rows = cur.fetchall()
    conn.close()
    
    data = {}
    for row in rows:
        user_id = row['user_id']
        if user_id not in data:
            data[user_id] = []
        vps = dict(row)
        vps['shared_with'] = json.loads(vps['shared_with'])
        vps['suspension_history'] = json.loads(vps['suspension_history'])
        vps['suspended'] = bool(vps['suspended'])
        vps['whitelisted'] = bool(vps['whitelisted'])
        vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
        vps['plan'] = vps.get('plan', 'Standard')
        data[user_id].append(vps)
    return data

def get_admins() -> List[str]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM admins')
    rows = cur.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

def save_vps_data():
    conn = get_db()
    cur = conn.cursor()
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            shared_json = json.dumps(vps['shared_with'])
            history_json = json.dumps(vps['suspension_history'])
            suspended_int = 1 if vps['suspended'] else 0
            whitelisted_int = 1 if vps.get('whitelisted', False) else 0
            os_ver = vps.get('os_version', 'ubuntu:22.04')
            created_at = vps.get('created_at', datetime.now().isoformat())
            plan = vps.get('plan', 'Standard')
            
            if 'id' not in vps or vps['id'] is None:
                cur.execute('''INSERT INTO vps (user_id, container_name, ram, cpu, storage, config, os_version, status, suspended, whitelisted, created_at, shared_with, suspension_history, plan)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (user_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int,
                             created_at, shared_json, history_json, plan))
                vps['id'] = cur.lastrowid
            else:
                cur.execute('''UPDATE vps SET user_id = ?, ram = ?, cpu = ?, storage = ?, config = ?, os_version = ?, status = ?, suspended = ?, whitelisted = ?, shared_with = ?, suspension_history = ?, plan = ?
                               WHERE id = ?''',
                            (user_id, vps['ram'], vps['cpu'], vps['storage'], vps['config'],
                             os_ver, vps['status'], suspended_int, whitelisted_int, shared_json, history_json, plan, vps['id']))
    conn.commit()
    conn.close()

def save_admin_data():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM admins')
    for admin_id in admin_data['admins']:
        cur.execute('INSERT INTO admins (user_id) VALUES (?)', (admin_id,))
    conn.commit()
    conn.close()

def log_audit(user_id: str, username: str, action: str, details: str):
    """Log an audit event"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO audit_logs (timestamp, user_id, username, action, details)
                   VALUES (?, ?, ?, ?, ?)''',
                (datetime.now().isoformat(), user_id, username, action, details))
    conn.commit()
    conn.close()

# ============================================================
# EMBED FUNCTIONS
# ============================================================

def create_embed(title, description="", color=EMBED_COLOR):
    embed = discord.Embed(
        title=f"✦ {BOT_NAME} — {title}",
        description=truncate_text(description, 4096),
        color=color
    )
    embed.set_thumbnail(url=BRAND_THUMBNAIL)
    embed.set_footer(text=f"{BRAND_FOOTER} • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     icon_url=BRAND_LOGO)
    return embed

def add_field(embed, name, value, inline=False):
    embed.add_field(
        name=truncate_text(f"▸ {name}", 256),
        value=truncate_text(value, 1024),
        inline=inline
    )
    return embed

def create_success_embed(title, description=""):
    return create_embed(f"✅ {title}", description, color=SUCCESS_COLOR)

def create_error_embed(title, description=""):
    return create_embed(f"❌ {title}", description, color=ERROR_COLOR)

def create_info_embed(title, description=""):
    return create_embed(f"ℹ️ {title}", description, color=ACCENT_COLOR)

def create_warning_embed(title, description=""):
    return create_embed(f"⚠️ {title}", description, color=WARNING_COLOR)

# ============================================================
# ADMIN CHECKS
# ============================================================

def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions to use this command.")
    return commands.check(predicate)

def is_main_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID):
            return True
        raise commands.CheckFailure("Only the main admin can use this command.")
    return commands.check(predicate)

# ============================================================
# LXC COMMANDS
# ============================================================

async def execute_lxc(command, timeout=120):
    try:
        cmd = shlex.split(command)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise asyncio.TimeoutError(f"Command timed out after {timeout} seconds")
        
        if proc.returncode != 0:
            error = stderr.decode().strip() if stderr else "Command failed with no error output"
            raise Exception(error)
        return stdout.decode().strip() if stdout else True
    except Exception as e:
        logger.error(f"LXC Error: {command} - {str(e)}")
        raise

async def get_container_status(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "info", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if line.startswith("Status: "):
                return line.split(": ", 1)[1].strip().lower()
        return "unknown"
    except Exception:
        return "unknown"

async def get_container_cpu_pct(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "top", "-bn1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if '%Cpu(s):' in line:
                parts = line.split()
                us = float(parts[1])
                sy = float(parts[3])
                ni = float(parts[5])
                id_ = float(parts[7])
                wa = float(parts[9])
                hi = float(parts[11])
                si = float(parts[13])
                st = float(parts[15])
                return us + sy + ni + wa + hi + si + st
        return 0.0
    except Exception:
        return 0.0

async def get_container_ram_pct(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            return (used / total * 100) if total > 0 else 0
        return 0.0
    except Exception:
        return 0.0

async def get_container_cpu(container_name):
    usage = await get_container_cpu_pct(container_name)
    return f"{usage:.1f}%"

async def get_container_memory(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            return f"{used}/{total} MB"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_disk(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/dev/' in line and ' /' in line:
                parts = line.split()
                if len(parts) >= 5:
                    return f"{parts[2]}/{parts[1]} ({parts[4]})"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_uptime(container_name):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "uptime",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else "Unknown"
    except Exception:
        return "Unknown"

async def apply_lxc_config(container_name):
    try:
        await execute_lxc(f"lxc config set {container_name} security.nesting true")
        await execute_lxc(f"lxc config set {container_name} security.privileged true")
        await execute_lxc(f"lxc config set {container_name} security.syscalls.intercept.mknod true")
        await execute_lxc(f"lxc config set {container_name} security.syscalls.intercept.setxattr true")
        
        try:
            await execute_lxc(f"lxc config device add {container_name} fuse unix-char path=/dev/fuse")
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise
        
        await execute_lxc(f"lxc config set {container_name} linux.kernel_modules overlay,loop,nf_nat,ip_tables,ip6_tables,netlink_diag,br_netfilter")
        
        raw_lxc_config = """
lxc.apparmor.profile = unconfined
lxc.cgroup.devices.allow = a
lxc.cap.drop =
lxc.mount.auto = proc:rw sys:rw cgroup:rw
"""
        await execute_lxc(f"lxc config set {container_name} raw.lxc '{raw_lxc_config}'")
        logger.info(f"Applied LXC config to {container_name}")
    except Exception as e:
        logger.error(f"Failed to apply LXC config to {container_name}: {e}")

async def apply_internal_permissions(container_name):
    try:
        await asyncio.sleep(3)
        commands = [
            "mkdir -p /etc/sysctl.d/",
            "echo 'net.ipv4.ip_unprivileged_port_start=0' > /etc/sysctl.d/99-custom.conf",
            "echo 'net.ipv4.ping_group_range=0 2147483647' >> /etc/sysctl.d/99-custom.conf",
            "echo 'fs.inotify.max_user_watches=524288' >> /etc/sysctl.d/99-custom.conf",
            "sysctl -p /etc/sysctl.d/99-custom.conf || true",
            "apt-get update -y > /dev/null 2>&1 || true",
            "apt-get install -y curl wget git vim htop net-tools > /dev/null 2>&1 || true"
        ]
        for cmd in commands:
            try:
                await execute_lxc(f"lxc exec {container_name} -- bash -c \"{cmd}\"")
            except Exception:
                continue
        logger.info(f"Applied internal permissions to {container_name}")
    except Exception as e:
        logger.error(f"Failed to apply internal permissions to {container_name}: {e}")

async def recreate_port_forwards(container_name: str) -> int:
    readded_count = 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT vps_port, host_port FROM port_forwards WHERE vps_container = ?', (container_name,))
    rows = cur.fetchall()
    for row in rows:
        vps_port = row['vps_port']
        host_port = row['host_port']
        try:
            await execute_lxc(f"lxc config device add {container_name} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}")
            await execute_lxc(f"lxc config device add {container_name} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}")
            readded_count += 1
        except Exception as e:
            logger.error(f"Failed to re-add port forward {host_port}->{vps_port}: {e}")
    conn.close()
    return readded_count

# ============================================================
# PORT FORWARDING
# ============================================================

def get_user_allocation(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT allocated_ports FROM port_allocations WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def get_user_used_ports(user_id: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM port_forwards WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0]

def get_available_host_port() -> Optional[int]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT host_port FROM port_forwards')
    used_ports = {row[0] for row in cur.fetchall()}
    conn.close()
    for _ in range(100):
        port = random.randint(20000, 50000)
        if port not in used_ports:
            return port
    return None

async def create_port_forward(user_id: str, container: str, vps_port: int) -> Optional[int]:
    host_port = get_available_host_port()
    if not host_port:
        return None
    try:
        await execute_lxc(f"lxc config device add {container} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}")
        await execute_lxc(f"lxc config device add {container} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}")
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO port_forwards (user_id, vps_container, vps_port, host_port, created_at) VALUES (?, ?, ?, ?, ?)',
                    (user_id, container, vps_port, host_port, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return host_port
    except Exception as e:
        logger.error(f"Failed to create port forward: {e}")
        return None

async def remove_port_forward(forward_id: int) -> tuple[bool, Optional[str]]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id, vps_container, host_port FROM port_forwards WHERE id = ?', (forward_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, None
    user_id, container, host_port = row
    try:
        await execute_lxc(f"lxc config device remove {container} tcp_proxy_{host_port}")
        await execute_lxc(f"lxc config device remove {container} udp_proxy_{host_port}")
        cur.execute('DELETE FROM port_forwards WHERE id = ?', (forward_id,))
        conn.commit()
        conn.close()
        return True, user_id
    except Exception as e:
        logger.error(f"Failed to remove port forward {forward_id}: {e}")
        conn.close()
        return False, None

# ============================================================
# INITIALIZATION
# ============================================================

init_db()
vps_data = get_vps_data()
admin_data = {'admins': get_admins()}

CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))
MAINTENANCE_MODE = get_setting('maintenance_mode', '0') == '1'

# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ============================================================
# RESOURCE MONITOR
# ============================================================

resource_monitor_active = True

def get_cpu_usage():
    try:
        if shutil.which("mpstat"):
            result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True)
            output = result.stdout
            for line in output.split('\n'):
                if 'all' in line and '%' in line:
                    parts = line.split()
                    idle = float(parts[-1])
                    return 100.0 - idle
        else:
            result = subprocess.run(['top', '-bn1'], capture_output=True, text=True)
            output = result.stdout
            for line in output.split('\n'):
                if '%Cpu(s):' in line:
                    parts = line.split()
                    us = float(parts[1])
                    sy = float(parts[3])
                    ni = float(parts[5])
                    id_ = float(parts[7])
                    wa = float(parts[9])
                    hi = float(parts[11])
                    si = float(parts[13])
                    st = float(parts[15])
                    return us + sy + ni + wa + hi + si + st
        return 0.0
    except Exception as e:
        logger.error(f"Error getting CPU usage: {e}")
        return 0.0

def get_ram_usage():
    try:
        result = subprocess.run(['free', '-m'], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        if len(lines) > 1:
            mem = lines[1].split()
            total = int(mem[1])
            used = int(mem[2])
            return (used / total * 100) if total > 0 else 0.0
        return 0.0
    except Exception as e:
        logger.error(f"Error getting RAM usage: {e}")
        return 0.0

def resource_monitor():
    global resource_monitor_active
    backup_interval = 3600
    last_backup = time.time()
    
    while resource_monitor_active:
        try:
            cpu_usage = get_cpu_usage()
            ram_usage = get_ram_usage()
            logger.info(f"Host CPU: {cpu_usage:.1f}%, RAM: {ram_usage:.1f}%")
            
            if cpu_usage > CPU_THRESHOLD or ram_usage > RAM_THRESHOLD:
                logger.warning(f"⚠️ Resource threshold exceeded! CPU: {cpu_usage:.1f}%, RAM: {ram_usage:.1f}%")
            
            if time.time() - last_backup > backup_interval:
                backup_name = f"uia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                try:
                    shutil.copy('uia_vps.db', backup_name)
                    logger.info(f"Database backup created: {backup_name}")
                    last_backup = time.time()
                except Exception as backup_e:
                    logger.error(f"Failed to create DB backup: {backup_e}")
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in resource monitor: {e}")
            time.sleep(60)

monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
monitor_thread.start()

# ============================================================
# BOT EVENTS
# ============================================================

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{BOT_NAME} VPS • {len(vps_data)} users"
        )
    )
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")
    logger.info(f"✨ {BOT_NAME} VPS Bot is ready!")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Usage: `{PREFIX}help` for command info"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=create_error_embed("Invalid Argument", "Please check your input and try again."))
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=create_error_embed("Access Denied", str(error) or "You don't have permission for this command."))
    elif isinstance(error, discord.NotFound):
        await ctx.send(embed=create_error_embed("Error", "The requested resource was not found."))
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(embed=create_error_embed("System Error", "An unexpected error occurred. Support has been notified."))

@bot.event
async def on_member_join(member):
    """Welcome new members with info about VPS services"""
    try:
        welcome_embed = create_info_embed(
            f"Welcome to {member.guild.name}!",
            f"Welcome {member.mention}!\n\n"
            f"🚀 **{BOT_NAME}** provides premium VPS hosting with:\n"
            f"• Full root access via SSH\n"
            f"• Docker-ready containers\n"
            f"• 24/7 uptime guarantee\n"
            f"• Instant deployment\n\n"
            f"Use `{PREFIX}help` to get started!"
        )
        await member.send(embed=welcome_embed)
    except:
        pass

# ============================================================
# BASIC COMMANDS
# ============================================================

@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = create_success_embed("Pong!", f"🏓 Latency: **{latency}ms**")
    add_field(embed, "Status", "🟢 Online", True)
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    try:
        result = subprocess.run(['uptime'], capture_output=True, text=True)
        embed = create_info_embed("Host Uptime", f"```\n{result.stdout.strip()}\n```")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

@bot.command(name='about')
async def about(ctx):
    embed = create_embed("About UIA HOST", 
        f"**{BOT_NAME}** - Premium VPS Management Bot\n\n"
        f"**Version:** 3.0.0\n"
        f"**Developer:** REONDEV\n"
        f"**Server IP:** {YOUR_SERVER_IP}\n"
        f"**Total VPS:** {sum(len(v) for v in vps_data.values())}\n"
        f"**Total Users:** {len(vps_data)}\n\n"
        f"✨ Features:\n"
        f"• Full LXC container management\n"
        f"• Port forwarding (TCP/UDP)\n"
        f"• Resource monitoring\n"
        f"• Docker-ready containers\n"
        f"• SSH access via tmate\n"
        f"• Snapshots & cloning\n"
        f"• Admin dashboard\n\n"
        f"📖 Use `{PREFIX}help` for commands"
    )
    await ctx.send(embed=embed)

# ============================================================
# VPS MANAGEMENT COMMANDS
# ============================================================

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, plan: str = "Standard"):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.plan = plan
        
        options = []
        for o in OS_OPTIONS:
            options.append(discord.SelectOption(
                label=o["label"],
                value=o["value"],
                emoji=o.get("emoji", "🐧")
            ))
        
        self.select = discord.ui.Select(
            placeholder="Select an OS for your VPS",
            options=options[:25]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)
    
    async def select_os(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the command author can select."),
                ephemeral=True
            )
            return
        
        os_version = self.select.values[0]
        self.select.disabled = True
        
        creating_embed = create_info_embed(
            "Deploying VPS",
            f"✨ Creating {self.plan} VPS for {self.user.mention} with **{os_version}**..."
        )
        await interaction.response.edit_message(embed=creating_embed, view=self)
        
        user_id = str(self.user.id)
        if user_id not in vps_data:
            vps_data[user_id] = []
        
        vps_count = len(vps_data[user_id]) + 1
        container_name = f"uia-{self.user.name.lower()}-{vps_count}"
        container_name = re.sub(r'[^a-zA-Z0-9-]', '', container_name)
        
        ram_mb = self.ram * 1024
        
        try:
            await execute_lxc(f"lxc init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}")
            await execute_lxc(f"lxc config set {container_name} limits.memory {ram_mb}MB")
            await execute_lxc(f"lxc config set {container_name} limits.cpu {self.cpu}")
            await execute_lxc(f"lxc config device set {container_name} root size={self.disk}GB")
            await apply_lxc_config(container_name)
            await execute_lxc(f"lxc start {container_name}")
            await apply_internal_permissions(container_name)
            await recreate_port_forwards(container_name)
            
            config_str = f"{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk"
            vps_info = {
                "container_name": container_name,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": config_str,
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "suspension_history": [],
                "created_at": datetime.now().isoformat(),
                "shared_with": [],
                "id": None,
                "plan": self.plan
            }
            vps_data[user_id].append(vps_info)
            save_vps_data()
            
            # Assign VPS role
            if self.ctx.guild:
                vps_role = discord.utils.get(self.ctx.guild.roles, name=f"{BOT_NAME} VPS User")
                if not vps_role:
                    try:
                        vps_role = await self.ctx.guild.create_role(
                            name=f"{BOT_NAME} VPS User",
                            color=discord.Color(0x00d4ff)
                        )
                    except:
                        pass
                if vps_role:
                    try:
                        await self.user.add_roles(vps_role, reason=f"{BOT_NAME} VPS ownership")
                    except:
                        pass
            
            # Success embed
            success_embed = create_success_embed("🎉 VPS Deployed Successfully!")
            add_field(success_embed, "Owner", self.user.mention, True)
            add_field(success_embed, "VPS ID", f"#{vps_count}", True)
            add_field(success_embed, "Plan", f"**{self.plan}**", True)
            add_field(success_embed, "Container", f"`{container_name}`", True)
            add_field(success_embed, "Resources", 
                     f"**RAM:** {self.ram}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.disk}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "Features", 
                     "✅ Docker-ready\n✅ Full root access\n✅ Unprivileged ports\n✅ 24/7 support", False)
            
            await interaction.followup.send(embed=success_embed)
            
            # DM user
            try:
                dm_embed = create_success_embed("🚀 Your VPS is Ready!")
                add_field(dm_embed, "VPS Details", 
                         f"**Container:** `{container_name}`\n"
                         f"**Plan:** {self.plan}\n"
                         f"**RAM:** {self.ram}GB\n"
                         f"**CPU:** {self.cpu} Cores\n"
                         f"**Storage:** {self.disk}GB\n"
                         f"**OS:** {os_version}", False)
                add_field(dm_embed, "Management", 
                         f"• `{PREFIX}manage` - Manage your VPS\n"
                         f"• `{PREFIX}ports` - Port forwarding\n"
                         f"• `{PREFIX}help` - All commands", False)
                await self.user.send(embed=dm_embed)
            except:
                pass
            
            log_audit(str(self.ctx.author.id), self.ctx.author.name, 
                     "vps_create", f"Created VPS {container_name} for {self.user.name}")
            
        except Exception as e:
            error_embed = create_error_embed("Deployment Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed)

@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member):
    """Create a VPS for a user"""
    if MAINTENANCE_MODE and str(ctx.author.id) != str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Maintenance Mode", "VPS creation is currently disabled."))
        return
    
    if ram <= 0 or cpu <= 0 or disk <= 0:
        await ctx.send(embed=create_error_embed("Invalid Specs", "RAM, CPU, and Disk must be positive integers."))
        return
    
    # Check available resources
    total_ram = sum(int(v.get('ram', '0GB').replace('GB', '')) for lst in vps_data.values() for v in lst)
    total_cpu = sum(int(v.get('cpu', 0)) for lst in vps_data.values() for v in lst)
    
    embed = create_info_embed(
        "VPS Creation",
        f"Creating VPS for {user.mention}\n\n"
        f"**Resources:**\n"
        f"• RAM: {ram}GB\n"
        f"• CPU: {cpu} Cores\n"
        f"• Storage: {disk}GB\n\n"
        f"Select an OS below."
    )
    view = OSSelectView(ram, cpu, disk, user, ctx)
    await ctx.send(embed=embed, view=view)

@bot.command(name='myvps')
async def my_vps(ctx):
    """List your VPS instances"""
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    
    if not vps_list:
        embed = create_error_embed("No VPS Found", 
            f"You don't have any {BOT_NAME} VPS.\n"
            f"Contact an admin to create one."
        )
        add_field(embed, "Quick Actions", f"• `{PREFIX}help` - View commands")
        await ctx.send(embed=embed)
        return
    
    embed = create_info_embed("My VPS", f"You have **{len(vps_list)}** VPS instances:")
    
    text = []
    for i, vps in enumerate(vps_list):
        status = vps.get('status', 'unknown').upper()
        if vps.get('suspended', False):
            status = f"⛔ {status} (SUSPENDED)"
        elif status == 'RUNNING':
            status = f"🟢 {status}"
        elif status == 'STOPPED':
            status = f"🔴 {status}"
        else:
            status = f"🟡 {status}"
        
        if vps.get('whitelisted', False):
            status += " ⭐"
        
        plan = vps.get('plan', 'Standard')
        text.append(f"**#{i+1}** `{vps['container_name']}` | {status} | `{plan}`")
    
    add_field(embed, "Your VPS", "\n".join(text), False)
    add_field(embed, "Actions", f"• `{PREFIX}manage` - Manage your VPS\n• `{PREFIX}ports` - Port forwarding", False)
    await ctx.send(embed=embed)

@bot.command(name='manage')
async def manage_vps(ctx, user: discord.Member = None):
    """Manage your VPS or another user's VPS (Admin only)"""
    if user:
        if not await is_admin().predicate(ctx):
            return
        user_id = str(user.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            await ctx.send(embed=create_error_embed("No VPS", f"{user.mention} doesn't have any VPS."))
            return
        view = ManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=user_id)
        await ctx.send(embed=create_info_embed(f"Managing {user.name}'s VPS", ""), view=view)
    else:
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            embed = create_error_embed("No VPS Found", "You don't have any VPS. Contact an admin.")
            await ctx.send(embed=embed)
            return
        view = ManageView(user_id, vps_list)
        embed = await view.get_initial_embed()
        await ctx.send(embed=embed, view=view)

class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False, actual_index: Optional[int] = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list[:]
        self.selected_index = None
        self.is_shared = is_shared
        self.owner_id = owner_id or user_id
        self.is_admin = is_admin
        self.actual_index = actual_index
        self.indices = list(range(len(vps_list)))
        
        if self.is_shared and self.actual_index is None:
            raise ValueError("actual_index required for shared views")
        
        if len(vps_list) > 1:
            options = [
                discord.SelectOption(
                    label=f"VPS {i+1} ({v.get('plan', 'Standard')})",
                    description=f"Status: {v.get('status', 'unknown').upper()}",
                    value=str(i)
                ) for i, v in enumerate(vps_list)
            ]
            self.select = discord.ui.Select(placeholder="Select a VPS to manage", options=options)
            self.select.callback = self.select_vps
            self.add_item(self.select)
            self.initial_embed = create_embed("VPS Management", "Select a VPS from the dropdown menu below.", EMBED_COLOR)
            add_field(self.initial_embed, "Available VPS", 
                     "\n".join([f"**VPS {i+1}:** `{v['container_name']}` - {v.get('plan', 'Standard')}" for i, v in enumerate(vps_list)]), False)
        else:
            self.selected_index = 0
            self.initial_embed = None
            self.add_action_buttons()
    
    async def get_initial_embed(self):
        if self.initial_embed is not None:
            return self.initial_embed
        self.initial_embed = await self.create_vps_embed(self.selected_index)
        return self.initial_embed
    
    async def create_vps_embed(self, index):
        vps = self.vps_list[index]
        status = vps.get('status', 'unknown')
        suspended = vps.get('suspended', False)
        whitelisted = vps.get('whitelisted', False)
        
        if status == 'running' and not suspended:
            status_color = SUCCESS_COLOR
        elif suspended:
            status_color = WARNING_COLOR
        else:
            status_color = ERROR_COLOR
        
        container_name = vps['container_name']
        lxc_status = await get_container_status(container_name)
        cpu_usage = await get_container_cpu(container_name)
        memory_usage = await get_container_memory(container_name)
        disk_usage = await get_container_disk(container_name)
        uptime = await get_container_uptime(container_name)
        
        status_text = lxc_status.upper()
        if suspended:
            status_text += " ⛔ SUSPENDED"
        if whitelisted:
            status_text += " ⭐ WHITELISTED"
        
        owner_text = ""
        if self.is_admin and self.owner_id != self.user_id:
            try:
                owner_user = await bot.fetch_user(int(self.owner_id))
                owner_text = f"\n**Owner:** {owner_user.mention}"
            except:
                owner_text = f"\n**Owner ID:** {self.owner_id}"
        
        embed = create_embed(
            f"Manage VPS",
            f"Container: **`{container_name}`**{owner_text}",
            status_color
        )
        
        plan = vps.get('plan', 'Standard')
        add_field(embed, "📊 Resources", 
                 f"**Plan:** {plan}\n"
                 f"**RAM:** {vps['ram']}\n"
                 f"**CPU:** {vps['cpu']} Cores\n"
                 f"**Storage:** {vps['storage']}\n"
                 f"**OS:** {vps.get('os_version', 'ubuntu:22.04')}\n"
                 f"**Status:** `{status_text}`\n"
                 f"**Uptime:** {uptime}", False)
        
        add_field(embed, "📈 Live Usage", 
                 f"**CPU:** {cpu_usage}\n**Memory:** {memory_usage}\n**Disk:** {disk_usage}", False)
        
        # Port forwards count
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM port_forwards WHERE vps_container = ?', (container_name,))
        port_count = cur.fetchone()[0]
        conn.close()
        add_field(embed, "🔌 Ports", f"{port_count} active forward(s)", True)
        
        add_field(embed, "🎮 Controls", "Use the buttons below to manage your VPS", False)
        
        return embed
    
    def add_action_buttons(self):
        # Start button
        start_button = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success)
        start_button.callback = lambda inter: self.action_callback(inter, 'start')
        self.add_item(start_button)
        
        # Stop button
        stop_button = discord.ui.Button(label="⏹ Stop", style=discord.ButtonStyle.danger)
        stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
        self.add_item(stop_button)
        
        # Restart button
        restart_button = discord.ui.Button(label="🔄 Restart", style=discord.ButtonStyle.primary)
        restart_button.callback = lambda inter: self.action_callback(inter, 'restart')
        self.add_item(restart_button)
        
        # SSH button
        ssh_button = discord.ui.Button(label="🔑 SSH Access", style=discord.ButtonStyle.secondary)
        ssh_button.callback = lambda inter: self.action_callback(inter, 'tmate')
        self.add_item(ssh_button)
        
        # Stats button
        stats_button = discord.ui.Button(label="📊 Stats", style=discord.ButtonStyle.secondary)
        stats_button.callback = lambda inter: self.action_callback(inter, 'stats')
        self.add_item(stats_button)
        
        # Reinstall button (only for owner)
        if not self.is_shared and not self.is_admin:
            reinstall_button = discord.ui.Button(label="🔄 Reinstall", style=discord.ButtonStyle.danger)
            reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
            self.add_item(reinstall_button)
    
    async def select_vps(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "This is not your VPS!"),
                ephemeral=True
            )
            return
        
        self.selected_index = int(self.select.values[0])
        await interaction.response.defer()
        new_embed = await self.create_vps_embed(self.selected_index)
        self.clear_items()
        self.add_action_buttons()
        await interaction.edit_original_response(embed=new_embed, view=self)
    
    async def action_callback(self, interaction: discord.Interaction, action: str):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "This is not your VPS!"),
                ephemeral=True
            )
            return
        
        if self.selected_index is None:
            await interaction.response.send_message(
                embed=create_error_embed("No VPS Selected", "Please select a VPS first."),
                ephemeral=True
            )
            return
        
        actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
        target_vps = vps_data[self.owner_id][actual_idx]
        suspended = target_vps.get('suspended', False)
        
        if suspended and not self.is_admin and action != 'stats':
            await interaction.response.send_message(
                embed=create_error_embed("Suspended", "This VPS is suspended. Contact an admin."),
                ephemeral=True
            )
            return
        
        container_name = target_vps["container_name"]
        
        if action == 'stats':
            status = await get_container_status(container_name)
            cpu_usage = await get_container_cpu(container_name)
            memory_usage = await get_container_memory(container_name)
            disk_usage = await get_container_disk(container_name)
            uptime = await get_container_uptime(container_name)
            
            stats_embed = create_info_embed(f"📊 Stats - {container_name}", "")
            add_field(stats_embed, "Status", f"`{status.upper()}`", True)
            add_field(stats_embed, "CPU", cpu_usage, True)
            add_field(stats_embed, "Memory", memory_usage, True)
            add_field(stats_embed, "Disk", disk_usage, True)
            add_field(stats_embed, "Uptime", uptime, True)
            await interaction.response.send_message(embed=stats_embed, ephemeral=True)
            return
        
        if action == 'reinstall':
            if self.is_shared or self.is_admin:
                await interaction.response.send_message(
                    embed=create_error_embed("Access Denied", "Only the VPS owner can reinstall!"),
                    ephemeral=True
                )
                return
            
            if suspended:
                await interaction.response.send_message(
                    embed=create_error_embed("Cannot Reinstall", "Unsuspend the VPS first."),
                    ephemeral=True
                )
                return
            
            ram_gb = int(target_vps['ram'].replace('GB', ''))
            cpu = int(target_vps['cpu'])
            storage_gb = int(target_vps['storage'].replace('GB', ''))
            
            class ReinstallConfirm(discord.ui.View):
                def __init__(self, parent, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb):
                    super().__init__(timeout=60)
                    self.parent = parent
                    self.container_name = container_name
                    self.owner_id = owner_id
                    self.actual_idx = actual_idx
                    self.ram_gb = ram_gb
                    self.cpu = cpu
                    self.storage_gb = storage_gb
                
                @discord.ui.button(label="⚠️ Confirm Reinstall", style=discord.ButtonStyle.danger)
                async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                    await inter.response.defer(ephemeral=True)
                    try:
                        await inter.followup.send(
                            embed=create_info_embed("Deleting Container", f"Removing `{self.container_name}`..."),
                            ephemeral=True
                        )
                        await execute_lxc(f"lxc delete {self.container_name} --force")
                        
                        class ReinstallOSView(discord.ui.View):
                            def __init__(self, parent, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb):
                                super().__init__(timeout=300)
                                self.parent = parent
                                self.container_name = container_name
                                self.owner_id = owner_id
                                self.actual_idx = actual_idx
                                self.ram_gb = ram_gb
                                self.cpu = cpu
                                self.storage_gb = storage_gb
                                
                                options = []
                                for o in OS_OPTIONS:
                                    options.append(discord.SelectOption(
                                        label=o["label"],
                                        value=o["value"],
                                        emoji=o.get("emoji", "🐧")
                                    ))
                                
                                self.select = discord.ui.Select(
                                    placeholder="Select OS for reinstall",
                                    options=options[:25]
                                )
                                self.select.callback = self.select_os
                                self.add_item(self.select)
                            
                            async def select_os(self, inter: discord.Interaction):
                                os_version = self.select.values[0]
                                self.select.disabled = True
                                await inter.response.edit_message(
                                    embed=create_info_embed("Reinstalling", f"Deploying {os_version}..."),
                                    view=self
                                )
                                
                                try:
                                    ram_mb = self.ram_gb * 1024
                                    await execute_lxc(f"lxc init {os_version} {self.container_name} -s {DEFAULT_STORAGE_POOL}")
                                    await execute_lxc(f"lxc config set {self.container_name} limits.memory {ram_mb}MB")
                                    await execute_lxc(f"lxc config set {self.container_name} limits.cpu {self.cpu}")
                                    await execute_lxc(f"lxc config device set {self.container_name} root size={self.storage_gb}GB")
                                    await apply_lxc_config(self.container_name)
                                    await execute_lxc(f"lxc start {self.container_name}")
                                    await apply_internal_permissions(self.container_name)
                                    await recreate_port_forwards(self.container_name)
                                    
                                    target_vps = vps_data[self.owner_id][self.actual_idx]
                                    target_vps["os_version"] = os_version
                                    target_vps["status"] = "running"
                                    target_vps["suspended"] = False
                                    target_vps["created_at"] = datetime.now().isoformat()
                                    save_vps_data()
                                    
                                    success_embed = create_success_embed("Reinstall Complete", 
                                        f"VPS `{self.container_name}` has been reinstalled successfully!")
                                    add_field(success_embed, "OS", os_version, True)
                                    add_field(success_embed, "Resources", 
                                             f"RAM: {self.ram_gb}GB\nCPU: {self.cpu} Cores\nStorage: {self.storage_gb}GB", False)
                                    await inter.followup.send(embed=success_embed, ephemeral=True)
                                    self.stop()
                                    
                                except Exception as e:
                                    await inter.followup.send(
                                        embed=create_error_embed("Reinstall Failed", str(e)),
                                        ephemeral=True
                                    )
                                    self.stop()
                        
                        os_view = ReinstallOSView(
                            self.parent, self.container_name, self.owner_id,
                            self.actual_idx, self.ram_gb, self.cpu, self.storage_gb
                        )
                        await inter.followup.send(
                            embed=create_info_embed("Select OS", "Choose the new OS:"),
                            view=os_view,
                            ephemeral=True
                        )
                    except Exception as e:
                        await inter.followup.send(
                            embed=create_error_embed("Delete Failed", str(e)),
                            ephemeral=True
                        )
                
                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                    await inter.response.edit_message(
                        embed=create_info_embed("Cancelled", "Reinstall cancelled."),
                        view=None
                    )
            
            confirm_embed = create_warning_embed(
                "⚠️ Reinstall Warning",
                f"This will **erase all data** on VPS `{container_name}`.\n\n"
                f"This action **cannot be undone**.\n\n"
                f"Type: `/confirm` in the next step to proceed."
            )
            await interaction.response.send_message(
                embed=confirm_embed,
                view=ReinstallConfirm(
                    self, container_name, self.owner_id,
                    actual_idx, ram_gb, cpu, storage_gb
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            if action == 'start':
                await execute_lxc(f"lxc start {container_name}")
                target_vps["status"] = "running"
                save_vps_data()
                await apply_internal_permissions(container_name)
                await recreate_port_forwards(container_name)
                await interaction.followup.send(
                    embed=create_success_embed("VPS Started", f"`{container_name}` is now running!"),
                    ephemeral=True
                )
                
            elif action == 'stop':
                await execute_lxc(f"lxc stop {container_name}", timeout=120)
                target_vps["status"] = "stopped"
                save_vps_data()
                await interaction.followup.send(
                    embed=create_success_embed("VPS Stopped", f"`{container_name}` has been stopped."),
                    ephemeral=True
                )
                
            elif action == 'restart':
                await execute_lxc(f"lxc restart {container_name}")
                target_vps["status"] = "running"
                save_vps_data()
                await apply_internal_permissions(container_name)
                await recreate_port_forwards(container_name)
                await interaction.followup.send(
                    embed=create_success_embed("VPS Restarted", f"`{container_name}` has been restarted."),
                    ephemeral=True
                )
                
            elif action == 'tmate':
                if suspended:
                    await interaction.followup.send(
                        embed=create_error_embed("Suspended", "Cannot access suspended VPS."),
                        ephemeral=True
                    )
                    return
                
                await interaction.followup.send(
                    embed=create_info_embed("SSH Access", "Generating SSH connection..."),
                    ephemeral=True
                )
                
                try:
                    check_proc = await asyncio.create_subprocess_exec(
                        "lxc", "exec", container_name, "--", "which", "tmate",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await check_proc.communicate()
                    
                    if check_proc.returncode != 0:
                        await interaction.followup.send(
                            embed=create_info_embed("Installing", "Installing tmate..."),
                            ephemeral=True
                        )
                        await execute_lxc(f"lxc exec {container_name} -- apt-get update -y")
                        await execute_lxc(f"lxc exec {container_name} -- apt-get install tmate -y")
                    
                    session_name = f"uia-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    await execute_lxc(f"lxc exec {container_name} -- tmate -S /tmp/{session_name}.sock new-session -d")
                    await asyncio.sleep(3)
                    
                    ssh_proc = await asyncio.create_subprocess_exec(
                        "lxc", "exec", container_name, "--", "tmate", "-S", f"/tmp/{session_name}.sock", "display", "-p", "#{tmate_ssh}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await ssh_proc.communicate()
                    ssh_url = stdout.decode().strip() if stdout else None
                    
                    if ssh_url:
                        try:
                            ssh_embed = create_success_embed("🔑 SSH Access", f"VPS: `{container_name}`")
                            add_field(ssh_embed, "Connection", f"```\n{ssh_url}\n```", False)
                            add_field(ssh_embed, "⚠️ Security", "This link is temporary. Do not share it.", False)
                            await interaction.user.send(embed=ssh_embed)
                            await interaction.followup.send(
                                embed=create_success_embed("SSH Sent", f"Check your DMs for the SSH link!"),
                                ephemeral=True
                            )
                        except discord.Forbidden:
                            await interaction.followup.send(
                                embed=create_error_embed("DM Failed", "Enable DMs to receive SSH link!"),
                                ephemeral=True
                            )
                    else:
                        await interaction.followup.send(
                            embed=create_error_embed("SSH Failed", "Could not generate SSH link."),
                            ephemeral=True
                        )
                except Exception as e:
                    await interaction.followup.send(
                        embed=create_error_embed("SSH Error", str(e)),
                        ephemeral=True
                    )
            
            # Update the embed
            new_embed = await self.create_vps_embed(self.selected_index)
            await interaction.edit_original_response(embed=new_embed, view=self)
            
        except Exception as e:
            await interaction.followup.send(
                embed=create_error_embed("Action Failed", str(e)),
                ephemeral=True
            )

# ============================================================
# PORT FORWARDING COMMANDS
# ============================================================

@bot.command(name='ports')
async def ports_command(ctx, subcmd: str = None, *args):
    """Manage port forwarding (TCP/UDP)"""
    user_id = str(ctx.author.id)
    allocated = get_user_allocation(user_id)
    used = get_user_used_ports(user_id)
    available = allocated - used
    
    if subcmd is None:
        embed = create_info_embed("🔌 Port Forwarding", f"**Your Quota:** {used}/{allocated} used")
        add_field(embed, "Commands", 
                 f"`{PREFIX}ports add <vps_num> <port>` - Add forward\n"
                 f"`{PREFIX}ports list` - List forwards\n"
                 f"`{PREFIX}ports remove <id>` - Remove forward", False)
        await ctx.send(embed=embed)
        return
    
    if subcmd == 'add':
        if len(args) < 2:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: `{PREFIX}ports add <vps_num> <port>`"))
            return
        
        try:
            vps_num = int(args[0])
            vps_port = int(args[1])
            if vps_port < 1 or vps_port > 65535:
                raise ValueError
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "VPS number and port must be positive integers (port: 1-65535)."))
            return
        
        vps_list = vps_data.get(user_id, [])
        if vps_num < 1 or vps_num > len(vps_list):
            await ctx.send(embed=create_error_embed("Invalid VPS", f"Invalid VPS number (1-{len(vps_list)})."))
            return
        
        vps = vps_list[vps_num - 1]
        container = vps['container_name']
        
        if used >= allocated:
            await ctx.send(embed=create_error_embed("Quota Exceeded", 
                f"No available slots. Used: {used}/{allocated}. Contact admin for more."))
            return
        
        host_port = await create_port_forward(user_id, container, vps_port)
        if host_port:
            embed = create_success_embed("Port Forward Created", 
                f"VPS #{vps_num} port {vps_port} → Host port {host_port}")
            add_field(embed, "Access", f"`{YOUR_SERVER_IP}:{host_port}` → VPS `{vps_port}` (TCP & UDP)", False)
            add_field(embed, "Quota", f"Used: {used + 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Failed", "Could not assign host port. Try again."))
    
    elif subcmd == 'list':
        forwards = get_user_forwards(user_id)
        embed = create_info_embed("Your Port Forwards", f"Quota: {used}/{allocated}")
        if not forwards:
            add_field(embed, "Forwards", "No active port forwards.", False)
        else:
            text = []
            for f in forwards[:10]:
                vps_num = next((i+1 for i, v in enumerate(vps_data.get(user_id, [])) 
                               if v['container_name'] == f['vps_container']), 'Unknown')
                created = datetime.fromisoformat(f['created_at']).strftime('%Y-%m-%d %H:%M')
                text.append(f"**ID {f['id']}** - VPS #{vps_num}: {f['vps_port']} → {f['host_port']} (TCP/UDP)")
            add_field(embed, "Active Forwards", "\n".join(text), False)
            if len(forwards) > 10:
                add_field(embed, "Note", f"Showing 10 of {len(forwards)}. Use `{PREFIX}ports remove <id>`", False)
        await ctx.send(embed=embed)
    
    elif subcmd == 'remove':
        if len(args) < 1:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: `{PREFIX}ports remove <forward_id>`"))
            return
        try:
            fid = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Forward ID must be an integer."))
            return
        
        success, _ = await remove_port_forward(fid)
        if success:
            embed = create_success_embed("Removed", f"Port forward {fid} removed.")
            add_field(embed, "Quota", f"Used: {used - 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Not Found", "Forward ID not found. Use `!ports list`."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Subcommand", "Use: `add`, `list`, `remove`"))

def get_user_forwards(user_id: str) -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM port_forwards WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ============================================================
# ADMIN COMMANDS
# ============================================================

@bot.command(name='admin-add')
@is_main_admin()
async def admin_add(ctx, user: discord.Member):
    """Add a user as admin"""
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Already Admin", "This user is the main admin!"))
        return
    if user_id in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Already Admin", f"{user.mention} is already an admin!"))
        return
    admin_data["admins"].append(user_id)
    save_admin_data()
    log_audit(str(ctx.author.id), ctx.author.name, "admin_add", f"Added {user.name} as admin")
    await ctx.send(embed=create_success_embed("Admin Added", f"{user.mention} is now an admin!"))
    
    try:
        await user.send(embed=create_success_embed("🎉 Admin Role", f"You are now an admin for {BOT_NAME}!"))
    except:
        pass

@bot.command(name='admin-remove')
@is_main_admin()
async def admin_remove(ctx, user: discord.Member):
    """Remove a user as admin"""
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Cannot Remove", "You cannot remove the main admin!"))
        return
    if user_id not in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Not Admin", f"{user.mention} is not an admin!"))
        return
    admin_data["admins"].remove(user_id)
    save_admin_data()
    log_audit(str(ctx.author.id), ctx.author.name, "admin_remove", f"Removed {user.name} as admin")
    await ctx.send(embed=create_success_embed("Admin Removed", f"{user.mention} is no longer an admin."))
    
    try:
        await user.send(embed=create_warning_embed("Admin Role Removed", f"Your admin role has been removed."))
    except:
        pass

@bot.command(name='admin-list')
@is_main_admin()
async def admin_list(ctx):
    """List all admins"""
    admins = admin_data.get("admins", [])
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
    
    embed = create_embed("👑 Admin Team", "Current administrators:")
    add_field(embed, "🔰 Main Admin", f"{main_admin.mention} (ID: {MAIN_ADMIN_ID})", False)
    
    if admins:
        admin_list = []
        for admin_id in admins:
            try:
                admin_user = await bot.fetch_user(int(admin_id))
                admin_list.append(f"• {admin_user.mention} (ID: {admin_id})")
            except:
                admin_list.append(f"• Unknown User (ID: {admin_id})")
        add_field(embed, "🛡️ Admins", "\n".join(admin_list), False)
    else:
        add_field(embed, "🛡️ Admins", "No additional admins", False)
    await ctx.send(embed=embed)

@bot.command(name='serverstats')
@is_admin()
async def server_stats(ctx):
    """View server statistics"""
    total_users = len(vps_data)
    total_vps = sum(len(v) for v in vps_data.values())
    
    total_ram = 0
    total_cpu = 0
    total_storage = 0
    running_vps = 0
    suspended_vps = 0
    whitelisted_vps = 0
    
    for vps_list in vps_data.values():
        for vps in vps_list:
            ram_gb = int(vps['ram'].replace('GB', ''))
            storage_gb = int(vps['storage'].replace('GB', ''))
            total_ram += ram_gb
            total_cpu += int(vps['cpu'])
            total_storage += storage_gb
            
            if vps.get('status') == 'running':
                if vps.get('suspended', False):
                    suspended_vps += 1
                else:
                    running_vps += 1
            if vps.get('whitelisted', False):
                whitelisted_vps += 1
    
    # Port stats
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT SUM(allocated_ports) FROM port_allocations')
    total_ports_allocated = cur.fetchone()[0] or 0
    cur.execute('SELECT COUNT(*) FROM port_forwards')
    total_ports_used = cur.fetchone()[0]
    conn.close()
    
    # Host stats
    cpu_usage = get_cpu_usage()
    ram_usage = get_ram_usage()
    
    embed = create_embed("📊 Server Statistics", "Current server overview")
    add_field(embed, "👥 Users", 
             f"**Total Users:** {total_users}\n"
             f"**Admins:** {len(admin_data.get('admins', [])) + 1}", False)
    add_field(embed, "🖥️ VPS", 
             f"**Total:** {total_vps}\n"
             f"**Running:** {running_vps}\n"
             f"**Suspended:** {suspended_vps}\n"
             f"**Whitelisted:** {whitelisted_vps}", False)
    add_field(embed, "📈 Resources", 
             f"**Total RAM:** {total_ram}GB\n"
             f"**Total CPU:** {total_cpu} cores\n"
             f"**Total Storage:** {total_storage}GB", False)
    add_field(embed, "🌐 Ports", 
             f"**Allocated:** {total_ports_allocated}\n"
             f"**In Use:** {total_ports_used}", False)
    add_field(embed, "🖥️ Host", 
             f"**CPU:** {cpu_usage:.1f}%\n"
             f"**RAM:** {ram_usage:.1f}%", False)
    await ctx.send(embed=embed)

@bot.command(name='delete-vps')
@is_admin()
async def delete_vps(ctx, user: discord.Member, vps_number: int, *, reason: str = "No reason"):
    """Delete a user's VPS"""
    user_id = str(user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number."))
        return
    
    vps = vps_data[user_id][vps_number - 1]
    container_name = vps["container_name"]
    
    # Remove port forwards
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM port_forwards WHERE vps_container = ?', (container_name,))
    conn.commit()
    conn.close()
    
    await ctx.send(embed=create_info_embed("Deleting VPS", f"Removing VPS `{container_name}`..."))
    
    try:
        await execute_lxc(f"lxc delete {container_name} --force")
        del vps_data[user_id][vps_number - 1]
        if not vps_data[user_id]:
            del vps_data[user_id]
        save_vps_data()
        log_audit(str(ctx.author.id), ctx.author.name, "vps_delete", f"Deleted {container_name} for {user.name}")
        
        embed = create_success_embed("VPS Deleted")
        add_field(embed, "Owner", user.mention, True)
        add_field(embed, "Container", f"`{container_name}`", True)
        add_field(embed, "Reason", reason, False)
        await ctx.send(embed=embed)
        
        try:
            dm_embed = create_warning_embed("VPS Deleted", 
                f"Your VPS `{container_name}` has been deleted.\n**Reason:** {reason}")
            await user.send(embed=dm_embed)
        except:
            pass
    except Exception as e:
        await ctx.send(embed=create_error_embed("Deletion Failed", str(e)))

@bot.command(name='suspend-vps')
@is_admin()
async def suspend_vps(ctx, container_name: str, *, reason: str = "Admin action"):
    """Suspend a VPS"""
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if vps.get('suspended', False):
                    await ctx.send(embed=create_error_embed("Already Suspended", "VPS is already suspended."))
                    return
                try:
                    await execute_lxc(f"lxc stop {container_name}")
                    vps['status'] = 'stopped'
                    vps['suspended'] = True
                    if 'suspension_history' not in vps:
                        vps['suspension_history'] = []
                    vps['suspension_history'].append({
                        'time': datetime.now().isoformat(),
                        'reason': reason,
                        'by': f"{ctx.author.name}"
                    })
                    save_vps_data()
                    log_audit(str(ctx.author.id), ctx.author.name, "vps_suspend", f"Suspended {container_name}")
                    
                    try:
                        owner = await bot.fetch_user(int(uid))
                        dm_embed = create_warning_embed("VPS Suspended", 
                            f"Your VPS `{container_name}` has been suspended.\n**Reason:** {reason}")
                        await owner.send(embed=dm_embed)
                    except:
                        pass
                    
                    await ctx.send(embed=create_success_embed("VPS Suspended", 
                        f"`{container_name}` suspended. Reason: {reason}"))
                    found = True
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Suspend Failed", str(e)))
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='unsuspend-vps')
@is_admin()
async def unsuspend_vps(ctx, container_name: str):
    """Unsuspend a VPS"""
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if not vps.get('suspended', False):
                    await ctx.send(embed=create_error_embed("Not Suspended", "VPS is not suspended."))
                    return
                try:
                    vps['suspended'] = False
                    vps['status'] = 'running'
                    await execute_lxc(f"lxc start {container_name}")
                    await apply_internal_permissions(container_name)
                    await recreate_port_forwards(container_name)
                    save_vps_data()
                    log_audit(str(ctx.author.id), ctx.author.name, "vps_unsuspend", f"Unsuspended {container_name}")
                    await ctx.send(embed=create_success_embed("VPS Unsuspended", f"`{container_name}` has been unsuspended."))
                    found = True
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Failed", str(e)))
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='add-resources')
@is_admin()
async def add_resources(ctx, container_name: str, ram: int = None, cpu: int = None, disk: int = None):
    """Add resources to a VPS"""
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", 
            "Specify at least one: `ram`, `cpu`, or `disk`"))
        return
    
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("Not Found", f"No VPS found: `{container_name}`"))
        return
    
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping `{container_name}` to apply changes..."))
        try:
            await execute_lxc(f"lxc stop {container_name}")
            found_vps['status'] = 'stopped'
            save_vps_data()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", str(e)))
            return
    
    changes = []
    try:
        current_ram = int(found_vps['ram'].replace('GB', ''))
        current_cpu = int(found_vps['cpu'])
        current_disk = int(found_vps['storage'].replace('GB', ''))
        
        if ram is not None and ram > 0:
            new_ram = current_ram + ram
            await execute_lxc(f"lxc config set {container_name} limits.memory {new_ram * 1024}MB")
            changes.append(f"RAM: +{ram}GB → {new_ram}GB")
            found_vps['ram'] = f"{new_ram}GB"
        
        if cpu is not None and cpu > 0:
            new_cpu = current_cpu + cpu
            await execute_lxc(f"lxc config set {container_name} limits.cpu {new_cpu}")
            changes.append(f"CPU: +{cpu} cores → {new_cpu} cores")
            found_vps['cpu'] = str(new_cpu)
        
        if disk is not None and disk > 0:
            new_disk = current_disk + disk
            await execute_lxc(f"lxc config device set {container_name} root size={new_disk}GB")
            changes.append(f"Disk: +{disk}GB → {new_disk}GB")
            found_vps['storage'] = f"{new_disk}GB"
        
        found_vps['config'] = f"{int(found_vps['ram'].replace('GB', ''))}GB RAM / {found_vps['cpu']} CPU / {int(found_vps['storage'].replace('GB', ''))}GB Disk"
        vps_data[user_id][vps_index] = found_vps
        save_vps_data()
        
        if was_running:
            await execute_lxc(f"lxc start {container_name}")
            found_vps['status'] = 'running'
            save_vps_data()
            await apply_internal_permissions(container_name)
            await recreate_port_forwards(container_name)
        
        embed = create_success_embed("Resources Added", f"VPS `{container_name}` updated successfully!")
        add_field(embed, "Changes", "\n".join(changes), False)
        if disk is not None:
            add_field(embed, "Disk Note", "Run `sudo resize2fs /` inside the VPS to expand the filesystem.", False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Failed", str(e)))

# ============================================================
# HELP COMMAND
# ============================================================

@bot.command(name='help')
async def show_help(ctx):
    """Show the help menu"""
    user_id = str(ctx.author.id)
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
    
    embed = create_embed("📚 Help Menu", f"Welcome to **{BOT_NAME}** VPS Management Bot!\n\nUse the commands below to manage your VPS.")
    
    # User commands
    user_commands = [
        f"`{PREFIX}ping` - Check bot latency",
        f"`{PREFIX}uptime` - Show host uptime",
        f"`{PREFIX}myvps` - List your VPS",
        f"`{PREFIX}manage` - Manage your VPS",
        f"`{PREFIX}ports` - Manage port forwarding",
        f"`{PREFIX}about` - About the bot",
    ]
    add_field(embed, "👤 User Commands", "\n".join(user_commands), False)
    
    # Admin commands
    if is_admin_user:
        admin_commands = [
            f"`{PREFIX}create <ram> <cpu> <disk> @user` - Create VPS",
            f"`{PREFIX}delete-vps @user <num> [reason]` - Delete VPS",
            f"`{PREFIX}add-resources <container> [ram] [cpu] [disk]` - Add resources",
            f"`{PREFIX}suspend-vps <container> [reason]` - Suspend VPS",
            f"`{PREFIX}unsuspend-vps <container>` - Unsuspend VPS",
            f"`{PREFIX}serverstats` - Server statistics",
            f"`{PREFIX}userinfo @user` - User information",
            f"`{PREFIX}list-all` - List all VPS",
            f"`{PREFIX}restart-vps <container>` - Restart VPS",
            f"`{PREFIX}exec <container> <command>` - Execute command",
            f"`{PREFIX}stop-vps-all` - Stop all VPS",
            f"`{PREFIX}snapshot <container> [name]` - Create snapshot",
        ]
        add_field(embed, "🛡️ Admin Commands", "\n".join(admin_commands), False)
    
    # Main admin commands
    if is_main_admin_user:
        main_admin_commands = [
            f"`{PREFIX}admin-add @user` - Add admin",
            f"`{PREFIX}admin-remove @user` - Remove admin",
            f"`{PREFIX}admin-list` - List admins",
        ]
        add_field(embed, "👑 Main Admin Commands", "\n".join(main_admin_commands), False)
    
    add_field(embed, "📖 Need Help?", 
             "Contact an admin for assistance.\n"
             f"Server IP: `{YOUR_SERVER_IP}`", False)
    
    await ctx.send(embed=embed)

# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(name="vps_status", description="Check your VPS status")
async def slash_vps_status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    vps_list = vps_data.get(user_id, [])
    
    if not vps_list:
        embed = create_error_embed("No VPS", "You don't have any VPS.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    embed = create_info_embed("My VPS", f"You have **{len(vps_list)}** VPS instances:")
    text = []
    for i, vps in enumerate(vps_list):
        status = vps.get('status', 'unknown').upper()
        if vps.get('suspended', False):
            status = f"⛔ {status} (SUSPENDED)"
        elif status == 'RUNNING':
            status = f"🟢 {status}"
        elif status == 'STOPPED':
            status = f"🔴 {status}"
        text.append(f"**#{i+1}** `{vps['container_name']}` | {status}")
    
    add_field(embed, "Your VPS", "\n".join(text), False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_manage", description="Manage your VPS")
async def slash_vps_manage(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    vps_list = vps_data.get(user_id, [])
    
    if not vps_list:
        embed = create_error_embed("No VPS", "You don't have any VPS.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    view = ManageView(user_id, vps_list)
    embed = await view.get_initial_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ============================================================
# RUN THE BOT
# ============================================================

if __name__ == "__main__":
    if DISCORD_TOKEN:
        print(f"""
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║   ██╗   ██╗██╗ █████╗     ██╗  ██╗ ██████╗ ███████╗████████╗       ║
║   ██║   ██║██║██╔══██╗    ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝       ║
║   ██║   ██║██║███████║    ███████║██║   ██║███████╗   ██║          ║
║   ██║   ██║██║██╔══██║    ██╔══██║██║   ██║╚════██║   ██║          ║
║   ╚██████╔╝██║██║  ██║    ██║  ██║╚██████╔╝███████║   ██║          ║
║    ╚═════╝ ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝          ║
║                                                                    ║
║                         UIA HOST VPS MANAGER                       ║
║                            Created by REONDEV                      ║
║                               Version 3.0.0                        ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
        """)
        logger.info(f"Starting {BOT_NAME} VPS Bot...")
        bot.run(DISCORD_TOKEN)
    else:
        logger.error("No Discord token found in DISCORD_TOKEN environment variable.")
        sys.exit(1)