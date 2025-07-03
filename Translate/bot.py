import discord
from discord.ext import commands
import asyncio
import random
import os
import json

# --- Load Config ---
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
COMMAND_PREFIX = config.get("prefix", "!")
GUILD_ID = config["guild_id"]
TICKET_CHANNEL_ID = config["ticket_channel_id"]
STAFF_ROLE_ID = config["staff_role_id"]
ROLE_CHANNEL_ID = config["role_channel_id"]
TARGET_CHANNEL_ID = config["target_channel_id"]
ALLOWED_LINK_CHANNELS = set(config["allowed_link_channels"])
EMOJI_TO_ROLE = config["emoji_to_role"]

# --- Intents and Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# --- Globals ---
open_tickets = {}
role_message_id = None

# --- Ticket System ---

role_message_id = None  # global to store the message ID

async def setup_ticket_message():
    global role_message_id
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    if channel is None:
        print("❌ Ticket channel not found!")
        return

    # Load existing message ID from file
    if os.path.exists("role_message.json"):
        with open("role_message.json", "r") as f:
            try:
                data = json.load(f)
                role_message_id = data.get("message_id")
            except json.JSONDecodeError:
                role_message_id = None

    # Try to fetch the existing message by saved ID
    if role_message_id:
        try:
            msg = await channel.fetch_message(role_message_id)
            print(f"✅ Ticket message found by ID: {msg.id}")
            return  # Message exists, do nothing more
        except discord.NotFound:
            print("⚠️ Stored ticket message not found, will try to find in history.")
            role_message_id = None  # Reset to send new message

    # If no saved message or fetch failed, try to find a similar message in recent history
    async for message in channel.history(limit=50):
        if message.author == bot.user and "Kliknij przycisk, aby utworzyć zgłoszenie." in message.content:
            role_message_id = message.id
            print(f"✅ Found existing ticket message in channel history: {role_message_id}")
            return  # Found existing message, stop here

    # If no existing message found, send a new one with button
    view = TicketButton()
    msg = await channel.send("Kliknij przycisk, aby utworzyć zgłoszenie.", view=view)

    role_message_id = msg.id

    # Save the message ID to file for next restarts
    with open("role_message.json", "w") as f:
        json.dump({"message_id": role_message_id}, f)

    print(f"✅ New ticket message sent: {role_message_id}")


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


@bot.command()
async def close(ctx):
    user_id = ctx.author.id
    channel = ctx.channel

    if channel.id not in open_tickets.values():
        await ctx.send("Ta komenda może zostać użyta tylko w zgłoszeniu.")
        return

    owner_id = next((uid for uid, cid in open_tickets.items() if cid == channel.id), None)
    if owner_id is None:
        await ctx.send("Błąd: nie znaleziono właściciela zgłoszenia.")
        return

    is_staff = any(role.id == STAFF_ROLE_ID for role in ctx.author.roles)
    if ctx.author.id != owner_id and not is_staff:
        await ctx.send("Nie masz uprawnień, aby zamykać zgłoszenia.")
        return

    open_tickets.pop(owner_id)
    await ctx.send("Zamykam zgłoszenie...")
    await channel.delete(reason=f"Zgłoszenie zamknięte przez {ctx.author}")

# --- On Ready ---

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}!")

    guild = bot.get_guild(GUILD_ID)
    ticket_channel = guild.get_channel(TICKET_CHANNEL_ID)
    if ticket_channel:
        async for msg in ticket_channel.history(limit=100):
            if msg.author == bot.user and msg.content.startswith("Click the button"):
                await msg.edit(view=TicketButton())
                break
        else:
            await ticket_channel.send("Naciśnij poniżej, aby skontaktować się z moderacją.", view=TicketButton())
    else:
        print("❌ Ticket channel not found!")

    await setup_self_assign_roles()
    print("✅ Bot is ready.")

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
            f"Welcome to {member.guild.name}! Proszę rozwiąż zadanie matematyczne, żebyśmy wiedzieli, że jesteś człowiekiem. Aby to zrobić, napisz sam wynik po zadaniu pytania:\n{question}"
        )

        def check(m):
            return m.author == member and m.channel == dm_channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=120)
        except asyncio.TimeoutError:
            await dm_channel.send("Nie odpowiedziałeś w czasie, proszę dołącz jeszcze raz do serwera i spróbuj ponownie.")
            await member.kick(reason="Weryfikacja nieudana, powód: czas.")
            return

        try:
            user_answer = int(msg.content.strip())
        except ValueError:
            await dm_channel.send("Zła odpowiedź, weryfikacja nieudana. Proszę dołącz jeszcze raz do serwera i spróbuj ponownie.")
            await member.kick(reason="Weryfikacja nieudana, powód: zła odpowiedź.")
            return

        if user_answer == correct_answer:
            await dm_channel.send("Zweryfikowano pomyślnie.")
        else:
            await dm_channel.send("Weryfikacja nieudana. Proszę dołącz jeszcze raz do serwera i spróbuj ponownie.")
            await member.kick(reason="Weryfikacja nieudana, powód: zła odpowiedź.")

    except Exception as e:
        print(f"Error verifying member {member}: {e}")

# --- Self Assign Roles (Fixed) ---

async def setup_self_assign_roles():
    global role_message_id
    channel = bot.get_channel(ROLE_CHANNEL_ID)
    if channel is None:
        print("❌ Role channel not found!")
        return

    # Load the message ID if it exists
    if os.path.exists("role_message.json"):
        with open("role_message.json", "r") as f:
            try:
                data = json.load(f)
                role_message_id = data.get("message_id")
            except json.JSONDecodeError:
                role_message_id = None

    # Try to fetch the existing message
    if role_message_id:
        try:
            msg = await channel.fetch_message(role_message_id)
            print(f"✅ Role message found: {msg.id}")
            return  # Reuse existing message
        except discord.NotFound:
            print("⚠️ Previous role message not found. Sending a new one.")

    # Create a new message
    description = "Zareaguj, żeby uzyskać rolę:\n"
    for emoji, role_id in EMOJI_TO_ROLE.items():
        role = channel.guild.get_role(role_id)
        if role:
            description += f"{emoji} : {role.name}\n"

    embed = discord.Embed(title="Autorole", description=description)
    msg = await channel.send(embed=embed)
    
    for emoji in EMOJI_TO_ROLE.keys():
        await msg.add_reaction(emoji)

    role_message_id = msg.id

    # Save the message ID
    with open("role_message.json", "w") as f:
        json.dump({"message_id": role_message_id}, f)

    print(f"✅ New role message sent: {role_message_id}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != role_message_id:
        return
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member and not member.bot:
        role_id = EMOJI_TO_ROLE.get(str(payload.emoji))
        if role_id:
            role = guild.get_role(role_id)
            if role:
                await member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id != role_message_id:
        return
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member and not member.bot:
        role_id = EMOJI_TO_ROLE.get(str(payload.emoji))
        if role_id:
            role = guild.get_role(role_id)
            if role:
                await member.remove_roles(role)

# --- Auto Reactions & Link Filter ---

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    is_target = (
        message.channel.id == TARGET_CHANNEL_ID or
        (hasattr(message.channel, "parent_id") and message.channel.parent_id == TARGET_CHANNEL_ID)
    )

    if is_target:
        try:
            await message.clear_reactions()
            await message.add_reaction("👍")
            await message.add_reaction("👎")
        except Exception as e:
            print(f"Reaction error: {e}")

    # Link Filtering
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

@bot.command(name="reactions")
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
# To do: Unban command
@bot.command(name="ban")
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
                await ctx.send("Invalid format. Use '7d', '12h', or 'permanent'.")
                return
        except Exception:
            await ctx.send("Invalid duration.")
            return

    await ctx.guild.ban(user, reason=reason)
    await ctx.send(f"Banned {user.mention} {'permanently' if not ban_duration else f'for {duration}'}.")

    if ban_duration:
        await asyncio.sleep(ban_duration)
        await ctx.guild.unban(user)
        await ctx.send(f"{user.mention} has been unbanned after {duration}.")

# --- Run Bot ---

if not TOKEN or TOKEN == "TOKEN_HERE":
    print("❌ Token not set in config.json.")
else:
    bot.run(TOKEN)
