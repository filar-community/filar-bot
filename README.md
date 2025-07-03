# filar-bot

**Unofficial FILAR moderation Discord bot**

---

This Discord bot includes several features:

## Ticket System

- Provides a persistent button labeled **"Utwórz zgłoszenie"**.  
- When a user clicks the button, it creates a **private text channel** (ticket) visible only to:  
  - the user,  
  - staff members (role),  
  - and the bot.  
- Prevents users from opening multiple tickets simultaneously.  
- Ticket owners can close their ticket with the `!close` command, which deletes the ticket channel.

## Anti-Raid Verification

- On member join, the bot sends a **DM with a simple math question**.  
- The user must answer correctly within **2 minutes** or they get kicked.  
- Helps protect the server from automated bot raids.

## Self-Assign Roles

- Posts a message with **emojis linked to specific roles**.  
- Users can react or remove reaction to assign or remove those roles automatically.

## Reaction Tracker

- The `!reactions` command counts and shows the total number of reactions on the last 100 messages in the current channel.

## Link Filtering

- Automatically deletes messages containing Discord invite links (`discord.gg/`, `discord.com/invite/`) outside of allowed channels.  
- Sends a warning message in the channel mentioning the user.

## Moderation Commands

- `!ban` — bans a member with an optional reason.  
- `!unban` — unbans a user by their ID.  
- `!kick` — kicks a member with an optional reason.  
- `!clear` — bulk deletes a specified number of messages in a channel.
- `!cleanuser` - User-specific message clearing command.

## Server Stats

- `!stats` command shows statistics including:  
  - Verified users,  
  - Failed verifications,  
  - Joined and left users,  
  - Banned users,  
  - Inactive users (no message in last 30 days).

## Ping Command

- `!ping` — shows bot latency in milliseconds.

---

## Upcoming Features

- Soon

---

## Info

Most of the code was generated or assisted by AI due to time constraints.
