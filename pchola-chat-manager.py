import os
import re
import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

DATA_FILE = "data.json"


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # Нужен для префиксных команд

bot = commands.Bot(command_prefix="!", intents=intents)


DEFAULT_DATA = {
    "warnings": {},
    "responses": {}
}


DEFAULT_RESPONSES = {
    "ban": {
        "success": "Пользователь {user} был забанен. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды !ban."
    },
    "kick": {
        "success": "Пользователь {user} был кикнут. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды !kick."
    },
    "mute": {
        "success": "Пользователь {user} был замучен на {duration}. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды !mute."
    },
    "unmute": {
        "success": "Пользователь {user} был размучен.",
        "noadmin": "У тебя нет прав для использования команды !unmute."
    },
    "warn": {
        "success": "Пользователь {user} получил предупреждение. Всего предупреждений: {count}. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды !warn."
    },
    "warnings": {
        "success": "Предупреждения пользователя {user}: {warnings}",
        "noadmin": "У тебя нет прав для использования команды !warnings."
    },
    "mywarn": {
        "success": "Твои предупреждения: {warnings}",
        "noadmin": ""
    },
    "clear": {
        "success": "Сообщение было удалено.",
        "noadmin": "У тебя нет прав для использования команды !clear."
    },
    "lock": {
        "success": "Канал {channel} был закрыт.",
        "noadmin": "У тебя нет прав для использования команды !lock."
    },
    "unlock": {
        "success": "Канал {channel} был открыт.",
        "noadmin": "У тебя нет прав для использования команды !unlock."
    },
    "purge": {
        "success": "Удалено сообщений пользователя {user}: {count}",
        "noadmin": "У тебя нет прав для использования команды !purge."
    },
    "configure": {
        "success": "Ответы для команды /{command} обновлены.",
        "noadmin": "У тебя нет прав для использования команды /configure."
    }
}


def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


data = load_data()


def get_guild_data(guild_id: int):
    guild_id = str(guild_id)

    if guild_id not in data["warnings"]:
        data["warnings"][guild_id] = {}

    if guild_id not in data["responses"]:
        data["responses"][guild_id] = {}

    return data["warnings"][guild_id], data["responses"][guild_id]


def is_admin(member: discord.Member) -> bool:
    permissions = member.guild_permissions
    return (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_messages
        or permissions.ban_members
        or permissions.kick_members
        or permissions.moderate_members
    )


def is_real_admin(member: discord.Member) -> bool:
    permissions = member.guild_permissions
    return permissions.administrator or permissions.manage_guild


def get_response(guild_id: int, command_name: str, response_type: str) -> str:
    _, guild_responses = get_guild_data(guild_id)
    custom = guild_responses.get(command_name, {}).get(response_type)

    if custom is not None:
        return custom

    return DEFAULT_RESPONSES.get(command_name, {}).get(response_type, "")


async def send_response(ctx: commands.Context, command_name: str, response_type: str = "success", **kwargs):
    template = get_response(ctx.guild.id, command_name, response_type)

    if template == "":
        return

    try:
        message = template.format_map(kwargs)
    except Exception:
        message = template

    await ctx.send(message)


async def check_admin(ctx: commands.Context, command_name: str) -> bool:
    if not ctx.guild:
        await ctx.send("Эта команда работает только на сервере.")
        return False

    if is_admin(ctx.author):
        return True

    await send_response(ctx, command_name, response_type="noadmin")
    return False


def parse_duration(duration: str) -> int:
    """
    Поддерживает любую комбинацию:
    1h
    34m
    12m 58s
    12h 23m 22s
    1243124s
    1d 2h 3m 4s
    """
    duration = duration.lower().strip()
    pattern = r"(\d+)\s*(d|h|m|s)"
    matches = re.findall(pattern, duration)

    if not matches:
        raise ValueError("Неверный формат времени.")

    total_seconds = 0

    for value, unit in matches:
        value = int(value)

        if unit == "d":
            total_seconds += value * 86400
        elif unit == "h":
            total_seconds += value * 3600
        elif unit == "m":
            total_seconds += value * 60
        elif unit == "s":
            total_seconds += value

    return total_seconds


def human_duration(seconds: int) -> str:
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []

    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else "0s"


def can_act_on_member(moderator: discord.Member, target: discord.Member) -> bool:
    if moderator.guild.owner_id == moderator.id:
        return True
    return moderator.top_role > target.top_role


def bot_can_act_on_member(guild: discord.Guild, target: discord.Member) -> bool:
    me = guild.me
    if me is None:
        return False
    return me.top_role > target.top_role


async def ensure_target_allowed(ctx: commands.Context, target: discord.Member) -> bool:
    if target.id == ctx.guild.owner_id:
        await ctx.send("Нельзя применить действие к владельцу сервера.")
        return False

    if target.id == bot.user.id:
        await ctx.send("Нельзя применить действие к боту.")
        return False

    if target.id == ctx.author.id:
        await ctx.send("Нельзя применить действие к самому себе.")
        return False

    if not can_act_on_member(ctx.author, target):
        await ctx.send("Ты не можешь применить действие к пользователю с ролью выше или равной твоей.")
        return False

    if not bot_can_act_on_member(ctx.guild, target):
        await ctx.send("Я не могу применить действие к этому пользователю. Моя роль должна быть выше его роли.")
        return False

    return True


def get_user_warnings(guild_id: int, user_id: int):
    warnings, _ = get_guild_data(guild_id)
    user_id = str(user_id)

    if user_id not in warnings:
        warnings[user_id] = []

    return warnings[user_id]


def parse_mute_args(args: tuple) -> tuple[discord.Member | None, int, str]:
    """
    Парсит аргументы команды !mute.
    Возвращает (member, seconds, reason).
    Формат: !mute @user [длительность] [причина]
    Длительность — любая комбинация: 1h, 30m, 1h 30m, 12m 58s и т.д.
    """
    # args[0] — это уже resolved member через конвертер
    # остальное — строка с временем и причиной
    return None  # не используется, см. команду ниже



# ─────────────────────────────────────────────
#                  КОМАНДЫ
# ─────────────────────────────────────────────

@bot.command(name="ban")
async def ban_command(ctx: commands.Context, user: discord.Member, *, reason: str = "Причина не указана"):
    if not await check_admin(ctx, "ban"):
        return

    if not await ensure_target_allowed(ctx, user):
        return

    await user.ban(reason=f"{reason} | Moderator: {ctx.author}")
    await send_response(ctx, "ban", user=user.mention, moderator=ctx.author.mention, reason=reason)


@bot.command(name="kick")
async def kick_command(ctx: commands.Context, user: discord.Member, *, reason: str = "Причина не указана"):
    if not await check_admin(ctx, "kick"):
        return

    if not await ensure_target_allowed(ctx, user):
        return

    await user.kick(reason=f"{reason} | Moderator: {ctx.author}")
    await send_response(ctx, "kick", user=user.mention, moderator=ctx.author.mention, reason=reason)


@bot.command(name="mute")
async def mute_command(ctx: commands.Context, user: discord.Member, *, args: str = ""):
    if not await check_admin(ctx, "mute"):
        return

    if not await ensure_target_allowed(ctx, user):
        return

    # Парсим время из начала строки args, остаток — причина
    # Паттерн: одна или несколько групп вида "число + d/h/m/s"
    duration_pattern = r"^((?:\d+\s*[dhms]\s*)+)"
    match = re.match(duration_pattern, args.strip(), re.IGNORECASE)

    if not match:
        await ctx.send("Укажи время. Пример: `!mute @user 1h 30m причина`")
        return

    duration_str = match.group(1).strip()
    reason = args[match.end():].strip() or "Причина не указана"

    try:
        seconds = parse_duration(duration_str)
    except ValueError:
        await ctx.send("Неверный формат времени. Пример: `1h`, `30m`, `1h 30m`, `12m 58s`")
        return

    if seconds <= 0:
        await ctx.send("Время мута должно быть больше 0 секунд.")
        return

    max_timeout_seconds = 28 * 24 * 60 * 60

    if seconds > max_timeout_seconds:
        await ctx.send("Discord timeout не может быть больше 28 дней.")
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await user.timeout(until, reason=f"{reason} | Moderator: {ctx.author}")
    await send_response(
        ctx, "mute",
        user=user.mention,
        moderator=ctx.author.mention,
        duration=human_duration(seconds),
        reason=reason
    )


@bot.command(name="unmute")
async def unmute_command(ctx: commands.Context, user: discord.Member):
    if not await check_admin(ctx, "unmute"):
        return

    if not await ensure_target_allowed(ctx, user):
        return

    await user.timeout(None, reason=f"Unmute | Moderator: {ctx.author}")
    await send_response(ctx, "unmute", user=user.mention, moderator=ctx.author.mention)


@bot.command(name="warn")
async def warn_command(ctx: commands.Context, user: discord.Member, *, reason: str = "Причина не указана"):
    if not await check_admin(ctx, "warn"):
        return

    warnings = get_user_warnings(ctx.guild.id, user.id)

    warnings.append({
        "reason": reason,
        "moderator_id": ctx.author.id,
        "moderator_name": str(ctx.author),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    save_data(data)
    await send_response(
        ctx, "warn",
        user=user.mention,
        moderator=ctx.author.mention,
        reason=reason,
        count=len(warnings)
    )


@bot.command(name="warnings")
async def warnings_command(ctx: commands.Context, user: discord.Member):
    if not await check_admin(ctx, "warnings"):
        return

    warnings = get_user_warnings(ctx.guild.id, user.id)

    if not warnings:
        warnings_text = "нет предупреждений"
    else:
        lines = []
        for index, warn in enumerate(warnings, start=1):
            reason = warn.get("reason", "Причина не указана")
            moderator_name = warn.get("moderator_name", "Unknown")
            created_at = warn.get("created_at", "Unknown date")
            lines.append(f"{index}. {reason} | Модератор: {moderator_name} | Дата: {created_at}")
        warnings_text = "\n".join(lines)

    await send_response(ctx, "warnings", user=user.mention, warnings=warnings_text)


@bot.command(name="mywarn")
async def mywarn_command(ctx: commands.Context):
    if not ctx.guild:
        await ctx.send("Только на сервере.")
        return

    warnings = get_user_warnings(ctx.guild.id, ctx.author.id)

    if not warnings:
        warnings_text = "нет предупреждений"
    else:
        lines = []
        for index, warn in enumerate(warnings, start=1):
            reason = warn.get("reason", "Причина не указана")
            moderator_name = warn.get("moderator_name", "Unknown")
            created_at = warn.get("created_at", "Unknown date")
            lines.append(f"{index}. {reason} | Модератор: {moderator_name} | Дата: {created_at}")
        warnings_text = "\n".join(lines)

    await send_response(ctx, "mywarn", user=ctx.author.mention, warnings=warnings_text)


@bot.command(name="clear")
async def clear_command(ctx: commands.Context):
    if not await check_admin(ctx, "clear"):
        return

    # Удаляем команду !clear
    await ctx.message.delete()

    # Если это ответ на сообщение — удаляем то сообщение
    if ctx.message.reference and ctx.message.reference.message_id:
        try:
            target_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            await target_message.delete()
            await send_response(ctx, "clear", moderator=ctx.author.mention)
        except discord.NotFound:
            await ctx.send("Сообщение не найдено.", delete_after=5)
    else:
        await ctx.send("Ответь на сообщение которое нужно удалить.", delete_after=5)


@bot.command(name="lock")
async def lock_command(ctx: commands.Context):
    if not await check_admin(ctx, "lock"):
        return

    channel = ctx.channel

    if not isinstance(channel, discord.TextChannel):
        await ctx.send("Эта команда работает только в текстовом канале.")
        return

    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False

    await channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite,
        reason=f"Channel locked by {ctx.author}"
    )

    await send_response(ctx, "lock", channel=channel.mention, moderator=ctx.author.mention)


@bot.command(name="unlock")
async def unlock_command(ctx: commands.Context):
    if not await check_admin(ctx, "unlock"):
        return

    channel = ctx.channel

    if not isinstance(channel, discord.TextChannel):
        await ctx.send("Эта команда работает только в текстовом канале.")
        return

    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None

    await channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite,
        reason=f"Channel unlocked by {ctx.author}"
    )

    await send_response(ctx, "unlock", channel=channel.mention, moderator=ctx.author.mention)


@bot.command(name="purge")
async def purge_command(ctx: commands.Context, user: discord.Member, scan_limit: int = 1000):
    if not await check_admin(ctx, "purge"):
        return

    channel = ctx.channel

    if not isinstance(channel, discord.TextChannel):
        await ctx.send("Эта команда работает только в текстовом канале.")
        return

    if scan_limit < 1:
        scan_limit = 1

    if scan_limit > 10000:
        scan_limit = 10000

    await ctx.message.delete()

    deleted = await channel.purge(
        limit=scan_limit,
        check=lambda msg: msg.author.id == user.id,
        reason=f"Purge by {ctx.author}"
    )

    await send_response(ctx, "purge", user=user.mention, moderator=ctx.author.mention, count=len(deleted))


# ─────────────────────────────────────────────
#         КОНТЕКСТНЫЕ МЕНЮ (остаются slash)
# ─────────────────────────────────────────────

async def ctx_ban_author(interaction: discord.Interaction, message: discord.Message):
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав.", ephemeral=True)
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message("Автор сообщения не является участником сервера.", ephemeral=True)
        return

    target = message.author
    moderator = interaction.user

    if target.id == interaction.guild.owner_id:
        await interaction.response.send_message("Нельзя применить действие к владельцу сервера.", ephemeral=True)
        return

    if target.id == bot.user.id:
        await interaction.response.send_message("Нельзя применить действие к боту.", ephemeral=True)
        return

    if target.id == moderator.id:
        await interaction.response.send_message("Нельзя применить действие к самому себе.", ephemeral=True)
        return

    if not can_act_on_member(moderator, target):
        await interaction.response.send_message("Ты не можешь применить действие к этому пользователю.", ephemeral=True)
        return

    if not bot_can_act_on_member(interaction.guild, target):
        await interaction.response.send_message("Моя роль должна быть выше роли пользователя.", ephemeral=True)
        return

    reason = "Ban через контекстное меню"
    await target.ban(reason=f"{reason} | Moderator: {moderator}")
    await interaction.response.send_message(f"Пользователь {target.mention} был забанен.", ephemeral=True)


async def ctx_kick_author(interaction: discord.Interaction, message: discord.Message):
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав.", ephemeral=True)
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message("Автор сообщения не является участником сервера.", ephemeral=True)
        return

    target = message.author
    moderator = interaction.user

    if target.id == interaction.guild.owner_id:
        await interaction.response.send_message("Нельзя применить действие к владельцу сервера.", ephemeral=True)
        return

    if target.id == bot.user.id:
        await interaction.response.send_message("Нельзя применить действие к боту.", ephemeral=True)
        return

    if target.id == moderator.id:
        await interaction.response.send_message("Нельзя применить действие к самому себе.", ephemeral=True)
        return

    if not can_act_on_member(moderator, target):
        await interaction.response.send_message("Ты не можешь применить действие к этому пользователю.", ephemeral=True)
        return

    if not bot_can_act_on_member(interaction.guild, target):
        await interaction.response.send_message("Моя роль должна быть выше роли пользователя.", ephemeral=True)
        return

    reason = "Kick через контекстное меню"
    await target.kick(reason=f"{reason} | Moderator: {moderator}")
    await interaction.response.send_message(f"Пользователь {target.mention} был кикнут.", ephemeral=True)


async def ctx_mute_author(interaction: discord.Interaction, message: discord.Message):
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав.", ephemeral=True)
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message("Автор сообщения не является участником сервера.", ephemeral=True)
        return

    target = message.author
    moderator = interaction.user

    if target.id == interaction.guild.owner_id:
        await interaction.response.send_message("Нельзя применить действие к владельцу сервера.", ephemeral=True)
        return

    if target.id == bot.user.id:
        await interaction.response.send_message("Нельзя применить действие к боту.", ephemeral=True)
        return

    if target.id == moderator.id:
        await interaction.response.send_message("Нельзя применить действие к самому себе.", ephemeral=True)
        return

    if not can_act_on_member(moderator, target):
        await interaction.response.send_message("Ты не можешь применить действие к этому пользователю.", ephemeral=True)
        return

    if not bot_can_act_on_member(interaction.guild, target):
        await interaction.response.send_message("Моя роль должна быть выше роли пользователя.", ephemeral=True)
        return

    seconds = 3600
    reason = "Mute через контекстное меню (1ч)"
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await target.timeout(until, reason=f"{reason} | Moderator: {moderator}")
    await interaction.response.send_message(f"Пользователь {target.mention} замучен на 1h.", ephemeral=True)


async def ctx_unmute_author(interaction: discord.Interaction, message: discord.Message):
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав.", ephemeral=True)
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message("Автор сообщения не является участником сервера.", ephemeral=True)
        return

    target = message.author
    moderator = interaction.user

    if target.id == interaction.guild.owner_id:
        await interaction.response.send_message("Нельзя применить действие к владельцу сервера.", ephemeral=True)
        return

    if target.id == bot.user.id:
        await interaction.response.send_message("Нельзя применить действие к боту.", ephemeral=True)
        return

    if target.id == moderator.id:
        await interaction.response.send_message("Нельзя применить действие к самому себе.", ephemeral=True)
        return

    if not can_act_on_member(moderator, target):
        await interaction.response.send_message("Ты не можешь применить действие к этому пользователю.", ephemeral=True)
        return

    if not bot_can_act_on_member(interaction.guild, target):
        await interaction.response.send_message("Моя роль должна быть выше роли пользователя.", ephemeral=True)
        return

    await target.timeout(None, reason=f"Unmute через контекстное меню | Moderator: {moderator}")
    await interaction.response.send_message(f"Пользователь {target.mention} размучен.", ephemeral=True)


async def ctx_warn_author(interaction: discord.Interaction, message: discord.Message):
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав.", ephemeral=True)
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message("Автор сообщения не является участником сервера.", ephemeral=True)
        return

    target = message.author
    moderator = interaction.user
    reason = "Warn через контекстное меню"

    warnings = get_user_warnings(interaction.guild.id, target.id)

    warnings.append({
        "reason": reason,
        "moderator_id": moderator.id,
        "moderator_name": str(moderator),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_id": message.id,
        "channel_id": message.channel.id
    })

    save_data(data)
    await interaction.response.send_message(
        f"Пользователь {target.mention} получил предупреждение. Всего: {len(warnings)}.",
        ephemeral=True
    )


bot.tree.add_command(app_commands.ContextMenu(name="Ban author", callback=ctx_ban_author))
bot.tree.add_command(app_commands.ContextMenu(name="Kick author", callback=ctx_kick_author))
bot.tree.add_command(app_commands.ContextMenu(name="Mute author 1h", callback=ctx_mute_author))
bot.tree.add_command(app_commands.ContextMenu(name="Unmute author", callback=ctx_unmute_author))
bot.tree.add_command(app_commands.ContextMenu(name="Warn author", callback=ctx_warn_author))


# ─────────────────────────────────────────────
#           /configure (остаётся slash)
# ─────────────────────────────────────────────

@bot.tree.command(name="configure", description="Настроить ответы команд.")
@app_commands.describe(
    command="Название команды без ! или /, например ban, kick, mute",
    success_response="Ответ при успешном выполнении. Напиши - чтобы бот ничего не писал",
    noadmin_response="Ответ если команду написал не админ. Напиши - чтобы бот ничего не писал"
)
async def configure_command(
    interaction: discord.Interaction,
    command: str,
    success_response: str | None = None,
    noadmin_response: str | None = None
):
    if not interaction.guild:
        await interaction.response.send_message("Эта команда работает только на сервере.", ephemeral=True)
        return

    if not isinstance(interaction.user, discord.Member) or not is_real_admin(interaction.user):
        await interaction.response.send_message("У тебя нет прав для использования команды /configure.", ephemeral=True)
        return

    command = command.lower().strip()

    if command not in DEFAULT_RESPONSES:
        await interaction.response.send_message(f"Неизвестная команда `{command}`.", ephemeral=True)
        return

    _, guild_responses = get_guild_data(interaction.guild.id)

    if command not in guild_responses:
        guild_responses[command] = {}

    if success_response is not None:
        guild_responses[command]["success"] = "" if success_response == "-" else success_response

    if noadmin_response is not None:
        guild_responses[command]["noadmin"] = "" if noadmin_response == "-" else noadmin_response

    save_data(data)

    await interaction.response.send_message(f"Ответы для команды `{command}` обновлены.", ephemeral=True)


# ─────────────────────────────────────────────
#               ОБРАБОТКА ОШИБОК
# ─────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Не хватает аргумента: `{error.param.name}`.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("Пользователь не найден.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Неверный аргумент.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Игнорируем неизвестные команды
    else:
        raise error


@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано slash/context команд: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации команд: {e}")


if not TOKEN:
    raise RuntimeError("Не найден DISCORD_TOKEN в .env")

bot.run(TOKEN)
