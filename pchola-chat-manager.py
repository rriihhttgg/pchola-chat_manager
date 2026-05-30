import os
import re
import json
import asyncio
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
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)



DEFAULT_DATA = {
    "warnings": {},
    "responses": {}
}


DEFAULT_RESPONSES = {
    "ban": {
        "success": "Пользователь {user} был забанен. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды /ban."
    },
    "kick": {
        "success": "Пользователь {user} был кикнут. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды /kick."
    },
    "mute": {
        "success": "Пользователь {user} был замучен на {duration}. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды /mute."
    },
    "unmute": {
        "success": "Пользователь {user} был размучен.",
        "noadmin": "У тебя нет прав для использования команды /unmute."
    },
    "warn": {
        "success": "Пользователь {user} получил предупреждение. Всего предупреждений: {count}. Причина: {reason}",
        "noadmin": "У тебя нет прав для использования команды /warn."
    },
    "warnings": {
        "success": "Предупреждения пользователя {user}: {warnings}",
        "noadmin": "У тебя нет прав для использования команды /warnings."
    },
    "mywarn": {
        "success": "Твои предупреждения: {warnings}",
        "noadmin": ""
    },
    "clear": {
        "success": "Сообщение было удалено.",
        "noadmin": "У тебя нет прав для использования команды /clear."
    },
    "lock": {
        "success": "Канал {channel} был закрыт.",
        "noadmin": "У тебя нет прав для использования команды /lock."
    },
    "unlock": {
        "success": "Канал {channel} был открыт.",
        "noadmin": "У тебя нет прав для использования команды /unlock."
    },
    "purge": {
        "success": "Удалено сообщений пользователя {user}: {count}",
        "noadmin": "У тебя нет прав для использования команды /purge."
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


async def check_admin_or_reply(interaction: discord.Interaction, command_name: str) -> bool:
    if not interaction.guild:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.",
            ephemeral=True
        )
        return False

    if isinstance(interaction.user, discord.Member) and is_admin(interaction.user):
        return True

    await send_configured_response(
        interaction,
        command_name,
        response_type="noadmin",
        ephemeral=True
    )
    return False



# FIX: параметр называется response_type везде одинаково
def get_response(guild_id: int, command_name: str, response_type: str) -> str:
    _, guild_responses = get_guild_data(guild_id)
    custom = guild_responses.get(command_name, {}).get(response_type)

    if custom is not None:
        return custom

    return DEFAULT_RESPONSES.get(command_name, {}).get(response_type, "")


# FIX: **kwargs вместо kwargs
async def send_configured_response(
    interaction: discord.Interaction,
    command_name: str,
    response_type: str = "success",
    ephemeral: bool = False,
    **kwargs
):
    if not interaction.guild:
        return

    template = get_response(interaction.guild.id, command_name, response_type)

    if template == "":
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        return

    try:
        message = template.format_map(kwargs)
    except Exception:
        message = template

    if not interaction.response.is_done():
        await interaction.response.send_message(message, ephemeral=ephemeral)
    else:
        await interaction.followup.send(message, ephemeral=ephemeral)



def parse_duration(duration: str) -> int:
    """
    Поддерживает:
    1h
    34m
    12m 58s
    12h 23m 22s
    1243124s
    1d 2h 3m 4s
    """

    duration = duration.lower().strip()

    # FIX: \s* вместо \s — пробел между числом и буквой опционален
    pattern = r"(\d+)\s*(d|h|m|s)"
    matches = re.findall(pattern, duration)

    if not matches:
        raise ValueError("Неверный формат времени.")

    total_seconds = 0

    for value, unit in matches:
        value = int(value)

        if unit == "d":
            total_seconds += value * 86400  # FIX: было value 86400 (пропущен *)
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
    minutes, seconds = divmod(seconds, 60)  # FIX: был неправильный отступ

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


async def ensure_target_allowed(
    interaction: discord.Interaction,
    target: discord.Member
) -> bool:
    if not interaction.guild:
        return False

    moderator = interaction.user

    if not isinstance(moderator, discord.Member):
        return False

    if target.id == interaction.guild.owner_id:
        await interaction.response.send_message(
            "Нельзя применить действие к владельцу сервера.",
            ephemeral=True
        )
        return False

    if target.id == bot.user.id:
        await interaction.response.send_message(
            "Нельзя применить действие к боту.",
            ephemeral=True
        )
        return False

    if target.id == moderator.id:
        await interaction.response.send_message(
            "Нельзя применить действие к самому себе.",
            ephemeral=True
        )
        return False

    if not can_act_on_member(moderator, target):
        await interaction.response.send_message(
            "Ты не можешь применить действие к пользователю с ролью выше или равной твоей.",
            ephemeral=True
        )
        return False

    # FIX: был неправильный отступ
    if not bot_can_act_on_member(interaction.guild, target):
        await interaction.response.send_message(
            "Я не могу применить действие к этому пользователю. Моя роль должна быть выше его роли.",
            ephemeral=True
        )
        return False

    return True


# FIX: параметр переименован в user_id, исправлен unpacking
def get_user_warnings(guild_id: int, user_id: int):
    warnings, _ = get_guild_data(guild_id)

    user_id = str(user_id)

    if user_id not in warnings:
        warnings[user_id] = []

    return warnings[user_id]



@bot.tree.command(name="ban", description="Забанить пользователя навсегда.")
@app_commands.describe(
    user="Пользователь, которого нужно забанить",
    reason="Причина бана"
)
async def ban_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "Причина не указана"
):
    if not await check_admin_or_reply(interaction, "ban"):
        return

    if not await ensure_target_allowed(interaction, user):
        return

    await user.ban(reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "ban",
        user=user.mention,
        moderator=interaction.user.mention,
        reason=reason
    )


@bot.tree.command(name="kick", description="Кикнуть пользователя с сервера.")
@app_commands.describe(
    user="Пользователь, которого нужно кикнуть",
    reason="Причина кика"
)
async def kick_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "Причина не указана"
):
    if not await check_admin_or_reply(interaction, "kick"):
        return

    if not await ensure_target_allowed(interaction, user):
        return

    await user.kick(reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "kick",
        user=user.mention,
        moderator=interaction.user.mention,
        reason=reason
    )


@bot.tree.command(name="mute", description="Замутить пользователя на время.")
@app_commands.describe(
    user="Пользователь, которого нужно замутить",
    duration="Время: например 1h 34m, 12m 58s, 12h 23m 22s, 1243124s",
    reason="Причина мута"
)
async def mute_command(
    interaction: discord.Interaction,
    user: discord.Member,
    duration: str,
    reason: str = "Причина не указана"
):
    if not await check_admin_or_reply(interaction, "mute"):
        return

    if not await ensure_target_allowed(interaction, user):
        return

    try:
        seconds = parse_duration(duration)
    except ValueError:
        await interaction.response.send_message(
            "Неверный формат времени. Пример: 1h 34m, 12m 58s, 1243124s.",
            ephemeral=True
        )
        return

    if seconds <= 0:
        await interaction.response.send_message(
            "Время мута должно быть больше 0 секунд.",
            ephemeral=True
        )
        return

    max_timeout_seconds = 28 * 24 * 60 * 60

    if seconds > max_timeout_seconds:
        await interaction.response.send_message(
            "Discord timeout не может быть больше 28 дней.",
            ephemeral=True
        )
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    await user.timeout(until, reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "mute",
        user=user.mention,
        moderator=interaction.user.mention,
        duration=human_duration(seconds),
        reason=reason
    )


@bot.tree.command(name="unmute", description="Снять мут с пользователя.")
@app_commands.describe(
    user="Пользователь, которого нужно размутить"
)
async def unmute_command(
    interaction: discord.Interaction,
    user: discord.Member
):
    if not await check_admin_or_reply(interaction, "unmute"):
        return

    if not await ensure_target_allowed(interaction, user):
        return

    await user.timeout(None, reason=f"Unmute | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "unmute",
        user=user.mention,
        moderator=interaction.user.mention
    )


@bot.tree.command(name="warn", description="Выдать предупреждение пользователю.")
@app_commands.describe(
    user="Пользователь, которому нужно выдать предупреждение",
    reason="Причина предупреждения"
)
async def warn_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "Причина не указана"
):
    if not await check_admin_or_reply(interaction, "warn"):
        return

    warnings = get_user_warnings(interaction.guild.id, user.id)

    warnings.append({
        "reason": reason,
        "moderator_id": interaction.user.id,
        "moderator_name": str(interaction.user),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    save_data(data)

    await send_configured_response(
        interaction,
        "warn",
        user=user.mention,
        moderator=interaction.user.mention,
        reason=reason,
        count=len(warnings)
    )


@bot.tree.command(name="warnings", description="Посмотреть предупреждения пользователя.")
@app_commands.describe(
    user="Пользователь, чьи предупреждения нужно посмотреть"
)
async def warnings_command(
    interaction: discord.Interaction,
    user: discord.Member
):
    if not await check_admin_or_reply(interaction, "warnings"):
        return

    warnings = get_user_warnings(interaction.guild.id, user.id)

    if not warnings:
        warnings_text = "нет предупреждений"
    else:
        lines = []

        # FIX: был неправильный отступ
        for index, warn in enumerate(warnings, start=1):
            reason = warn.get("reason", "Причина не указана")
            moderator_name = warn.get("moderator_name", "Unknown")
            created_at = warn.get("created_at", "Unknown date")

            lines.append(
                f"{index}. {reason} | Модератор: {moderator_name} | Дата: {created_at}"
            )

        warnings_text = "\n".join(lines)

    await send_configured_response(
        interaction,
        "warnings",
        user=user.mention,
        warnings=warnings_text
    )


@bot.tree.command(name="mywarn", description="Посмотреть свои предупреждения.")
async def mywarn_command(interaction: discord.Interaction):
    # FIX: проверка гильдии перенесена до обращения к interaction.guild.id
    if not interaction.guild:
        await interaction.response.send_message("Только на сервере.", ephemeral=True)
        return

    warnings = get_user_warnings(interaction.guild.id, interaction.user.id)

    if not warnings:
        warnings_text = "нет предупреждений"
    else:
        lines = []

        for index, warn in enumerate(warnings, start=1):
            reason = warn.get("reason", "Причина не указана")
            moderator_name = warn.get("moderator_name", "Unknown")
            created_at = warn.get("created_at", "Unknown date")

            lines.append(
                f"{index}. {reason} | Модератор: {moderator_name} | Дата: {created_at}"
            )

        warnings_text = "\n".join(lines)

    await send_configured_response(
        interaction,
        "mywarn",
        user=interaction.user.mention,
        warnings=warnings_text,
        ephemeral=True
    )


@bot.tree.command(name="clear", description="Удалить сообщение по ID.")
@app_commands.describe(
    message_id="ID сообщения, которое нужно удалить"
)
async def clear_command(
    interaction: discord.Interaction,
    message_id: str
):
    if not await check_admin_or_reply(interaction, "clear"):
        return

    channel = interaction.channel

    # FIX: был неправильный отступ
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Эта команда работает только в текстовом канале.",
            ephemeral=True
        )
        return

    try:
        message_id_int = int(message_id)
        message = await channel.fetch_message(message_id_int)
    except Exception:
        await interaction.response.send_message(
            "Сообщение не найдено.",
            ephemeral=True
        )
        return

    await message.delete()

    await send_configured_response(
        interaction,
        "clear",
        moderator=interaction.user.mention
    )


@bot.tree.command(name="lock", description="Закрыть текущий канал для обычных пользователей.")
async def lock_command(interaction: discord.Interaction):
    if not await check_admin_or_reply(interaction, "lock"):
        return

    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Эта команда работает только в текстовом канале.",
            ephemeral=True
        )
        return

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False

    await channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite,
        reason=f"Channel locked by {interaction.user}"
    )

    await send_configured_response(
        interaction,
        "lock",
        channel=channel.mention,
        moderator=interaction.user.mention
    )


@bot.tree.command(name="unlock", description="Открыть текущий канал для обычных пользователей.")
async def unlock_command(interaction: discord.Interaction):
    if not await check_admin_or_reply(interaction, "unlock"):
        return

    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Эта команда работает только в текстовом канале.",
            ephemeral=True
        )
        return

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None

    await channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite,
        reason=f"Channel unlocked by {interaction.user}"
    )

    await send_configured_response(
        interaction,
        "unlock",
        channel=channel.mention,
        moderator=interaction.user.mention
    )


@bot.tree.command(name="purge", description="Удалить сообщения пользователя в текущем канале.")
@app_commands.describe(
    user="Пользователь, чьи сообщения нужно удалить",
    scan_limit="Сколько последних сообщений проверить. По умолчанию 1000"
)
async def purge_command(
    interaction: discord.Interaction,
    user: discord.Member,
    scan_limit: int = 1000
):
    if not await check_admin_or_reply(interaction, "purge"):
        return

    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Эта команда работает только в текстовом канале.",
            ephemeral=True
        )
        return

    if scan_limit < 1:
        scan_limit = 1

    if scan_limit > 10000:
        scan_limit = 10000

    await interaction.response.defer()

    deleted = await channel.purge(
        limit=scan_limit,
        check=lambda msg: msg.author.id == user.id,
        reason=f"Purge by {interaction.user}"
    )

    await send_configured_response(
        interaction,
        "purge",
        user=user.mention,
        moderator=interaction.user.mention,
        count=len(deleted)
    )


@bot.tree.command(name="configure", description="Настроить ответы команд.")
@app_commands.describe(
    command="Название команды без /, например ban, kick, mute",
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
        await interaction.response.send_message(
            "Эта команда работает только на сервере.",
            ephemeral=True
        )
        return

    if not isinstance(interaction.user, discord.Member) or not is_real_admin(interaction.user):
        await send_configured_response(
            interaction,
            "configure",
            response_type="noadmin",
            ephemeral=True
        )
        return

    command = command.lower().strip()

    if command not in DEFAULT_RESPONSES:
        # FIX: было sendmessage (без подчёркивания)
        await interaction.response.send_message(
            f"Неизвестная команда {command}.",
            ephemeral=True
        )
        return

    # FIX: было , guild_responses (сломанный unpacking)
    _, guild_responses = get_guild_data(interaction.guild.id)

    if command not in guild_responses:
        guild_responses[command] = {}

    if success_response is not None:
        if success_response == "-":
            success_response = ""
        guild_responses[command]["success"] = success_response

    if noadmin_response is not None:
        if noadmin_response == "-":
            noadmin_response = ""
        guild_responses[command]["noadmin"] = noadmin_response

    save_data(data)

    await send_configured_response(
        interaction,
        "configure",
        command=command
    )



async def ctx_ban_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    # FIX: был неправильный отступ
    if not await check_admin_or_reply(interaction, "ban"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    target = message.author

    if not await ensure_target_allowed(interaction, target):
        return

    reason = "Ban через контекстное меню сообщения"

    await target.ban(reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "ban",
        user=target.mention,
        moderator=interaction.user.mention,
        reason=reason
    )


async def ctx_kick_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "kick"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    target = message.author

    if not await ensure_target_allowed(interaction, target):
        return

    reason = "Kick через контекстное меню сообщения"

    await target.kick(reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "kick",
        user=target.mention,
        moderator=interaction.user.mention,
        reason=reason
    )


async def ctx_mute_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "mute"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    # FIX: был неправильный отступ
    target = message.author

    if not await ensure_target_allowed(interaction, target):
        return

    seconds = 3600
    reason = "Mute через контекстное меню сообщения"
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    await target.timeout(until, reason=f"{reason} | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "mute",
        user=target.mention,
        moderator=interaction.user.mention,
        duration=human_duration(seconds),
        reason=reason
    )


async def ctx_unmute_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "unmute"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    target = message.author

    if not await ensure_target_allowed(interaction, target):
        return

    await target.timeout(None, reason=f"Unmute through context menu | Moderator: {interaction.user}")

    await send_configured_response(
        interaction,
        "unmute",
        user=target.mention,
        moderator=interaction.user.mention
    )


async def ctx_warn_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "warn"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    target = message.author
    reason = "Warn через контекстное меню сообщения"

    warnings = get_user_warnings(interaction.guild.id, target.id)

    warnings.append({
        "reason": reason,
        "moderator_id": interaction.user.id,
        "moderator_name": str(interaction.user),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_id": message.id,
        "channel_id": message.channel.id
    })

    save_data(data)

    await send_configured_response(
        interaction,
        "warn",
        user=target.mention,
        moderator=interaction.user.mention,
        reason=reason,
        count=len(warnings)
    )


async def ctx_clear_message(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "clear"):
        return

    await message.delete()

    await send_configured_response(
        interaction,
        "clear",
        moderator=interaction.user.mention
    )


async def ctx_purge_author(
    interaction: discord.Interaction,
    message: discord.Message
):
    if not await check_admin_or_reply(interaction, "purge"):
        return

    if not isinstance(message.author, discord.Member):
        await interaction.response.send_message(
            "Автор сообщения не является участником сервера.",
            ephemeral=True
        )
        return

    target = message.author
    channel = message.channel

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Эта команда работает только в текстовом канале.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    deleted = await channel.purge(
        limit=1000,
        check=lambda msg: msg.author.id == target.id,
        reason=f"Purge through context menu by {interaction.user}"
    )

    await send_configured_response(
        interaction,
        "purge",
        user=target.mention,
        moderator=interaction.user.mention,
        count=len(deleted)
    )


bot.tree.add_command(app_commands.ContextMenu(
    name="Ban author",
    callback=ctx_ban_author
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Kick author",
    callback=ctx_kick_author
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Mute author 1h",
    callback=ctx_mute_author
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Unmute author",
    callback=ctx_unmute_author
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Warn author",
    callback=ctx_warn_author
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Clear message",
    callback=ctx_clear_message
))

bot.tree.add_command(app_commands.ContextMenu(
    name="Purge author messages",
    callback=ctx_purge_author
))



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
