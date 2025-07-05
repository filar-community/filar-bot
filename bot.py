import discord
from discord.ext import commands
import asyncio
import random
import os
import json
from datetime import datetime, timedelta, timezone
from filarbot import config

# --- Load Config ---
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

GUILD_ID = config.get("guild_id")
TICKET_CHANNEL_ID = config.get("ticket_channel_id")
STAFF_ROLE_ID = config.get("staff_role_id")
ROLE_CHANNEL_ID = config.get("role_channel_id")
TARGET_CHANNEL_ID = config.get("target_channel_id")
ALLOWED_LINK_CHANNELS = set(config.get("allowed_link_channels", []))
EMOJI_TO_ROLE = config.get("emoji_to_role", {})

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True
intents.bans = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Globals ---
stats = {
    "passed_verification": 0,
    "failed_verification": 0,
    "users_joined": 0,
    "users_left": 0,
    "banned_users": 0,
    "inactive_users": 0,
}

verified_members = set()
failed_verifications = set()
last_message_times = {}
open_tickets = {}
ticket_message_id = None
role_message_id = None

# --- Helpers ---
def save_message_id(filename, message_id):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({"message_id": message_id}, f)
    except Exception as e:
        print(f"❌ Błąd zapisu pliku {filename}: {e}")

def load_message_id(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("message_id")
    except Exception as e:
        print(f"❌ Błąd odczytu pliku {filename}: {e}")
        return None

# --- Ticket System ---
class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Utwórz zgłoszenie", style=discord.ButtonStyle.green, custom_id="create_ticket_button")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        guild = interaction.guild

        if user_id in open_tickets:
            await interaction.response.send_message("Już masz otwarte zgłoszenie.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(STAFF_ROLE_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            topic=f"Zgłoszenie dla {interaction.user} (ID: {interaction.user.id})",
            reason="Nowe zgłoszenie zostało utworzone."
        )

        open_tickets[user_id] = ticket_channel.id

        await interaction.response.send_message(
            f"Twoje zgłoszenie zostało utworzone: {ticket_channel.mention}", ephemeral=True
        )
        await ticket_channel.send(
            f"Cześć {interaction.user.mention}! Niedługo powinna pojawić się moderacja.\n"
            "Żeby zamknąć zgłoszenie, użyj komendy !close."
        )

async def setup_ticket_message():
    global ticket_message_id
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    if not channel:
        print("❌ Nie znaleziono kanału do ticketów!")
        return

    ticket_message_id = load_message_id("ticket_message.json")

    if ticket_message_id:
        try:
            await channel.fetch_message(ticket_message_id)
            print(f"✅ Znaleziono wiadomość ticketu: {ticket_message_id}")
            return
        except discord.NotFound:
            print("⚠️ Wiadomość ticketu nie znaleziona, tworzę nową.")
            ticket_message_id = None

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and "Kliknij przycisk, aby utworzyć zgłoszenie." in msg.content:
            ticket_message_id = msg.id
            save_message_id("ticket_message.json", ticket_message_id)
            print(f"✅ Znaleziona istniejąca wiadomość ticketu: {ticket_message_id}")
            return

    view = TicketButton()
    msg = await channel.send("Kliknij przycisk, aby utworzyć zgłoszenie.", view=view)
    ticket_message_id = msg.id
    save_message_id("ticket_message.json", ticket_message_id)
    print(f"✅ Wysłano nową wiadomość ticketu: {ticket_message_id}")

# --- Role Message ---
async def setup_role_message():
    global role_message_id
    channel = bot.get_channel(ROLE_CHANNEL_ID)
    if not channel:
        print("❌ Nie znaleziono kanału z rolami!")
        return

    role_message_id = load_message_id("role_message.json")

    if role_message_id:
        try:
            await channel.fetch_message(role_message_id)
            print(f"✅ Znaleziono wiadomość z rolami: {role_message_id}")
            return
        except discord.NotFound:
            print("⚠️ Stara wiadomość nie znaleziona. Wysyłam nową.")

    description = "Zareaguj, żeby uzyskać rolę:\n"
    for emoji, role_id in EMOJI_TO_ROLE.items():
        role = channel.guild.get_role(role_id)
        if role:
            description += f"{emoji} : {role.name}\n"

    embed = discord.Embed(title="Autorole", description=description, color=discord.Color.green())
    msg = await channel.send(embed=embed)
    for emoji in EMOJI_TO_ROLE.keys():
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            print(f"❌ Nie udało się dodać reakcji {emoji}: {e}")

    role_message_id = msg.id
    save_message_id("role_message.json", role_message_id)
    print(f"✅ Wysłano nową wiadomość z rolami: {role_message_id}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != role_message_id or payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    emoji_str = str(payload.emoji)
    role_id = EMOJI_TO_ROLE.get(emoji_str)
    if not role_id:
        return

    role = guild.get_role(role_id)
    if role:
        try:
            await member.add_roles(role)
            print(f"Dodano rolę {role.name} użytkownikowi {member}")
        except Exception as e:
            print(f"❌ Nie udało się dodać roli: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id != role_message_id or payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    emoji_str = str(payload.emoji)
    role_id = EMOJI_TO_ROLE.get(emoji_str)
    if not role_id:
        return

    role = guild.get_role(role_id)
    if role:
        try:
            await member.remove_roles(role)
            print(f"Usunięto rolę {role.name} od użytkownika {member}")
        except Exception as e:
            print(f"❌ Nie udało się usunąć roli: {e}")

# --- Anti-Raid Math Verification ---
def generate_math_question():
    a, b = random.randint(1, 20), random.randint(1, 20)
    op = random.choice(['+', '-'])
    question = f"Ile to jest {a} {op} {b}?"
    answer = a + b if op == '+' else a - b
    return question, answer

@bot.event
async def on_member_join(member):
    stats["users_joined"] += 1
    try:
        question, correct_answer = generate_math_question()
        dm_channel = await member.create_dm()
        await dm_channel.send(
            f"Witaj na {member.guild.name}! Proszę rozwiąż zadanie matematyczne:\n{question}"
        )

        def check(m):
            return m.author == member and m.channel == dm_channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=120)
        except asyncio.TimeoutError:
            await dm_channel.send("Czas minął. Spróbuj ponownie.")
            stats["failed_verification"] += 1
            failed_verifications.add(member.id)
            await member.kick(reason="Verification timeout")
            return

        try:
            if int(msg.content.strip()) == correct_answer:
                await dm_channel.send("Weryfikacja zakończona sukcesem!")
                stats["passed_verification"] += 1
                verified_members.add(member.id)
            else:
                raise ValueError("Wrong answer")
        except Exception:
            await dm_channel.send("Niepoprawna odpowiedź.")
            stats["failed_verification"] += 1
            failed_verifications.add(member.id)
            await member.kick(reason="Wrong answer")

    except Exception as e:
        print(f"❌ Weryfikacja error: {e}")

@bot.event
async def on_member_remove(member):
    stats["users_left"] += 1
    verified_members.discard(member.id)
    failed_verifications.discard(member.id)
    last_message_times.pop(member.id, None)
    open_tickets.pop(member.id, None)

@bot.event
async def on_member_ban(guild, user):
    stats["banned_users"] += 1

@bot.event
async def on_member_unban(guild, user):
    if stats["banned_users"] > 0:
        stats["banned_users"] -= 1

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    last_message_times[message.author.id] = datetime.now(timezone.utc)

    if ("discord.gg/" in message.content.lower() or "discord.com/invite/" in message.content.lower()) and message.channel.id not in ALLOWED_LINK_CHANNELS:
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention}, linki zaproszeń są niedozwolone tutaj.",
                delete_after=10
            )
        except Exception as e:
            print(f"❌ Nie udało się usunąć linku: {e}")
        return

    await bot.process_commands(message)

# --- Commands ---
@bot.command(name="close")
async def close_ticket(ctx):
    user_id = ctx.author.id
    ticket_channel_id = open_tickets.get(user_id)

    if not ticket_channel_id:
        await ctx.send("Nie masz otwartego zgłoszenia.", delete_after=10)
        return

    channel = bot.get_channel(ticket_channel_id)
    if channel:
        await channel.delete(reason=f"Zamknięcie przez {ctx.author}")
    open_tickets.pop(user_id, None)
    await ctx.send("Zgłoszenie zamknięte.", delete_after=10)

@bot.command(name="reactions")
@commands.has_permissions(manage_messages=True)
async def reactions(ctx):
    counter = 0
    try:
        async for msg in ctx.channel.history(limit=100):
            counter += sum(reaction.count for reaction in msg.reactions)
        await ctx.send(f"Liczba reakcji w 100 wiadomościach: {counter}")
    except Exception as e:
        await ctx.send(f"❌ Błąd: {e}")

@bot.command(name="stats")
async def stats_cmd(ctx):
    threshold = datetime.now(timezone.utc) - timedelta(days=30)
    inactive = sum(1 for m in ctx.guild.members if not m.bot and (last_message_times.get(m.id) or threshold) < threshold)
    stats["inactive_users"] = inactive

    embed = discord.Embed(title="Statystyki", color=discord.Color.blue())
    for key, value in stats.items():
        embed.add_field(name=key.replace('_', ' ').title(), value=value, inline=True)
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send(f"Pong! Opóźnienie: {round(bot.latency * 1000)} ms")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount <= 0:
        await ctx.send("Podaj liczbę większą niż 0.", delete_after=5)
        return
    try:
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"Usunięto {len(deleted)} wiadomości.", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Błąd: {e}")

@bot.command(name="clearuser")
@commands.has_permissions(manage_messages=True)
async def clearuser(ctx, member: discord.Member, amount: int = 100):
    deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == member)
    await ctx.send(f"Usunięto {len(deleted)} wiadomości użytkownika {member.display_name}.", delete_after=5)

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"Zbanowano {member} za: {reason}")
    except Exception as e:
        await ctx.send(f"❌ Nie udało się zbanować: {e}")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        user = discord.Object(id=user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"Odbanowano użytkownika o ID {user_id}.")
    except Exception as e:
        await ctx.send(f"❌ Nie udało się odbanować: {e}")

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"Wyrzucono {member} za: {reason}")
    except Exception as e:
        await ctx.send(f"❌ Nie udało się wyrzucić: {e}")

# --- Bot Ready ---
@bot.event
async def on_ready():
    print(f"✅ Bot gotowy! Zalogowano jako {bot.user} (ID: {bot.user.id})")
    await setup_ticket_message()
    await setup_role_message()
    bot.add_view(TicketButton())
# --- Start Bot ---
if config.bot_token():
    bot.run(config.bot_token())
else:
    print("❌ Brak tokenu")
