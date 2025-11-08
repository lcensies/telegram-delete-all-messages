import os
import json
import argparse
import sys
from datetime import datetime

from time import sleep

from pyrogram import Client
from pyrogram.raw.functions.messages import Search
from pyrogram.raw.types import InputPeerSelf, InputMessagesFilterEmpty
from pyrogram.raw.types.messages import ChannelMessages
from pyrogram.errors import FloodWait, UnknownError, ChatAdminRequired

# Try to import readline for better terminal input handling (arrow keys, etc.)
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

def safe_input(prompt=''):
    """Read input safely, handling paste events (Ctrl+Shift+V) properly.
    
    This function reads from stdin line by line, allowing proper pasting
    without immediate execution. It supports arrow key navigation for editing.
    Strips trailing newlines and whitespace.
    """
    try:
        if READLINE_AVAILABLE:
            # Use readline for better terminal input handling (arrow keys, etc.)
            line = input(prompt)
        else:
            # Fallback to basic input if readline is not available
            sys.stdout.write(prompt)
            sys.stdout.flush()
            line = sys.stdin.readline()
            line = line.rstrip('\n\r')
        
        # Strip trailing whitespace
        return line.strip()
    except (EOFError, KeyboardInterrupt):
        # Handle Ctrl+C or EOF gracefully
        print('\nExiting...')
        sys.exit(0)

cachePath = os.path.abspath(__file__)
cachePath = os.path.dirname(cachePath)
cachePath = os.path.join(cachePath, "cache")

if os.path.exists(cachePath):
    with open(cachePath, "r") as cacheFile:
        cache = json.loads(cacheFile.read())
    
    API_ID = cache["API_ID"]
    API_HASH = cache["API_HASH"]
else:
    API_ID = os.getenv('API_ID', None) or int(safe_input('Enter your Telegram API id: '))
    API_HASH = os.getenv('API_HASH', None) or safe_input('Enter your Telegram API hash: ')

app = Client("client", api_id=API_ID, api_hash=API_HASH)

if not os.path.exists(cachePath):
    with open(cachePath, "w") as cacheFile:
        cache = {"API_ID": API_ID, "API_HASH": API_HASH}
        cacheFile.write(json.dumps(cache))


class Cleaner:
    def __init__(self, chats=None, search_chunk_size=100, delete_chunk_size=100):
        self.chats = chats or []
        if search_chunk_size > 100:
            # https://github.com/gurland/telegram-delete-all-messages/issues/31
            #
            # The issue is that pyrogram.raw.functions.messages.Search uses
            # pagination with chunks of 100 messages. Might consider switching
            # to search_messages, which handles pagination transparently.
            raise ValueError('search_chunk_size > 100 not supported')
        self.search_chunk_size = search_chunk_size
        self.delete_chunk_size = delete_chunk_size

    @staticmethod
    def chunks(l, n):
        """Yield successive n-sized chunks from l.
        https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks#answer-312464"""
        for i in range(0, len(l), n):
            yield l[i:i + n]

    @staticmethod
    async def get_all_chats():        
        async with app:
            dialogs = []
            async for dialog in app.get_dialogs():
                dialogs.append(dialog.chat)
            return dialogs

    async def select_groups(self, recursive=0):
        chats = await self.get_all_chats()
        groups = [c for c in chats if c.type.name in ('GROUP, SUPERGROUP')]

        print('Delete all your messages in')
        for i, group in enumerate(groups):
            print(f'  {i+1}. {group.title}')

        print(
            f'  {len(groups) + 1}. '
            '(!) DELETE ALL YOUR MESSAGES IN ALL OF THOSE GROUPS (!)\n'
        )

        nums_str = safe_input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), filter(lambda s: s.strip(), nums_str.split(',')))

        for n in nums:
            if not 1 <= n <= len(groups) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            if n == len(groups) + 1:
                print('\nTHIS WILL DELETE ALL YOUR MESSSAGES IN ALL GROUPS!')
                answer = safe_input('Please type "I understand" to proceed: ')
                if answer.upper() != 'I UNDERSTAND':
                    print('Better safe than sorry. Aborting...')
                    exit(-1)
                self.chats = groups
                break
            else:
                self.chats.append(groups[n - 1])
        
        groups_str = ', '.join(c.title for c in self.chats)
        print(f'\nSelected {groups_str}.\n')

        if recursive == 1:
            self.run()

    async def run(self):
        for chat in self.chats:
            chat_id = chat.id
            message_ids = []
            add_offset = 0

            while True:
                q = await self.search_messages(chat_id, add_offset)
                message_ids.extend(msg.id for msg in q)
                messages_count = len(q)
                print(f'Found {len(message_ids)} of your messages in "{chat.title}"')
                if messages_count < self.search_chunk_size:
                    break
                add_offset += self.search_chunk_size

            await self.delete_messages(chat_id=chat.id, message_ids=message_ids)

    async def delete_messages(self, chat_id, message_ids):
        print(f'Deleting {len(message_ids)} messages with message IDs:')
        print(message_ids)
        for chunk in self.chunks(message_ids, self.delete_chunk_size):
            try:
                async with app:
                    await app.delete_messages(chat_id=chat_id, message_ids=chunk)
            except FloodWait as flood_exception:
                sleep(flood_exception.x)

    async def search_messages(self, chat_id, add_offset):
        async with app:
            messages = []
            print(f'Searching messages. OFFSET: {add_offset}')
            async for message in app.search_messages(chat_id=chat_id, offset=add_offset, from_user="me", limit=100):
                messages.append(message)
            return messages

    async def archive_groups(self, archive_file="archived_groups.txt"):
        """Archive groups: list, select, leave, and save links to file"""
        chats = await self.get_all_chats()
        # Get both groups and channels (supergroups)
        groups = [c for c in chats if c.type.name in ('GROUP', 'SUPERGROUP', 'CHANNEL')]
        
        if not groups:
            print('No groups or channels found.')
            return

        print('\nArchive groups (leave and save links)')
        print('=' * 50)
        for i, group in enumerate(groups):
            group_type = group.type.name
            print(f'  {i+1}. [{group_type}] {group.title}')
        
        print(
            f'\n  {len(groups) + 1}. '
            '(!) ARCHIVE ALL GROUPS AND CHANNELS (!)\n'
        )

        nums_str = safe_input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), filter(lambda s: s.strip(), nums_str.split(',')))
        selected_groups = []

        for n in nums:
            if not 1 <= n <= len(groups) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            if n == len(groups) + 1:
                print('\nTHIS WILL LEAVE ALL GROUPS AND CHANNELS!')
                answer = safe_input('Please type "I understand" to proceed: ')
                if answer.upper() != 'I UNDERSTAND':
                    print('Better safe than sorry. Aborting...')
                    exit(-1)
                selected_groups = groups
                break
            else:
                selected_groups.append(groups[n - 1])
        
        if not selected_groups:
            print('No groups selected. Exiting...')
            return

        groups_str = ', '.join(c.title for c in selected_groups)
        print(f'\nSelected {len(selected_groups)} group(s): {groups_str}\n')

        # Collect links and leave groups
        archived_links = []
        
        async with app:
            for group in selected_groups:
                try:
                    # Try to get invite link or username
                    link = None
                    
                    # If group has username, use it
                    if group.username:
                        link = f"https://t.me/{group.username}"
                    else:
                        # Try to export invite link
                        try:
                            invite_link = await app.export_chat_invite_link(group.id)
                            link = invite_link
                        except (ChatAdminRequired, Exception):
                            # Can't export link, try to get it from chat info
                            try:
                                chat_info = await app.get_chat(group.id)
                                if hasattr(chat_info, 'invite_link') and chat_info.invite_link:
                                    link = chat_info.invite_link
                            except:
                                pass
                        
                        # If still no link, note that it's a private group/channel
                        if not link:
                            link = f"[Private {group.type.name.lower()} - ID: {group.id}]"
                    
                    archived_links.append({
                        'title': group.title,
                        'type': group.type.name,
                        'link': link,
                        'archived_at': datetime.now().isoformat()
                    })
                    
                    print(f'Archiving: {group.title} ({group.type.name})')
                    print(f'  Link: {link}')
                    
                    # Leave the group/channel
                    try:
                        await app.leave_chat(group.id)
                        print(f'  ✓ Left successfully\n')
                    except Exception as e:
                        print(f'  ✗ Error leaving: {e}\n')
                        
                except Exception as e:
                    print(f'Error processing {group.title}: {e}\n')
                    # Still save what we can
                    archived_links.append({
                        'title': group.title,
                        'type': group.type.name,
                        'link': 'N/A',
                        'archived_at': datetime.now().isoformat(),
                        'error': str(e)
                    })

        # Save links to file
        archive_path = os.path.join(os.path.dirname(cachePath), archive_file)
        with open(archive_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{'=' * 50}\n")
            f.write(f"Archived on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'=' * 50}\n\n")
            
            for item in archived_links:
                f.write(f"{item['title']} [{item['type']}]\n")
                f.write(f"Link: {item['link']}\n")
                if 'error' in item:
                    f.write(f"Note: {item['error']}\n")
                f.write("\n")
        
        valid_links = [l for l in archived_links if l["link"] != "N/A" and l["link"].startswith("http")]
        print(f'\n✓ Archived {len(archived_links)} group(s) to {archive_path}')
        print(f'  Valid links saved: {len(valid_links)}')
        print(f'  Private groups (no link available): {len(archived_links) - len(valid_links)}')

async def main():
    parser = argparse.ArgumentParser(description='Telegram message cleaner and group archiver')
    parser.add_argument('--archive-groups', action='store_true',
                        help='Archive groups: list, select, leave, and save links to file')
    parser.add_argument('--archive-file', default='archived_groups.txt',
                        help='File to save archived group links (default: archived_groups.txt)')
    
    args = parser.parse_args()
    
    try:
        deleter = Cleaner()
        
        if args.archive_groups:
            await deleter.archive_groups(args.archive_file)
        else:
            await deleter.select_groups()
            await deleter.run()
    except UnknownError as e:
        print(f'UnknownError occured: {e}')
        print('Probably API has changed, ask developers to update this utility')

app.run(main())