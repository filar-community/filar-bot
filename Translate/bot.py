import discord
from discord.ext import commands
import asyncio
import random
import os
import json
from datetime import datetime, timedelta

# --- Load Config ---
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config.get("token")
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
intents.presences = True  # To check member activity status

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Globals for stats ---
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

# --- Helper Functions ---
def save_message_id(filename, message_id):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump({"message_id": message_id}, f)

def load_message_id(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("message_id")
    except json.JSONDecodeError:
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
        print("❌ Ticket channel not found!")
        return

    ticket_message_id = load_message_id("ticket_message.json")

    if ticket_message_id:
        try:
            msg = await channel.fetch_message(ticket_message_id)
            print(f"✅ Ticket message found by ID: {msg.id}")
            return
        except discord.NotFound:
            print("⚠️ Stored ticket message not found, searching recent history.")
            ticket_message_id = None

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and "Kliknij przycisk, aby utworzyć zgłoszenie." in msg.content:
            ticket_message_id = msg.id
            save_message_id("ticket_message.json", ticket_message_id)
            print(f"✅ Found existing ticket message in channel history: {ticket_message_id}")
            return

    view = TicketButton()
    msg = await channel.send("Kliknij przycisk, aby utworzyć zgłoszenie.", view=view)
    ticket_message_id = msg.id
    save_message_id("ticket_message.json", ticket_message_id)
    print(f"✅ New ticket message sent: {ticket_message_id}")

# --- Self-Assign Roles ---
async def setup_role_message():
    global role_message_id
    channel = bot.get_channel(ROLE_CHANNEL_ID)
    if not channel:
        print("❌ Role channel not found!")
        return

    role_message_id = load_message_id("role_message.json")

    if role_message_id:
        try:
            msg = await channel.fetch_message(role_message_id)
            print(f"✅ Role message found: {msg.id}")
            return
        except discord.NotFound:
            print("⚠️ Previous role message not found. Sending a new one.")

    description = "Zareaguj, żeby uzyskać rolę:\n"
    for emoji, role_id in EMOJI_TO_ROLE.items():
        role = channel.guild.get_role(role_id)
        if role:
            description += f"{emoji} : {role.name}\n"

    embed = discord.Embed(title="Autorole", description=description)
    msg = await channel.send(embed=embed)
    for emoji in EMOJI_TO_ROLE.keys():
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            print(f"Failed to add reaction {emoji}: {e}")

    role_message_id = msg.id
    save_message_id("role_message.json", role_message_id)
    print(f"✅ New role message sent: {role_message_id}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != role_message_id:
        return
    if payload.user_id == bot.user.id:
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
            print(f"Added role {role.name} to {member}")
        except Exception as e:
            print(f"Failed to add role: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id != role_message_id:
        return
    if payload.user_id == bot.user.id:
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
            print(f"Removed role {role.name} from {member}")
        except Exception as e:
            print(f"Failed to remove role: {e}")

# --- Anti-Raid Math Challenge ---
def generate_math_question():
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    op = random.choice(['+', '-'])
    question = f"What is {a} {op} {b}?"
    answer = a + b if op == '+' else a - b
    return question, answer

@bot.event
async def on_member_join(member):
    stats["users_joined"] += 1
    try:
        question, correct_answer = generate_math_question()
        dm_channel = await member.create_dm()
        await dm_channel.send(
            f"Witaj na {member.guild.name}! Proszę rozwiąż zadanie matematyczne, żebyśmy wiedzieli, że jesteś człowiekiem.\n"
            f"Napisz sam wynik:\n{question}"
        )

        def check(m):
            return m.author == member and m.channel == dm_channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=120)
        except asyncio.TimeoutError:
            await dm_channel.send("Nie odpowiedziałeś na czas. Spróbuj dołączyć ponownie i rozwiązać zadanie.")
            stats["failed_verification"] += 1
            failed_verifications.add(member.id)
            await member.kick(reason="Weryfikacja nieudana: timeout")
            return

        try:
            user_answer = int(msg.content.strip())
        except ValueError:
            await dm_channel.send("Niepoprawna odpowiedź. Spróbuj dołączyć ponownie.")
            stats["failed_verification"] += 1
            failed_verifications.add(member.id)
            await member.kick(reason="Weryfikacja nieudana: zła odpowiedź")
            return

        if user_answer == correct_answer:
            await dm_channel.send("Weryfikacja zakończona sukcesem. Witamy na serwerze!")
            stats["passed_verification"] += 1
            verified_members.add(member.id)
        else:
            await dm_channel.send("Niepoprawna odpowiedź. Spróbuj dołączyć ponownie.")
            stats["failed_verification"] += 1
            failed_verifications.add(member.id)
            await member.kick(reason="Weryfikacja nieudana: zła odpowiedź")

    except Exception as e:
        print(f"Error verifying member {member}: {e}")

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

    last_message_times[message.author.id] = datetime.utcnow()

    # Check if message is in target channel or its category
    is_target = False
    if message.channel.id == TARGET_CHANNEL_ID:
        is_target = True
    elif getattr(message.channel, "category", None) and message.channel.category.id == TARGET_CHANNEL_ID:
        is_target = True

    # Check for discord.gg or discord.com/invite links
    lowered = message.content.lower()
    if ("discord.gg/" in lowered or "discord.com/invite/" in lowered) and message.channel.id not in ALLOWED_LINK_CHANNELS:
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention}, linki zaproszeń nie są dozwolone tutaj.",
                delete_after=10
            )
        except Exception as e:
            print(f"Failed to delete invite link: {e}")
        return

    await bot.process_commands(message)

# --- Commands ---
@bot.command(name="close")
async def close_ticket(ctx):
    user_id = ctx.author.id
    if user_id not in open_tickets:
        await ctx.send("Nie masz otwartego zgłoszenia.", delete_after=10)
        return

    ticket_channel_id = open_tickets[user_id]
    ticket_channel = bot.get_channel(ticket_channel_id)
    if ticket_channel:
        try:
            await ticket_channel.delete(reason=f"Zgłoszenie zamknięte przez {ctx.author}")
            del open_tickets[user_id]
            await ctx.send("Twoje zgłoszenie zostało zamknięte.", delete_after=10)
        except Exception as e:
            await ctx.send(f"Nie udało się zamknąć zgłoszenia: {e}", delete_after=10)
    else:
        del open_tickets[user_id]
        await ctx.send(
            "Nie znaleziono kanału zgłoszenia, ale twoje zgłoszenie zostało usunięte z listy.",
            delete_after=10
        )

@bot.command(name="reactions")
@commands.has_permissions(manage_messages=True)
async def reactions(ctx):
    channel = ctx.channel
    counter = 0
    async for msg in channel.history(limit=100):
        counter += sum(reaction.count for reaction in msg.reactions)

    await ctx.send(f"W tym kanale jest {counter} reakcji na ostatnich 100 wiadomościach.")

@bot.command(name="stats")
async def stats_cmd(ctx):
    guild = ctx.guild
    if not guild:
        await ctx.send("Ta komenda działa tylko na serwerze.")
        return

    threshold = datetime.utcnow() - timedelta(days=30)
    inactive_count = 0
    for member in guild.members:
        if member.bot:
            continue
        last_msg = last_message_times.get(member.id)
        if not last_msg or last_msg < threshold:
            inactive_count += 1
    stats["inactive_users"] = inactive_count

    embed = discord.Embed(title="Statystyki serwera", color=discord.Color.blue())
    embed.add_field(name="Przeszło weryfikację", value=stats["passed_verification"], inline=True)
    embed.add_field(name="Nie przeszło weryfikacji", value=stats["failed_verification"], inline=True)
    embed.add_field(name="Dołączyło użytkowników", value=stats["users_joined"], inline=True)
    embed.add_field(name="Opuściło użytkowników", value=stats["users_left"], inline=True)
    embed.add_field(name="Zbanowanych użytkowników", value=stats["banned_users"], inline=True)
    embed.add_field(name="Nieaktywnych użytkowników (30 dni)", value=stats["inactive_users"], inline=True)

    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! Opóźnienie: {latency_ms} ms")

# --- NEW CLEAN COMMAND ---
@bot.command(name="clean")
@commands.has_permissions(manage_messages=True)
async def clean(ctx, amount: int, time_range: int):
    if amount <= 0:
        await ctx.send("❌ Proszę podać liczbę większą niż 0 dla ilości wiadomości do usunięcia.", delete_after=10)
        return
    if time_range <= 0:
        await ctx.send("❌ Proszę podać liczbę większą niż 0 dla zakresu czasu w godzinach.", delete_after=10)
        return

    time_limit = datetime.utcnow() - timedelta(hours=time_range)
    deleted = 0
    try:
        # We fetch up to 1000 messages to filter manually by time.
        messages = []
        async for msg in ctx.channel.history(limit=1000, oldest_first=False):
            if msg.created_at > time_limit:
                messages.append(msg)
                if len(messages) >= amount:
                    break

        if not messages:
            await ctx.send("❌ Nie znaleziono wiadomości do usunięcia w podanym zakresie czasu.", delete_after=10)
            return

        def is_deletable(m):
            return (datetime.utcnow() - m.created_at).total_seconds() < 1209600  # 14 days in seconds

        deletable_msgs = [m for m in messages if is_deletable(m)]
        if not deletable_msgs:
            await ctx.send("❌ Brak wiadomości do usunięcia (starsze niż 14 dni).", delete_after=10)
            return

        await ctx.channel.delete_messages(deletable_msgs)
        deleted = len(deletable_msgs)
        await ctx.send(f"✅ Usunięto {deleted} wiadomości z ostatnich {time_range} godzin.", delete_after=10)
    except Exception as e:
        await ctx.send(f"❌ Wystąpił błąd podczas usuwania wiadomości: {e}", delete_after=10)

# --- UNBAN SLASH COMMAND ---
@bot.tree.command(name="unban", description="Odbanuj użytkownika z serwera")
@discord.app_commands.describe(user="Użytkownik do odbanowania (w formacie Nazwa#1234)")
async def unban(interaction: discord.Interaction, user: str):
    if not interaction.guild:
        await interaction.response.send_message("Ta komenda działa tylko na serwerze.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("Nie masz uprawnień do odbanowywania użytkowników.", ephemeral=True)
        return

    try:
        banned_users = await interaction.guild.bans()
        user_name, user_discriminator = user.split("#")

        banned_entry = None
        for ban_entry in banned_users:
            if (ban_entry.user.name == user_name and ban_entry.user.discriminator == user_discriminator):
                banned_entry = ban_entry
                break

        if not banned_entry:
            await interaction.response.send_message(f"Użytkownik {user} nie jest zbanowany.", ephemeral=True)
            return

        await interaction.guild.unban(banned_entry.user, reason=f"Odbanowane przez {interaction.user}")
        await interaction.response.send_message(f"Użytkownik {user} został odbanowany pomyślnie.")
    except Exception as e:
        await interaction.response.send_message(f"Wystąpił błąd: {e}", ephemeral=True)

# --- On Ready ---
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"❌ Błąd synchronizacji slash commands: {e}")

    await setup_ticket_message()
    await setup_role_message()

# --- Run bot ---
bot.run(TOKEN)
