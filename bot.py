import discord
from discord.ext import commands
import asyncio
import random
import os
import json

# --- Bot Intents ---
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content
intents.guilds = True           # Required for guild-related events
intents.members = True          # Required to track member join and roles

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Replace with your actual IDs ---
GUILD_ID = 123456789012345678          # Your server ID
TICKET_CHANNEL_ID = 000000000000000000   # Channel where the "Create Ticket" button is posted
STAFF_ROLE_ID = 000000000000000000     # Role ID for staff who can view tickets
ROLE_CHANNEL_ID = 000000000000000000    # Channel where self-assign role message is sent
TARGET_CHANNEL_ID = 000000000000000000  # Channel for thumbs up/down reactions

# --- Global variables ---
open_tickets = {}        # Tracks user_id -> ticket channel_id
role_message_id = None   # Stores ID of the message for self-assign roles
allowed_link_channels = set()  # Channels where links are allowed

# --- ---------------------- TICKET SYSTEM ---------------------- ---

class TicketButton(discord.ui.View):
    """View containing a single button to create tickets."""
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.green, custom_id="create_ticket_button")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        guild = interaction.guild

        # Check if user already has a ticket open
        if user_id in open_tickets:
            await interaction.response.send_message("You already have an open ticket!", ephemeral=True)
            return

        # Setup permission overwrites for the ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(STAFF_ROLE_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        # Create the private ticket channel
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            topic=f"Ticket for {interaction.user} (ID: {interaction.user.id})",
            reason="New support ticket created"
        )

        open_tickets[user_id] = ticket_channel.id

        # Inform the user privately that their ticket was created
        await interaction.response.send_message(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)
        await ticket_channel.send(f"Hello {interaction.user.mention}! A staff member will be with you shortly.\nTo close this ticket, type `!close`.")

@bot.command()
async def close(ctx):
    """
    Command to close a ticket:
    - Only ticket owner or staff can close.
    - Deletes the ticket channel and removes it from tracking.
    """
    user_id = ctx.author.id
    channel = ctx.channel

    if channel.id not in open_tickets.values():
        await ctx.send("This command can only be used inside a ticket channel.")
        return

    # Find owner of the ticket channel
    owner_id = next((uid for uid, cid in open_tickets.items() if cid == channel.id), None)
    if owner_id is None:
        await ctx.send("Error: ticket owner not found.")
        return

    is_staff = any(role.id == STAFF_ROLE_ID for role in ctx.author.roles)
    if ctx.author.id != owner_id and not is_staff:
        await ctx.send("You don't have permission to close this ticket.")
        return

    open_tickets.pop(owner_id)
    await ctx.send("Closing ticket...")
    await channel.delete(reason=f"Ticket closed by {ctx.author}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

    # Setup ticket button message in the ticket channel
    guild = bot.get_guild(GUILD_ID)
    channel = guild.get_channel(TICKET_CHANNEL_ID)
    if channel is None:
        print("Ticket channel not found!")
        return

    # Try to find previous message with the ticket button and edit it; else send new message
    async for message in channel.history(limit=100):
        if message.author == bot.user and message.content == "Click the button below to create a ticket!":
            await message.edit(view=TicketButton())
            break
    else:
        await channel.send("Click the button below to create a ticket!", view=TicketButton())

    # Setup self-assign roles message
    await setup_self_assign_roles()

    # Print ready message
    print("Bot is ready.")

# --- ------------------ ANTI-RAID MATH CHALLENGE ------------------ ---

def generate_math_question():
    """Generate a simple math question and its answer."""
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    op = random.choice(['+', '-'])
    question = f"What is {a} {op} {b}?"
    answer = a + b if op == '+' else a - b
    return question, answer

@bot.event
async def on_member_join(member):
    """Send math challenge to new member and kick if they fail to answer correctly in time."""
    try:
        question, correct_answer = generate_math_question()
        dm_channel = await member.create_dm()
        await dm_channel.send(
            f"Welcome to {member.guild.name}! To verify you're not a bot, please answer this question within 2 minutes:\n{question}"
        )

        def check(m):
            return m.author == member and m.channel == dm_channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=120)
        except asyncio.TimeoutError:
            await dm_channel.send("You did not answer in time. You will be kicked.")
            await member.kick(reason="Failed verification: no response")
            return

        try:
            user_answer = int(msg.content.strip())
        except ValueError:
            await dm_channel.send("Invalid answer format. You will be kicked.")
            await member.kick(reason="Failed verification: invalid answer")
            return

        if user_answer == correct_answer:
            await dm_channel.send("Thank you! You have been verified and allowed to stay.")
        else:
            await dm_channel.send("Incorrect answer. You will be kicked.")
            await member.kick(reason="Failed verification: wrong answer")

    except Exception as e:
        print(f"Error during verification for {member}: {e}")

# --- -------------------- SELF-ASSIGN ROLES -------------------- ---

# Map emoji to role IDs (replace with your server's actual role IDs and emojis)
EMOJI_TO_ROLE = {
    "🔥": 111111111111111111,  # Example role 1
    "💧": 222222222222222222,  # Example role 2
    "🌿": 333333333333333333,  # Example role 3
}

async def setup_self_assign_roles():
    """Send or update the self-assign role message with reaction roles."""
    global role_message_id
    channel = bot.get_channel(ROLE_CHANNEL_ID)
    if channel is None:
        print("Role channel not found!")
        return

    description = "React to assign yourself a role:\n"
    for emoji, role_id in EMOJI_TO_ROLE.items():
        role = channel.guild.get_role(role_id)
        if role:
            description += f"{emoji} : {role.name}\n"

    embed = discord.Embed(title="Self-Assign Roles", description=description)
    
    # Send a new message with embed and reactions if role_message_id is None
    if role_message_id is None:
        msg = await channel.send(embed=embed)
        for emoji in EMOJI_TO_ROLE.keys():
            await msg.add_reaction(emoji)
        role_message_id = msg.id
        print(f"Role message sent with ID: {role_message_id}")

@bot.event
async def on_raw_reaction_add(payload):
    """Add role when user reacts to the self-assign message."""
    if payload.message_id != role_message_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    role_id = EMOJI_TO_ROLE.get(str(payload.emoji))
    if role_id is None:
        return

    role = guild.get_role(role_id)
    if role is None:
        return

    try:
        await member.add_roles(role)
        print(f"Added {role.name} to {member.display_name}")
    except Exception as e:
        print(f"Failed to add role: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    """Remove role when user removes their reaction."""
    if payload.message_id != role_message_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    role_id = EMOJI_TO_ROLE.get(str(payload.emoji))
    if role_id is None:
        return

    role = guild.get_role(role_id)
    if role is None:
        return

    try:
        await member.remove_roles(role)
        print(f"Removed {role.name} from {member.display_name}")
    except Exception as e:
        print(f"Failed to remove role: {e}")

# --- -------------------- THUMBS UP/DOWN REACTIONS -------------------- ---

@bot.event
async def on_message(message):
    """Add 👍 and 👎 reactions automatically in the target channel and handle link filtering."""
    if message.author.bot:
        return

    # Add thumbs reactions in the specified channel
    if message.channel.id == TARGET_CHANNEL_ID:
        try:
            await message.add_reaction("👍")
            await message.add_reaction("👎")
        except Exception as e:
            print(f"Failed to add reactions: {e}")

    # --- LINK FILTERING ---
    # Ignore links in allowed channels
    if message.channel.id not in allowed_link_channels:
        if "http://" in message.content or "https://" in message.content:
            try:
                await message.delete()
            except discord.Forbidden:
                print("Missing permissions to delete message.")
            except discord.NotFound:
                pass

            try:
                await message.author.send(
                    f"⚠️ Your message containing a link was removed in {message.guild.name} "
                    f"because links are not allowed in {message.channel.mention}."
                )
            except discord.Forbidden:
                print(f"Couldn't DM user {message.author}.")

    await bot.process_commands(message)

@bot.command(name="reactions")
async def reactions(ctx):
    """Summarizes total 👍 and 👎 reactions in the target channel for recent messages."""
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return

    messages = await ctx.channel.history(limit=50).flatten()

    total_thumbs_up = 0
    total_thumbs_down = 0

    for msg in messages:
        for reaction in msg.reactions:
            if reaction.emoji == "👍":
                total_thumbs_up += reaction.count
            elif reaction.emoji == "👎":
                total_thumbs_down += reaction.count

    await ctx.send(f"Total 👍 reactions: {total_thumbs_up}\nTotal 👎 reactions: {total_thumbs_down}")

# --- -------------------- BAN COMMAND -------------------- ---

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, user: discord.User, duration: str = None, *, reason: str = "No reason provided"):
    """
    Ban a user with optional duration and reason.
    If duration is omitted or "permanent", ban is permanent.
    Duration examples: "7d" (7 days), "12h" (12 hours).
    """
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
                await ctx.send("Invalid duration format. Use number + 'd' or 'h', or 'permanent'.")
                return
        except Exception:
            await ctx.send("Invalid duration format. Use number + 'd' or 'h', or 'permanent'.")
            return

    await ctx.guild.ban(user, reason=reason)
    await ctx.send(f"Banned {user} permanently." if ban_duration is None else f"Banned {user} for {duration}.")

    # Unban after duration if temporary ban
    if ban_duration:
        await asyncio.sleep(ban_duration)
        await ctx.guild.unban(user)
        try:
            await ctx.send(f"{user} has been unbanned after {duration}.")
        except Exception:
            pass

# --- -------------------- RUN BOT -------------------- ---

# Load your token from environment variable or replace here
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    print("Error: DISCORD_BOT_TOKEN environment variable not set.")
else:
    bot.run(TOKEN)
