import discord
from discord.ext import commands
import asyncio
import random
import os
import json

# --- Load Config ---
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config.get("token")
COMMAND_PREFIX = config.get("prefix", "!")
GUILD_ID = config.get("guild_id")
TICKET_CHANNEL_ID = config.get("ticket_channel_id")
STAFF_ROLE_ID = config.get("staff_role_id")
ROLE_CHANNEL_ID = config.get("role_channel_id")
TARGET_CHANNEL_ID = config.get("target_channel_id")
ALLOWED_LINK_CHANNELS = set(config.get("allowed_link_channels", []))
EMOJI_TO_ROLE = config.get("emoji_to_role", {})

# --- Intents and Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# --- Globals ---
open_tickets = {}  # user_id : channel_id
ticket_message_id = None
role_message_id = None

# --- Helper Functions to Save/Load IDs ---
def save_message_id(filename, message_id):
    with open(filename, "w") as f:
        json.dump({"message_id": message_id}, f)

def load_message_id(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r") as f:
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
            "Żeby zamknąć zgłoszenie, napisz `!close`."
        )

async def setup_ticket_message():
    global ticket_message_id
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    if not channel:
        print("❌ Ticket channel not found!")
        return

    ticket_message_id = load_message_id("ticket_message.json")

    # Try fetch existing message by saved ID
    if ticket_message_id:
        try:
            msg = await channel.fetch_message(ticket_message_id)
            print(f"✅ Ticket message found by ID: {msg.id}")
            return  # message exists, done
        except discord.NotFound:
            print("⚠️ Stored ticket message not found, searching recent history.")
            ticket_message_id = None

    # Search recent history for existing ticket message
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and "Kliknij przycisk, aby utworzyć zgłoszenie." in msg.content:
            ticket_message_id = msg.id
            save_message_id("ticket_message.json", ticket_message_id)
            print(f"✅ Found existing ticket message in channel history: {ticket_message_id}")
            return

    # If no message found, send new one
    view = TicketButton()
    msg = await channel.send("Kliknij przycisk, aby utworzyć zgłoszenie.", view=view)
    ticket_message_id = msg.id
    save_message_id("ticket_message.json", ticket_message_id)
    print(f"✅ New ticket message sent: {ticket_message_id}")

@bot.command()
async def close(ctx):
    channel_id = ctx.channel.id
    if channel_id not in open_tickets.values():
        await ctx.send("Ta komenda może zostać użyta tylko w zgłoszeniu.")
        return

    # Find owner of ticket
    owner_id = next((uid for uid, cid in open_tickets.items() if cid == channel_id), None)
    if owner_id is None:
        await ctx.send("Błąd: nie znaleziono właściciela zgłoszenia.")
        return

    is_staff = any(role.id == STAFF_ROLE_ID for role in ctx.author.roles)
    if ctx.author.id != owner_id and not is_staff:
        await ctx.send("Nie masz uprawnień, aby zamykać zgłoszenia.")
        return

    open_tickets.pop(owner_id)
    await ctx.send("Zamykam zgłoszenie...")
    await ctx.channel.delete(reason=f"Zgłoszenie zamknięte przez {ctx.author}")

# --- Self-Assign Roles ---

async def setup_role_message():
    global role_message_id
    channel = bot.get_channel(ROLE_CHANNEL_ID)
    if not channel:
        print("❌ Role channel not found!")
        return

    role_message_id = load_message_id("role_message.json")

    # Try fetch existing message by saved ID
    if role_message_id:
        try:
            msg = await channel.fetch_message(role_message_id)
            print(f"✅ Role message found: {msg.id}")
            return
        except discord.NotFound:
            print("⚠️ Previous role message not found. Sending a new one.")

    # Send new role message
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
            await member.kick(reason="Weryfikacja nieudana: timeout")
            return

        try:
            user_answer = int(msg.content.strip())
        except ValueError:
            await dm_channel.send("Niepoprawna odpowiedź. Spróbuj dołączyć ponownie.")
            await member.kick(reason="Weryfikacja nieudana: zła odpowiedź")
            return

        if user_answer == correct_answer:
            await dm_channel.send("Weryfikacja zakończona sukcesem. Witamy na serwerze!")
        else:
            await dm_channel.send("Niepoprawna odpowiedź. Spróbuj dołączyć ponownie.")
            await member.kick(reason="Weryfikacja nieudana: zła odpowiedź")

    except Exception as e:
        print(f"Error verifying member {member}: {e}")

# --- Auto Reactions & Link Filter ---

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Add reactions to messages in target channel or category
    is_target = False
    if message.channel.id == TARGET_CHANNEL_ID:
        is_target = True
    elif hasattr(message.channel, "category") and message.channel.category:
        if message.channel.category.id == TARGET_CHANNEL_ID:
            is_target = True

    if is_target:
        try:
            await message.clear_reactions()
            await message.add_reaction("👍")
            await message.add_reaction("👎")
        except Exception as e:
            print(f"Reaction error: {e}")

    # Link filtering
    if message.channel.id not in ALLOWED_LINK_CHANNELS:
        if "http://" in message.content or "https://" in message.content:
            try:
                await message.delete()
                await message.author.send(
                    f"⚠️ Twoja wiadomość z linkiem została usunięta z {message.channel.mention}."
                )
            except Exception:
                pass

    await bot.process_commands(message)

@bot.command()
async def reactions(ctx):
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return

    messages = await ctx.channel.history(limit=50).flatten()
    total_up = 0
    total_down = 0

    for msg in messages:
        for reaction in msg.reactions:
            if reaction.emoji == "👍":
                total_up += reaction.count
            elif reaction.emoji == "👎":
                total_down += reaction.count

    await ctx.send(f"👍: {total_up}, 👎: {total_down}")

# --- Ban Command ---

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, user: discord.User, duration: str = None, *, reason: str = "No reason provided"):
    ban_duration = None
    if duration and duration.lower() != "permanent":
        try:
            unit = duration[-1]
            time_amount = int(duration[:-1])
            if unit == "d":
                ban_duration = time_amount * 86400
            elif unit == "h":
                ban_duration = time_amount * 3600
            else:
                await ctx.send("Niepoprawny format czasu. Użyj '7d', '12h' lub 'permanent'.")
                return
        except Exception:
            await ctx.send("Niepoprawny czas.")
            return

    await ctx.guild.ban(user, reason=reason)
    await ctx.send(f"Zbanowano {user.mention} {'na stałe' if not ban_duration else f'na {duration}'}.")

    if ban_duration:
        await asyncio.sleep(ban_duration)
        await ctx.guild.unban(user)
        await ctx.send(f"{user.mention} został odbanowany po {duration}.")

# --- On Ready ---

@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako {bot.user}!")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ Nie znaleziono serwera!")
        return

    # Setup ticket message
    await setup_ticket_message()

    # Setup self assign role message
    await setup_role_message()

    print("✅ Bot jest gotowy.")

# --- Run Bot ---

if not TOKEN or TOKEN == "TOKEN_HERE":
    print("❌ Token nie został ustawiony w config.json.")
else:
    bot.run(TOKEN)
