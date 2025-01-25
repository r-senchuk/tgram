from pyrogram.enums import ChatType

def list_channels(app):
    """
    List available channels the client can access.

    Args:
        app (Client): An instance of the Pyrogram Client.
    """
    print("Fetching available channels...")

    with app:
        dialogs = app.get_dialogs()
        channels = [
            dialog.chat for dialog in dialogs
            if dialog.chat.type in {ChatType.CHANNEL, ChatType.SUPERGROUP}
        ]

        if not channels:
            print("No accessible channels found.")
            return

        print("Available channels:")
        for idx, channel in enumerate(channels, start=1):
            print(f"{idx}. {channel.title} ({channel.id})")