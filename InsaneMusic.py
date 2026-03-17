from .. import loader, utils
import asyncio
import time
import re
from telethon.tl.custom import Button
from telethon.tl.types import Message


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.database = None
        self.search_lock = asyncio.Lock()
        self.spam_protection = {}
        self.temp_results = {}
        self.active_searches = {}  # Для отслеживания активных поисков
        super().__init__()

    async def client_ready(self, client, database):
        self.client = client
        self.database = database
        
        if not self.database.get("InsMusic", "allowed_chats"):
            self.database.set("InsMusic", "allowed_chats", [])
        
        if not self.database.get("InsMusic", "music_bots"):
            default_bots = ["ShillMusic_bot", "AudioBoxrobot", "Lybot", "vkm4_bot", "MusicDownloaderBot", "DeezerMusicBot", "SpotifyDownloaderBot", "shazambot"]
            self.database.set("InsMusic", "music_bots", default_bots)

    @property
    def allowed_chats(self):
        return self.database.get("InsMusic", "allowed_chats", [])

    @allowed_chats.setter
    def allowed_chats(self, value):
        self.database.set("InsMusic", "allowed_chats", value)

    @property
    def music_bots(self):
        return self.database.get("InsMusic", "music_bots", [])

    @music_bots.setter
    def music_bots(self, value):
        self.database.set("InsMusic", "music_bots", value)

    def check_spam(self, user_id):
        """Проверка на спам"""
        current_time = time.time()
        if user_id in self.spam_protection:
            last_time = self.spam_protection[user_id]
            if current_time - last_time < 5:
                return False
        self.spam_protection[user_id] = current_time
        return True

    async def delete_after(self, message, seconds):
        """Удаляет сообщение через указанное количество секунд"""
        await asyncio.sleep(seconds)
        try:
            await message.delete()
        except:
            pass

    @loader.command(
        ru_doc="<название> - Ищет музыку через @lyadownbot с выбором результата",
        en_doc="<title> - Search music via @lyadownbot with result selection"
    )
    async def миcmd(self, message):
        """Поиск музыки через @lyadownbot с выбором"""
        # Проверка на спам
        user_id = message.sender_id
        if not self.check_spam(user_id):
            await message.delete()
            error_message = await message.respond("Слишком много запросов! Подождите 5 секунд.")
            await self.delete_after(error_message, 3)
            return
        
        search_query = utils.get_args_raw(message)

        if not search_query:
            await message.delete()
            error_message = await message.respond("Укажите название песни!")
            await self.delete_after(error_message, 3)
            return

        try:
            await message.delete()
            searching_message = await message.respond(f"🔍 Ищу <b>{search_query}</b> в @lyadownbot...")

            # Создаем уникальный ID для этого поиска
            search_id = f"{user_id}_{int(time.time())}"
            
            # Регистрируем активный поиск
            self.active_searches[search_id] = {
                'user_id': user_id,
                'query': search_query,
                'chat_id': message.chat_id,
                'reply_to': message.id,
                'search_message': searching_message,
                'results': [],
                'message_ids': []
            }

            # Отправляем запрос боту
            bot_username = "lyadownbot"
            
            # Отправляем сообщение боту
            bot_entity = await self.client.get_entity(bot_username)
            sent_msg = await self.client.send_message(bot_entity, search_query)
            
            # Ждем ответ от бота (до 10 секунд)
            await asyncio.sleep(2)
            
            # Проверяем, есть ли уже результаты
            if not self.active_searches[search_id]['results']:
                # Если нет, ждем еще
                await asyncio.sleep(3)
            
            # Получаем историю чата с ботом
            async for msg in self.client.iter_messages(bot_entity, limit=20):
                if msg.id <= sent_msg.id:
                    continue
                
                # Проверяем, есть ли аудио в сообщении
                if msg.audio or msg.document:
                    # Проверяем, не сохранили ли мы уже это сообщение
                    if msg.id not in self.active_searches[search_id]['message_ids']:
                        self.active_searches[search_id]['results'].append(msg)
                        self.active_searches[search_id]['message_ids'].append(msg.id)
                        
                        # Ограничиваем до 10 результатов
                        if len(self.active_searches[search_id]['results']) >= 10:
                            break
            
            results = self.active_searches[search_id]['results']
            
            if not results:
                await searching_message.edit(f"❌ Ничего не найдено в @lyadownbot по запросу: {search_query}")
                await self.delete_after(searching_message, 5)
                # Очищаем данные поиска
                if search_id in self.active_searches:
                    del self.active_searches[search_id]
                return

            # Создаем клавиатуру с выбором
            buttons = []
            row = []
            
            for i, msg in enumerate(results[:10]):
                # Формируем название трека
                title = "Неизвестный трек"
                
                if msg.audio and msg.audio.title:
                    title = msg.audio.title
                    if msg.audio.performer:
                        title = f"{msg.audio.performer} - {title}"
                elif msg.document:
                    # Пробуем извлечь из атрибутов документа
                    for attr in msg.document.attributes:
                        if hasattr(attr, 'title') and attr.title:
                            title = attr.title
                            if hasattr(attr, 'performer') and attr.performer:
                                title = f"{attr.performer} - {title}"
                            break
                    else:
                        # Если не получилось, берем имя файла
                        if msg.file and msg.file.name:
                            title = msg.file.name
                        else:
                            title = f"Трек {i+1}"
                
                # Сокращаем название для кнопки
                btn_text = f"{i+1}. {title[:35]}"
                if len(title) > 35:
                    btn_text += "..."
                
                row.append(Button.inline(btn_text, data=f"lyaselect_{search_id}_{i}"))
                
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            
            if row:
                buttons.append(row)
            
            # Кнопка отмены
            buttons.append([Button.inline("❌ Отмена", data=f"lyacancel_{search_id}")])
            
            await searching_message.edit(
                f"🎵 Найдено {len(results)} треков в @lyadownbot. Выберите нужный:\n\nЗапрос: {search_query}",
                buttons=buttons
            )
            
            # Сохраняем ID сообщения с кнопками для последующего удаления
            self.active_searches[search_id]['menu_message'] = searching_message

        except Exception as error:
            await message.delete()
            error_message = await message.respond(f"Ошибка: {str(error)}")
            await self.delete_after(error_message, 3)
            if 'search_id' in locals() and search_id in self.active_searches:
                del self.active_searches[search_id]

    async def watcher(self, message):
        """Обработчик сообщений от ботов"""
        if not message.sender_id:
            return
            
        # Проверяем, есть ли активные поиски
        if not self.active_searches:
            return
            
        # Проверяем, от бота ли сообщение
        if not message.out and message.sender:
            # Проверяем для всех активных поисков
            for search_id, search_data in list(self.active_searches.items()):
                if search_data.get('completed'):
                    continue
                    
                # Проверяем, может это ответ на наш запрос
                if message.audio or message.document:
                    # Сохраняем результат
                    if message.id not in search_data['message_ids']:
                        search_data['results'].append(message)
                        search_data['message_ids'].append(message.id)
                        
                        # Обновляем сообщение с результатами
                        if len(search_data['results']) >= 10:
                            # Достигнут лимит, обновляем меню если оно есть
                            pass

    async def on_callback_query(self, call):
        """Обработчик нажатий на инлайн-кнопки"""
        user_id = call.sender_id
        data = call.data.decode()
        
        # Обработка отмены
        if data.startswith("lyacancel_"):
            search_id = data.replace("lyacancel_", "")
            
            if search_id in self.active_searches:
                await call.answer("❌ Поиск отменен")
                await call.delete()
                del self.active_searches[search_id]
            else:
                await call.answer("❌ Сессия устарела", alert=True)
                await call.delete()
            return
        
        # Обработка выбора трека
        if data.startswith("lyaselect_"):
            parts = data.split("_")
            if len(parts) < 3:
                await call.answer("❌ Ошибка данных", alert=True)
                return
                
            search_id = f"{parts[1]}_{parts[2]}"
            try:
                index = int(parts[3])
            except:
                await call.answer("❌ Ошибка индекса", alert=True)
                return
            
            if search_id not in self.active_searches:
                await call.answer("❌ Сессия поиска устарела", alert=True)
                await call.delete()
                return
            
            search_data = self.active_searches[search_id]
            
            if user_id != search_data['user_id']:
                await call.answer("❌ Это не ваш поиск", alert=True)
                return
            
            if index < 0 or index >= len(search_data['results']):
                await call.answer("❌ Неверный выбор", alert=True)
                return
            
            try:
                selected_msg = search_data['results'][index]
                
                await call.answer("✅ Отправляю трек...")
                
                # Удаляем сообщение с кнопками
                await call.delete()
                
                # Пересылаем выбранный трек
                await self.client.send_file(
                    search_data['chat_id'],
                    selected_msg.audio or selected_msg.document,
                    caption=f"🎵 <b>{search_data['query']}</b>\n🔍 Найдено через @lyadownbot",
                    parse_mode='html',
                    reply_to=search_data['reply_to']
                )
                
                # Очищаем данные поиска
                del self.active_searches[search_id]
                
            except Exception as e:
                await call.answer(f"❌ Ошибка: {str(e)}", alert=True)

    # Остальные методы модуля (addmcmd, delmcmd, listmcmd, и т.д.) остаются без изменений
    # Для краткости они не включены, но их нужно добавить из предыдущего кода
