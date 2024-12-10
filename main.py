import os
from dotenv import load_dotenv
import re
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from translations import TRANSLATIONS
from excel_service import ExcelService

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
START, LANGUAGE_SELECT, WALLET_TYPE, USER_WALLET, REFERRER_WALLET, ADMIN_MENU, VALIDATE_USER = range(7)

# Get environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

class WalletBot:
    def __init__(self, token, admin_id):
        global ADMIN_ID
        self.token = token
        self.users_data = []
        ADMIN_ID = admin_id
        self.application = None
        self.excel_service = ExcelService()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation."""
        context.user_data.clear()
        
        if update.effective_user.id == ADMIN_ID:
            if not os.path.exists('data/excel_link.txt'):
                await update.message.reply_text(
                    "👋 Привет, администратор!\n\n"
                    "❗️ Для начала работы необходимо:\n"
                    "Установить ссылку на Excel файл командой:\n"
                    "/setlink <ссылка на Excel>\n\n"
                    "❗️ Требования к файлу Excel:\n"
                    "- Колонки:\n"
                    "  • Телеграмм ID\n"
                    "  • Имя пользователя\n"
                    "  • Пользовательский кошелек\n"
                    "  • ��шелек реферера\n"
                    "  • Статус"
                )
                return ConversationHandler.END
            
            context.user_data['language'] = 'ru'
            keyboard = [
                ['Список пользователей'],
                ['Валидация пользователя']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Панель администратора\n\n"
                "🔗 Текущая ссылка на файл: /getlink",
                reply_markup=reply_markup
            )
            return ADMIN_MENU

        # Check if admin has set up the file
        if not os.path.exists('data/excel_link.txt'):
            await update.message.reply_text(
                "⚠️ Бот находится в процессе настройки.\n"
                "Пожалуйста, попробуйте позже."
            )
            return ConversationHandler.END

        keyboard = [
            ['English 🇬🇧', '中文 🇨🇳'],
            ['Indonesia 🇮🇩', 'Filipino 🇵🇭'],
            ['Tiếng Việt 🇻🇳', 'Русский 🇷🇺']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Please select your language\n"
            "请选择您的语言\n"
            "Pilih bahasa Anda\n"
            "Piliin ang iyong wika\n"
            "Vui lòng chọn ngôn ngữ của bạn\n"
            "Пожалуйста, выберите язык",
            reply_markup=reply_markup
        )
        return LANGUAGE_SELECT

    async def select_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles language selection."""
        text = update.message.text
        
        # Маппинг текста кнопок на коды языков
        language_map = {
            'English 🇬🇧': 'en',
            '中文 🇨🇳': 'zh',
            'Indonesia 🇮🇩': 'id',
            'Filipino 🇵🇭': 'ph',
            'Tiếng Việt 🇻🇳': 'vi',
            'Русский 🇷🇺': 'ru'
        }
        
        language = language_map.get(text)
        if not language:
            await update.message.reply_text("Please select a language using the buttons")
            return LANGUAGE_SELECT
            
        # Сохраняем выбранный язык
        context.user_data['language'] = language
        
        # Показы��аем приветственное сообщение на выбранном языке
        keyboard = [['Start']]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            TRANSLATIONS[language]['welcome'],
            reply_markup=reply_markup
        )
        return START

    async def user_start_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Begins the user registration process."""
        language = context.user_data.get('language', 'en')
        try:
            # Уведомление администратора о новом пользователе (всегда на русском)
            if self.application and ADMIN_ID:
                try:
                    await self.application.bot.send_message(
                        chat_id=ADMIN_ID, 
                        text=f"🆕 Новый пользователь начал регистрацию: @{update.effective_user.username or 'без username'}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                    pass

            # Use translated button text
            keyboard = [[TRANSLATIONS[language]['evm_wallet']]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                TRANSLATIONS[language]['select_wallet'],
                reply_markup=reply_markup
            )
            return WALLET_TYPE

        except Exception as e:
            logger.error(f"Error in user_start_registration: {e}")
            await update.message.reply_text(TRANSLATIONS[language]['error_try_again'])
            return ConversationHandler.END

    async def select_wallet_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles wallet type selection."""
        language = context.user_data.get('language', 'en')
        wallet_type = update.message.text
        
        # Check against translated button text
        if wallet_type != TRANSLATIONS[language]['evm_wallet']:
            await update.message.reply_text(TRANSLATIONS[language]['select_wallet_error'])
            return WALLET_TYPE
            
        # Store the wallet type
        context.user_data['wallet_type'] = 'EVM'
        
        # Show instructions in selected language without back button
        await update.message.reply_text(
            TRANSLATIONS[language]['enter_wallet']
        )
        return USER_WALLET

    async def collect_user_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collects and validates the user's wallet address."""
        language = context.user_data.get('language', 'en')
        try:
            user_wallet = update.message.text.strip()
            
            # Validate EVM wallet format
            if not self.is_valid_eth_address(user_wallet):
                await update.message.reply_text(
                    TRANSLATIONS[language]['invalid_wallet']
                )
                return USER_WALLET
            
            # Store the wallet in context
            context.user_data['user_wallet'] = user_wallet
            
            # Ask for referrer wallet without back button
            await update.message.reply_text(
                TRANSLATIONS[language]['enter_referral']
            )
            return REFERRER_WALLET

        except Exception as e:
            logger.error(f"Error in collect_user_wallet: {e}")
            await update.message.reply_text(TRANSLATIONS[language]['error_try_again'])
            return ConversationHandler.END

    async def admin_show_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Shows list of unvalidated users."""
        try:
            # Use excel service to show users
            await self.excel_service.admin_show_users(update, context)
            # Always return to ADMIN_MENU
            return ADMIN_MENU
            
        except Exception as e:
            logger.error(f"Error in admin_show_users: {e}")
            await update.message.reply_text("Произошла ошибка при чтении данных.")
            return ADMIN_MENU

    async def admin_start_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Begins user validation process."""
        try:
            # Show list of users
            success = await self.excel_service.admin_show_users(update, context)
            
            if success:
                # Ask for ID and move to VALIDATE_USER state
                await update.message.reply_text(
                    "\n⚡️ Введите ID пользователя для подтверждения:"
                )
                return VALIDATE_USER
            else:
                # If there was an error or no users, return to admin menu
                return ADMIN_MENU
            
        except Exception as e:
            logger.error(f"Error in admin_start_validation: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте снова через /start")
            return ADMIN_MENU

    async def confirm_user_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirms user validation."""
        try:
            user_id = update.message.text
            
            # Verify ID is a number
            try:
                user_id = int(user_id)
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите корректный Telegram ID.")
                return VALIDATE_USER

            # Update status using excel service
            success = await self.excel_service.update_user_status(user_id, 'Подтвержден')
            if success:
                try:
                    # Send notification to user
                    await self.application.bot.send_message(
                        chat_id=user_id, 
                        text="🎉 Поздравляем! Ваша регистрация подтверждена."
                    )
                    
                    await update.message.reply_text(
                        f"✅ Пользователь {user_id} успешно подтвержден!",
                        reply_markup=ReplyKeyboardMarkup([['Список пользователей'], ['Валидация пользователя']], resize_keyboard=True)
                    )
                except Exception as e:
                    await update.message.reply_text(f"Пользователь подтвержден, но не удалось отправить ему уведомление: {e}")
            else:
                await update.message.reply_text(
                    "❌ Не удалось найти или подтвердить пользователя.",
                    reply_markup=ReplyKeyboardMarkup([['Список пользователей'], ['Валидация пользователя']], resize_keyboard=True)
                )

            return ADMIN_MENU
            
        except Exception as e:
            logger.error(f"Error in confirm_user_validation: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте снова через /start")
            return ConversationHandler.END

    def is_valid_eth_address(self, address: str) -> bool:
        """Validates Ethereum address format."""
        # Check if address matches the format: 0x followed by 40 hex characters
        pattern = r'^0x[a-fA-F0-9]{40}$'
        return bool(re.match(pattern, address))

    async def save_user_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Saves the user data to Excel file."""
        language = context.user_data.get('language', 'en')
        try:
            # Handle /start command
            if update.message.text == '/start':
                return await self.start(update, context)

            referrer_wallet = update.message.text.strip()
            user_wallet = context.user_data.get('user_wallet')
            
            # Validate referrer wallet
            if not self.is_valid_eth_address(referrer_wallet):
                await update.message.reply_text(
                    TRANSLATIONS[language]['invalid_wallet']
                )
                return REFERRER_WALLET
            
            # Check if referrer wallet is the same as user wallet
            if referrer_wallet.lower() == user_wallet.lower():
                await update.message.reply_text(
                    TRANSLATIONS[language]['same_wallet']
                )
                return REFERRER_WALLET

            # Use excel service to save data
            user_data = {
                'Телеграмм ID': update.effective_user.id,
                'Имя пользователя': update.effective_user.username,
                'Пользовательский кошелек': user_wallet,
                'Кошелек реферера': referrer_wallet,
                'Статус': None
            }

            if self.excel_service.save_user_data(user_data):
                # Remove keyboard only after successful registration
                await update.message.reply_text(
                    "✅ Спасибо за регистрацию! Ожидайте подтверждения от администратора.",
                    reply_markup=ReplyKeyboardRemove()  # Remove keyboard here
                )
                # Notify admin about new registration
                if self.application:
                    await self.application.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"✅ Новая регистрация!\n"
                             f"👤 Пользователь: @{update.effective_user.username or 'без username'}\n"
                             f"📱 ID: {update.effective_user.id}\n"
                             f"💼 Кошелек: {user_wallet}\n"
                             f"👥 Реферер: {referrer_wallet}"
                    )
                return ConversationHandler.END
            else:
                raise Exception("Failed to save data")

        except Exception as e:
            logger.error(f"Error in save_user_data: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении данных. Пожалуйста, попробуйте позже."
            )
            return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels and ends the conversation."""
        await update.message.reply_text(
            'Операция отменена.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    async def shutdown(self):
        """Cleanup before shutdown"""
        if self.application:
            await self.application.shutdown()
    
    def run(self):
        """Runs the bot."""
        try:
            application = Application.builder().token(self.token).build()
            self.application = application

            # Set up conversation handler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', self.start)],
                states={
                    LANGUAGE_SELECT: [
                        CommandHandler('start', self.start),
                        MessageHandler(
                            filters.Regex('^(English 🇬🇧|中文 🇨🇳|Indonesia 🇮🇩|Filipino 🇵🇭|Tiếng Việt 🇻🇳|Русский 🇷🇺)$'), 
                            self.select_language
                        )
                    ],
                    START: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.user_start_registration)
                    ],
                    WALLET_TYPE: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.select_wallet_type)
                    ],
                    USER_WALLET: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.collect_user_wallet)
                    ],
                    REFERRER_WALLET: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_user_data)
                    ],
                    ADMIN_MENU: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.Regex('^Список пользователей$'), self.admin_show_users),
                        MessageHandler(filters.Regex('^Валидация пользователя$'), self.admin_start_validation),
                    ],
                    VALIDATE_USER: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_user_validation)
                    ],
                },
                fallbacks=[CommandHandler('cancel', self.cancel)]
            )

            # Add handlers
            application.add_handler(conv_handler)
            application.add_handler(CommandHandler('setlink', self.set_excel_link))
            application.add_handler(CommandHandler('getlink', self.get_excel_link))

            # Start the bot
            application.run_polling(allowed_updates=Update.ALL_TYPES)
            
        except Exception as e:
            logger.error(f"Error in run method: {e}")
            if self.application:
                self.application.stop()

    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Restarts the conversation."""
        context.user_data.clear()  # Clear user data
        return await self.start(update, context)  # Restart from beginning

    async def set_excel_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Saves the shared Excel file link"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        try:
            # Extract link from command
            link = ' '.join(context.args)
            if not link:
                await update.message.reply_text("Использование: /setlink <ссылка>")
                return
            
            # Save link to file
            with open('data/excel_link.txt', 'w') as f:
                f.write(link)
            
            await update.message.reply_text(
                "✅ Ссылка сохранена!\n\n"
                "Теперь вы може��е:\n"
                "1️⃣ Открыть файл по ссылке\n"
                "2️⃣ Просматривать изменения в реальном времени\n"
                "3️⃣ Редактировать данные\n\n"
                "Получить ссылку: /getlink"
            )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")

    async def get_excel_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sends the shared Excel file link"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        try:
            if os.path.exists('data/excel_link.txt'):
                with open('data/excel_link.txt', 'r') as f:
                    link = f.read().strip()
                await update.message.reply_text(
                    f"🔗 Ссылка на файл Excel:\n{link}\n\n"
                    "Откройте ссылку для просмотра и редактирования данных."
                )
            else:
                await update.message.reply_text(
                    "❌ Ссылка еще не установлена.\n"
                    "Используйте /setlink <ссылка> для установки."
                )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")

def main():
    bot = WalletBot(BOT_TOKEN, ADMIN_ID)
    bot.run()

if __name__ == '__main__':
    main()