from telethon import events
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import PeerUser, InputPeerUser, PeerChannel, PeerChat, Channel, Chat
from .. import loader, utils
import time

@loader.tds
class AutoAddMod(loader.Module):
    strings = {'name': 'AutoAdd', 'developer': '@SheoMod'}
    
    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.me = await client.get_me()
        self.target_chat = self.db.get("AutoAdd", "target_chat", None)
        self.enabled = self.db.get("AutoAdd", "enabled", False)
        self.added_users = []
    
    @loader.command()
    async def addchat(self, message):
        """<ссылка или ID> - Установить чат для добавления пользователей"""
        args = utils.get_args_raw(message)
        if not args:
            return await message.edit("Укажите ссылку или ID чата")
        
        try:
            chat = await self.client.get_entity(args.strip())
            self.db.set("AutoAdd", "target_chat", chat.id)
            self.target_chat = chat.id
            await message.edit(f"Чат установлен: {chat.title or chat.username or chat.id}")
        except Exception as e:
            await message.edit(f"Ошибка: {str(e)}")
    
    @loader.command()
    async def add(self, message):
        """Включить/выключить авто-добавление пользователей в чат"""
        if not self.target_chat:
            return await message.edit("Сначала установите чат командой .addchat")
        
        self.enabled = not self.enabled
        self.db.set("AutoAdd", "enabled", self.enabled)
        
        status = "включено" if self.enabled else "выключено"
        await message.edit(f"Авто-добавление {status}")
    
    def _check_rate_limit(self):
        """Проверяет лимит добавлений (10 в минуту)"""
        current_time = time.time()
        self.added_users = [t for t in self.added_users if current_time - t < 60]
        
        if len(self.added_users) >= 10:
            return False
        
        self.added_users.append(current_time)
        return True
    
    async def _is_user_in_chat(self, chat, user_id):
        """Проверяет, есть ли пользователь в чате"""
        try:
            participants = await self.client.get_participants(chat)
            for participant in participants:
                if participant.id == user_id:
                    return True
            return False
        except Exception:
            return False
    
    @loader.watcher(only_messages=True)
    async def watcher(self, message):
        try:
            
            if not message.is_private:
                return
            
            if message.out:
                return
            
            if not self.enabled:
                return
            
            if not self.target_chat:
                return
            
            if message.sender_id == self.me.id:
                return
            
            # 
                sender = await self.client.get_entity(message.sender_id)
                if sender.bot:
                    return
            except Exception:
                return
            
            
            if not self._check_rate_limit():
                return
            
            try:
                user = await self.client.get_entity(message.sender_id)
                chat = await self.client.get_entity(self.target_chat)
                
                
                if await self._is_user_in_chat(chat, user.id):
                    return
                
                if isinstance(chat, Channel):
                    await self.client(InviteToChannelRequest(
                        channel=chat,
                        users=[user]
                    ))
                elif isinstance(chat, Chat):
                    await self.client(AddChatUserRequest(
                        chat_id=chat.id,
                        user_id=user,
                        fwd_limit=0
                    ))
                else:
                    return
                
            except Exception:
                pass
                
        except Exception:
            pass
