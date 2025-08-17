from abc import ABC, abstractmethod
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class Fetcher(ABC):
    """
    Abstract base class for fetching messages from Telegram.
    Provides methods to fetch new, old, and missed messages, and list available channels.
    """

    @abstractmethod
    async def fetch_new(self):
        """Fetch the newest messages."""
        pass

    @abstractmethod
    async def fetch_old(self):
        """Fetch the oldest messages."""
        pass

    @abstractmethod
    async def fetch_scan(self):
        """Fetch missed messages (gaps)."""
        pass

    @abstractmethod
    async def list_channels(self):
        """List available channels accessible by the client."""
        pass


class TelegramFetcher(Fetcher):
    """
    Implementation of the Fetcher abstraction for Telegram using Pyrogram.
    """

    def __init__(self, app, storage, chat_id, batch_size):
        self.app = app  # Pyrogram client instance
        self.storage = storage  # KeyValueStorage instance
        self.chat_id = chat_id  # Target chat/channel ID
        self.batch_size = batch_size  # Number of messages per batch
        logger.info(f"TelegramFetcher initialized with chat_id: {chat_id}, batch_size: {batch_size}")

    async def fetch_new(self):
        """Fetch the newest messages and store them."""
        logger.info(f"Starting to fetch newest messages for chat {self.chat_id}...")
        print(f"Starting to fetch newest messages for chat {self.chat_id}...")
        
        fetch_kwargs = {"chat_id": self.chat_id, "limit": self.batch_size}
        logger.info(f"Fetch kwargs: {fetch_kwargs}")

        try:
            messages_fetched = 0
            async for message in self._fetch_messages(fetch_kwargs):
                logger.info(f"Processing message {message.id}")
                
                if self.storage.is_message_processed(message.id):
                    logger.info(f"Skipping already processed message {message.id}")
                    print(f"Skipping already processed message {message.id}.")
                    continue

                # Process the message before saving
                message_data = self._process_message(message)
                text_preview = message_data.get('text', '') or 'No text'
                logger.info(f"Saving message {message.id}: {text_preview[:50]}...")
                
                self.storage.save_message(message.id, message_data)
                messages_fetched += 1
                
                if messages_fetched % 10 == 0:  # Log progress every 10 messages
                    logger.info(f"Fetched {messages_fetched} messages so far...")
                    print(f"Fetched {messages_fetched} messages so far...")

            logger.info(f"Fetch new completed. Total messages fetched: {messages_fetched}")
            print(f"Fetch new completed. Total messages fetched: {messages_fetched}")

        except Exception as e:
            logger.error(f"Error fetching newest messages: {e}", exc_info=True)
            print(f"Error fetching newest messages: {e}")

    async def fetch_old(self):
        """Fetch the oldest messages and store them."""
        print(f"Starting to fetch oldest messages for chat {self.chat_id}...")
        # ``load_all_messages`` returns a mapping where the keys are message IDs.
        # When backed by ``FileKeyValueStorage`` the keys are stored as strings.
        # Using them directly with ``min`` yields lexicographical comparison
        # (e.g. '100' < '99'), producing an incorrect offset and even raising a
        # ``TypeError`` when arithmetic is performed.  Convert keys to integers
        # before computing the smallest ID.
        all_messages = self.storage.load_all_messages().keys()
        last_stored_message = min(
            map(int, self.storage.load_all_messages().keys()), default=None
        )
        fetch_kwargs = {"chat_id": self.chat_id, "limit": self.batch_size}

        if last_stored_message is not None:
            fetch_kwargs["offset_id"] = last_stored_message - 1

        while True:
            messages_fetched = 0

            try:
                async for message in self._fetch_messages(fetch_kwargs):
                    if self.storage.is_message_processed(message.id):
                        continue

                    message_data = self._process_message(message)
                    self.storage.save_message(message.id, message_data)
                    messages_fetched += 1

            except Exception as e:
                print(f"Error fetching oldest messages: {e}")
                break

            if messages_fetched == 0:
                print("No more old messages. Stopping fetch.")
                break

            print(f"Fetched {messages_fetched} messages. Continuing...")

    async def fetch_scan(self):
        print("Scanning for missing messages...")
        # Mock: Generate a list of missing message ranges
        missing_ranges = [(100, 120), (250, 270)]
        print("Missing message ranges:", missing_ranges)
        return missing_ranges

    async def fetch_missed(self):
        """Fetch messages for gaps detected in storage."""
        print("Fetching missed messages...")
        gaps = self.storage.find_gaps()
        for start_id, end_id in gaps:
            fetch_kwargs = {
                "chat_id": self.chat_id,
                "limit": self.batch_size,
                "offset_id": end_id + 1,
            }
            async for message in self._fetch_messages(fetch_kwargs):
                if message.id < start_id:
                    break
                if not self.storage.is_message_processed(message.id):
                    message_data = self._process_message(message)
                    self.storage.save_message(message.id, message_data)
    
    async def fetch_gap(self, start_id, end_id):
        print(f"Fetching messages from {start_id} to {end_id}...")
        for message_id in range(start_id, end_id + 1):
            print(f"Fetched message {message_id}")
        print("Gap fetch completed.")

    async def fetch_by_native_topic(self, native_topic_id):
        """Fetch messages for a specific native topic."""
        logger.info(f"Fetching messages for native topic {native_topic_id} in chat {self.chat_id}...")
        print(f"Fetching messages for native topic {native_topic_id}...")
        
        try:
            # Get topic summary first
            summary = self.storage.get_native_topic_summary(self.chat_id, native_topic_id)
            
            if not summary:
                print(f"❌ Native topic {native_topic_id} not found")
                return
            
            print(f"📌 Native Topic {native_topic_id}")
            print(f"   Messages: {summary['message_count']}")
            print(f"   Participants: {summary['participant_count']}")
            print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
            print()
            
            # Get all messages for this topic
            messages = self.storage.get_messages_by_native_topic(self.chat_id, native_topic_id)
            
            if messages:
                print("Conversation Thread:")
                print("-" * 50)
                
                # Sort messages by ID to maintain conversation order
                sorted_messages = sorted(messages.items(), key=lambda x: int(x[0]))
                
                for msg_id, msg_data in sorted_messages:
                    username = msg_data.get('from_user', {}).get('username', 'Unknown')
                    text = msg_data.get('text', '') or 'No text'
                    date = msg_data.get('date', 'Unknown date')
                    
                    print(f"[{date}] @{username}: {text}")
                    print()
                
                print(f"End of conversation thread (Native Topic {native_topic_id})")
                
            else:
                print(f"No messages found for native topic {native_topic_id}")
                
        except Exception as e:
            logger.error(f"Error fetching native topic messages: {e}", exc_info=True)
            print(f"Error fetching native topic messages: {e}")

    async def list_channels(self):
        """List available channels the client can access."""
        logger.info("Starting channel listing...")
        print("Fetching available channels...")

        try:
            logger.info("Fetching dialogs from Pyrogram...")
            async for dialog in self.app.get_dialogs():
                logger.info(f"Dialog found: {dialog.chat.title} - Type: {dialog.chat.type} - ID: {dialog.chat.id}")
                if dialog.chat.type in ["channel", "supergroup"]:
                    logger.info(f"Channel/Group: {dialog.chat.title} ({dialog.chat.id})")
                    print(f"{dialog.chat.title} ({dialog.chat.id})")
            
            logger.info("Channel listing completed")
        except Exception as e:
            logger.error(f"Error listing channels: {e}", exc_info=True)
            print(f"Error listing channels: {e}")

    async def list_native_topics(self):
        """List available native Telegram topics based on reply_to_top_message_id."""
        logger.info(f"Listing native topics for chat {self.chat_id}...")
        print(f"Listing native topics for chat {self.chat_id}...")
        
        try:
            # Get native topic statistics
            stats = self.storage.get_native_topic_stats(self.chat_id)
            
            if stats:
                logger.info(f"Found {len(stats)} native topics")
                print(f"🎉 Found {len(stats)} native Telegram topics!")
                print()
                print("Native Topics (based on reply_to_top_message_id):")
                print("-" * 70)
                
                # Sort by message count (most active first)
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
                
                for topic_id, msg_count in sorted_stats:
                    # Get topic summary
                    summary = self.storage.get_native_topic_summary(self.chat_id, topic_id)
                    
                    if summary:
                        print(f"📌 Native Topic {topic_id}")
                        print(f"   Messages: {summary['message_count']}")
                        print(f"   Participants: {summary['participant_count']}")
                        print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
                        print(f"   Message Range: {summary['first_message_id']} - {summary['last_message_id']}")
                        
                        # Get first message text for context
                        first_msg = self.storage.get_messages_by_native_topic(self.chat_id, topic_id)
                        if first_msg:
                            first_msg_id = min(int(k) for k in first_msg.keys())
                            first_msg_data = first_msg[str(first_msg_id)]
                            text_preview = first_msg_data.get('text', '') or 'No text'
                            print(f"   Preview: {text_preview[:80]}...")
                        print()
                    else:
                        print(f"📌 Native Topic {topic_id}: {msg_count} messages")
                
                print(f"Total native topics: {len(stats)}")
                print(f"Total messages with native topics: {sum(stats.values())}")
                
            else:
                logger.info("No native topics found")
                print("❌ No native topics found")
                print("This chat doesn't support Telegram forum topics")
                print("💡 Use virtual topics instead (based on reply chains)")
                
        except Exception as e:
            logger.error(f"Error listing native topics: {e}", exc_info=True)
            print(f"Error listing native topics: {e}")

    async def list_virtual_topics(self):
        """List available virtual topics based on reply chains."""
        logger.info(f"Listing virtual topics for chat {self.chat_id}...")
        print(f"Listing virtual topics for chat {self.chat_id}...")
        
        try:
            # Get virtual topic statistics
            stats = self.storage.get_virtual_topic_stats(self.chat_id)
            
            if stats:
                logger.info(f"Found {len(stats)} virtual topics")
                print(f"🎉 Found {len(stats)} virtual topics based on reply chains!")
                print()
                print("Virtual Topics (organized by conversation threads):")
                print("-" * 70)
                
                # Sort by message count (most active first)
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
                
                for topic_id, msg_count in sorted_stats:
                    # Get topic summary
                    summary = self.storage.get_virtual_topic_summary(self.chat_id, topic_id)
                    
                    if summary:
                        print(f"📌 Virtual Topic {topic_id}")
                        print(f"   Messages: {summary['message_count']}")
                        print(f"   Participants: {summary['participant_count']}")
                        print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
                        print(f"   Message Range: {summary['first_message_id']} - {summary['last_message_id']}")
                        
                        # Get first message text for context
                        first_msg = self.storage.get_messages_by_virtual_topic(self.chat_id, topic_id)
                        if first_msg:
                            first_msg_id = min(int(k) for k in first_msg.keys())
                            first_msg_data = first_msg[str(first_msg_id)]
                            text_preview = first_msg_data.get('text', '') or 'No text'
                            print(f"   Preview: {text_preview[:80]}...")
                        print()
                    else:
                        print(f"📌 Virtual Topic {topic_id}: {msg_count} messages")
                
                print(f"Total virtual topics: {len(stats)}")
                print(f"Total messages with topics: {sum(stats.values())}")
                
            else:
                logger.info("No virtual topics found")
                print("❌ No virtual topics found")
                print("Run the reply threading implementation first to create virtual topics")
                
        except Exception as e:
            logger.error(f"Error listing virtual topics: {e}", exc_info=True)
            print(f"Error listing virtual topics: {e}")

    async def fetch_by_virtual_topic(self, virtual_topic_id):
        """Fetch messages for a specific virtual topic."""
        logger.info(f"Fetching messages for virtual topic {virtual_topic_id} in chat {self.chat_id}...")
        print(f"Fetching messages for virtual topic {virtual_topic_id}...")
        
        try:
            # Get topic summary first
            summary = self.storage.get_virtual_topic_summary(self.chat_id, virtual_topic_id)
            
            if not summary:
                print(f"❌ Virtual topic {virtual_topic_id} not found")
                return
            
            print(f"📌 Virtual Topic {virtual_topic_id}")
            print(f"   Messages: {summary['message_count']}")
            print(f"   Participants: {summary['participant_count']}")
            print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
            print()
            
            # Get all messages for this topic
            messages = self.storage.get_messages_by_virtual_topic(self.chat_id, virtual_topic_id)
            
            if messages:
                print("Conversation Thread:")
                print("-" * 50)
                
                # Sort messages by ID to maintain conversation order
                sorted_messages = sorted(messages.items(), key=lambda x: int(x[0]))
                
                for msg_id, msg_data in sorted_messages:
                    username = msg_data.get('from_user', {}).get('username', 'Unknown')
                    text = msg_data.get('text', '') or 'No text'
                    date = msg_data.get('date', 'Unknown date')
                    
                    print(f"[{date}] @{username}: {text}")
                    print()
                
                print(f"End of conversation thread (Virtual Topic {virtual_topic_id})")
                
            else:
                print(f"No messages found for virtual topic {virtual_topic_id}")
                
        except Exception as e:
            logger.error(f"Error fetching virtual topic messages: {e}", exc_info=True)
            print(f"Error fetching virtual topic messages: {e}")

    async def list_native_topics(self):
        """List available native Telegram topics based on reply_to_top_message_id."""
        logger.info(f"Listing native topics for chat {self.chat_id}...")
        print(f"Listing native topics for chat {self.chat_id}...")
        
        try:
            # Get native topic statistics
            stats = self.storage.get_native_topic_stats(self.chat_id)
            
            if stats:
                logger.info(f"Found {len(stats)} native topics")
                print(f"🎉 Found {len(stats)} native Telegram topics!")
                print()
                print("Native Topics (based on reply_to_top_message_id):")
                print("-" * 70)
                
                # Sort by message count (most active first)
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
                
                for topic_id, msg_count in sorted_stats:
                    # Get topic summary
                    summary = self.storage.get_native_topic_summary(self.chat_id, topic_id)
                    
                    if summary:
                        print(f"📌 Native Topic {topic_id}")
                        print(f"   Messages: {summary['message_count']}")
                        print(f"   Participants: {summary['participant_count']}")
                        print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
                        print(f"   Message Range: {summary['first_message_id']} - {summary['last_message_id']}")
                        
                        # Get first message text for context
                        first_msg = self.storage.get_messages_by_native_topic(self.chat_id, topic_id)
                        if first_msg:
                            first_msg_id = min(int(k) for k in first_msg.keys())
                            first_msg_data = first_msg[str(first_msg_id)]
                            text_preview = first_msg_data.get('text', '') or 'No text'
                            print(f"   Preview: {text_preview[:80]}...")
                        print()
                    else:
                        print(f"📌 Native Topic {topic_id}: {msg_count} messages")
                
                print(f"Total native topics: {len(stats)}")
                print(f"Total messages with native topics: {sum(stats.values())}")
                
            else:
                logger.info("No native topics found")
                print("❌ No native topics found")
                print("This chat doesn't support Telegram forum topics")
                
        except Exception as e:
            logger.error(f"Error listing native topics: {e}", exc_info=True)
            print(f"Error listing native topics: {e}")

    async def fetch_by_native_topic(self, native_topic_id):
        """Fetch messages for a specific native topic."""
        logger.info(f"Fetching messages for native topic {native_topic_id} in chat {self.chat_id}...")
        print(f"Fetching messages for native topic {native_topic_id}...")
        
        try:
            # Get topic summary first
            summary = self.storage.get_native_topic_summary(self.chat_id, native_topic_id)
            
            if not summary:
                print(f"❌ Native topic {native_topic_id} not found")
                return
            
            print(f"📌 Native Topic {native_topic_id}")
            print(f"   Messages: {summary['message_count']}")
            print(f"   Participants: {summary['participant_count']}")
            print(f"   Date Range: {summary['first_date']} to {summary['last_date']}")
            print()
            
            # Get all messages for this topic
            messages = self.storage.get_messages_by_native_topic(self.chat_id, native_topic_id)
            
            if messages:
                print("Conversation Thread:")
                print("-" * 50)
                
                # Sort messages by ID to maintain conversation order
                sorted_messages = sorted(messages.items(), key=lambda x: int(x[0]))
                
                for msg_id, msg_data in sorted_messages:
                    username = msg_data.get('from_user', {}).get('username', 'Unknown')
                    text = msg_data.get('text', '') or 'No text'
                    date = msg_data.get('date', 'Unknown date')
                    
                    print(f"[{date}] @{username}: {text}")
                    print()
                
                print(f"End of conversation thread (Native Topic {native_topic_id})")
                
            else:
                print(f"No messages found for native topic {native_topic_id}")
                
        except Exception as e:
            logger.error(f"Error fetching native topic messages: {e}", exc_info=True)
            print(f"Error fetching native topic messages: {e}")

    async def show_hybrid_topic_stats(self):
        """Show combined statistics for both native and virtual topics."""
        logger.info(f"Showing hybrid topic stats for chat {self.chat_id}...")
        print(f"Hybrid Topic Statistics for chat {self.chat_id}:")
        print("=" * 60)
        
        try:
            hybrid_stats = self.storage.get_hybrid_topic_stats(self.chat_id)
            
            if hybrid_stats:
                print("📊 Native Telegram Topics:")
                print(f"   Total topics: {hybrid_stats['total_native_topics']}")
                print(f"   Total messages: {hybrid_stats['messages_with_native_topics']}")
                
                if hybrid_stats['native_topics']:
                    print("   Top topics by message count:")
                    sorted_native = sorted(hybrid_stats['native_topics'].items(), key=lambda x: x[1], reverse=True)[:5]
                    for topic_id, count in sorted_native:
                        print(f"     Topic {topic_id}: {count} messages")
                
                print()
                print("🧠 Virtual Topics (Reply Chain Analysis):")
                print(f"   Total topics: {hybrid_stats['total_virtual_topics']}")
                print(f"   Total messages: {hybrid_stats['messages_with_virtual_topics']}")
                
                if hybrid_stats['virtual_topics']:
                    print("   Top topics by message count:")
                    sorted_virtual = sorted(hybrid_stats['virtual_topics'].items(), key=lambda x: x[1], reverse=True)[:5]
                    for topic_id, count in sorted_virtual:
                        print(f"     Topic {topic_id}: {count} messages")
                
                print()
                print("💡 Summary:")
                total_messages = hybrid_stats['messages_with_native_topics'] + hybrid_stats['messages_with_virtual_topics']
                print(f"   Total messages with topic organization: {total_messages}")
                
                if hybrid_stats['total_native_topics'] > 0:
                    print("   ✅ This chat supports native Telegram topics!")
                else:
                    print("   ❌ This chat doesn't support native topics (using virtual topics only)")
                    
            else:
                print("No topic statistics available")
                
        except Exception as e:
            logger.error(f"Error showing hybrid topic stats: {e}", exc_info=True)
            print(f"Error showing hybrid topic stats: {e}")

    def show_status(self):
        """Display basic information about stored messages."""
        all_messages = self.storage.load_all_messages()
        total = len(all_messages)
        if total == 0:
            print("No messages stored.")
            return

        ids = list(map(int, all_messages.keys()))
        first_id, last_id = min(ids), max(ids)
        print(f"Stored messages: {total}")
        print(f"ID range: {first_id} - {last_id}")

        gaps = self.storage.find_gaps()
        if gaps:
            print(f"Gaps detected: {gaps}")
        else:
            print("No gaps detected.")

    async def _fetch_messages(self, fetch_kwargs):
        """Helper to fetch messages for better testability."""
        history = self.app.get_chat_history(**fetch_kwargs)

        # ``get_chat_history`` can either return an async iterable directly or a
        # coroutine that resolves to one (as seen with ``AsyncMock`` in tests).
        # Handle both cases to make the helper robust.
        if not hasattr(history, "__aiter__"):
            history = await history

        async for message in history:
            yield message

    def _process_message(self, message):
        """Convert a message to a serializable dictionary."""
        return {
            "id": message.id,
            "chat_id": self.chat_id,  # Add the chat_id from the fetcher
            "reply_to_top_message_id": getattr(message, 'reply_to_top_message_id', None),  # Native Telegram topic ID
            "virtual_topic_id": None,  # Will be set by reply threading analysis
            "from_user": {
                "id": message.from_user.id if message.from_user else None,
                "username": message.from_user.username if message.from_user else None,
            },
            "date": message.date.strftime("%Y-%m-%dT%H:%M:%S") if message.date else None,
            "text": message.text,
            "media": str(message.media) if message.media else None,
            "reply_to_message_id": message.reply_to_message_id,
        }