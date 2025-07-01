# filar-bot
unofficial FILAR moderation discord bot

This Discord bot includes several features:

    Ticket System

        Provides a persistent button labeled "Create Ticket".

        When a user clicks the button, it creates a private text channel (ticket) visible only to the user, staff members, and the bot.

        Prevents users from opening multiple tickets simultaneously.

        Allows ticket owners or staff to close the ticket with the !close command, which deletes the ticket channel.

    Anti-Raid Verification

        When a new member joins, the bot sends a direct message with a simple math question.

        The user must answer correctly within 2 minutes to avoid being kicked from the server.

        This helps prevent bot raids by verifying human users.

    Self-Assign Roles

        Posts a message with emojis that users can react to in order to assign or remove roles themselves.

        Automatically manages role assignment/removal based on reactions to the specific message.

    Reaction Tracker

        Automatically adds thumbs up (👍) and thumbs down (👎) reactions to messages in a specified channel.

        Provides a !reactions command to summarize the total number of 👍 and 👎 reactions on recent messages in that channel.

    Link Filtering

        Deletes messages containing links (http:// or https://) in channels where links are not allowed.

        Notifies users via DM that their message was removed for containing a link.

        Allows exceptions for specified channels where links are permitted.

    Temporary and Permanent Ban Command

        Provides a !ban command that allows staff with ban permissions to ban users.

        Supports temporary bans with durations specified in days (d) or hours (h).

        Automatically unbans the user after the ban duration expires.
