class ChannelManager:
    """
    Manages channel-related operations, such as listing available channels.
    """

    def __init__(self, app):
        """
        Initialize the ChannelManager.

        Args:
            app (Client): Pyrogram client instance.
        """
        self.app = app

    async def list_channels(self):
        """
        List available channels or groups accessible by the client.

        Returns:
            list[dict]: A list of dictionaries containing channel information.
        """
        print("Fetching available channels...")
        channels = []

        try:
            async for dialog in self.app.get_dialogs():
                if dialog.chat.type in ["channel", "supergroup"]:
                    channel_info = {
                        "title": dialog.chat.title,
                        "id": dialog.chat.id,
                        "type": dialog.chat.type,
                    }
                    channels.append(channel_info)
                    print(f"{dialog.chat.title} ({dialog.chat.id})")
        except Exception as e:
            print(f"Error listing channels: {e}")

        return channels
