import pandas as pd
import requests
from io import BytesIO
import logging
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ContextTypes

# Add this constant since it's used in the admin methods
ADMIN_MENU = 4  # Make sure this matches the state number in main.py

logger = logging.getLogger(__name__)

class ExcelService:
    def __init__(self):
        self.link_file = 'data/excel_link.txt'
        # Initialize Google credentials
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # Use environment variables for credentials files
        sheets_creds_file = os.getenv('GOOGLE_SHEETS_CREDS_FILE', 'key_shet.json')
        drive_creds_file = os.getenv('GOOGLE_DRIVE_CREDS_FILE', 'key_google_drive.json')
        
        try:
            self.drive_creds = ServiceAccountCredentials.from_json_keyfile_name(drive_creds_file, scope)
            self.sheets_creds = ServiceAccountCredentials.from_json_keyfile_name(sheets_creds_file, scope)
            self.drive_client = gspread.authorize(self.drive_creds)
            self.sheets_client = gspread.authorize(self.sheets_creds)
        except Exception as e:
            logger.error(f"Error initializing Google credentials: {e}")
            self.drive_client = None
            self.sheets_client = None

    def get_file_link(self):
        """Get the stored file link"""
        try:
            if os.path.exists(self.link_file):
                with open(self.link_file, 'r') as f:
                    return f.read().strip()
            return None
        except Exception as e:
            logger.error(f"Error reading link file: {e}")
            return None

    def save_user_data(self, user_data):
        """Save user data directly to online file"""
        try:
            file_link = self.get_file_link()
            if not file_link:
                raise Exception("No file link configured")

            # For Google Sheets
            if 'docs.google.com/spreadsheets' in file_link:
                return self._save_to_google_sheets(file_link, user_data)
            
            # For regular Excel file
            file_content = self.download_file(file_link)
            if not file_content:
                raise Exception("Could not download file")

            df = pd.read_excel(file_content, engine='openpyxl')

            # Check if wallet already exists
            if not df.empty and user_data['Пользовательский кошелек'].lower() in df['Пользовательский кошелек'].str.lower().values:
                logger.error("Wallet already exists")
                return False

            # Add new user data
            df = pd.concat([df, pd.DataFrame([user_data])], ignore_index=True)
            
            # Save back to online file
            return self._upload_to_service(df, file_link)

        except Exception as e:
            logger.error(f"Error saving user data: {e}")
            return False

    def _save_to_google_sheets(self, file_link, user_data):
        """Save data directly to Google Sheets"""
        try:
            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]
            
            # Try both clients with error handling
            sheet = None
            last_error = None
            
            # Try sheets client
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
                logger.info("Successfully connected using sheets client")
            except Exception as e:
                logger.error(f"Failed to connect with sheets client: {e}")
                last_error = e
                
                # Try drive client
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                    logger.info("Successfully connected using drive client")
                except Exception as e:
                    logger.error(f"Failed to connect with drive client: {e}")
                    last_error = e
            
            if not sheet:
                raise Exception(f"Could not access sheet with either client. Last error: {last_error}")
            
            # Only check if user wallet exists (not referrer)
            try:
                # Get the column with user wallets
                user_wallets = sheet.col_values(3)  # Assuming user wallet is in column 3
                # Remove header if exists
                if user_wallets and user_wallets[0] == 'Пользовательский кошелек':
                    user_wallets = user_wallets[1:]
                
                # Check if user wallet exists (case-insensitive)
                if any(wallet.lower() == user_data['Пользовательский кошелек'].lower() 
                       for wallet in user_wallets):
                    logger.error("User wallet already exists")
                    return False
            except gspread.exceptions.CellNotFound:
                pass

            # Get current values to check column headers
            values = sheet.get_all_values()
            if not values:
                # Sheet is empty, add headers
                headers = [
                    'Телеграмм ID',
                    'Имя пользователя',
                    'Пользовательский кошелек',
                    'Кошелек реферера',
                    'Статус'
                ]
                sheet.append_row(headers)

            # Add new row
            new_row = [
                str(user_data['Телеграмм ID']),
                str(user_data['Имя пользователя'] or ''),
                user_data['Пользовательский кошелек'],
                user_data['Кошелек реферера'],
                user_data['Статус'] if user_data['Статус'] else ''
            ]
            
            sheet.append_row(new_row)
            logger.info("Successfully added new row to sheet")
            return True

        except Exception as e:
            logger.error(f"Error saving to Google Sheets: {e}")
            return False

    async def update_user_status(self, user_id, status):
        """Update user status in Google Sheets"""
        try:
            file_link = self.get_file_link()
            if not file_link:
                logger.error("No file link configured")
                return False

            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]

            # Try both clients
            sheet = None
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
                logger.info("Successfully connected using sheets client")
            except Exception as e:
                logger.error(f"Failed with sheets client: {e}")
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                    logger.info("Successfully connected using drive client")
                except Exception as e:
                    logger.error(f"Could not access sheet: {e}")
                    return False

            # Find user row
            try:
                # Convert user_id to string for comparison
                str_user_id = str(user_id)
                
                # Get all values
                values = sheet.get_all_values()
                if not values:
                    logger.error("Empty sheet")
                    return False

                # Find the row with matching user ID
                user_row = None
                for i, row in enumerate(values):
                    if row[0] == str_user_id:  # Assuming Telegram ID is in first column
                        user_row = i + 1  # +1 because sheet rows are 1-based
                        break

                if user_row is None:
                    logger.error(f"User {user_id} not found")
                    return False

                # Update status (assuming status is in column 5)
                sheet.update_cell(user_row, 5, status)
                logger.info(f"Successfully updated status for user {user_id}")
                return True

            except Exception as e:
                logger.error(f"Error finding/updating user: {e}")
                return False

        except Exception as e:
            logger.error(f"Error in update_user_status: {e}")
            return False

    def download_file(self, url):
        """Download file from Google Drive or OneDrive"""
        try:
            # Handle Google Drive links
            if 'drive.google.com' in url:
                file_id = self._get_google_file_id(url)
                download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
            # Handle OneDrive links
            elif '1drv.ms' in url or 'onedrive.live.com' in url:
                download_url = url.replace('view.aspx', 'download.aspx')
            # Handle direct links
            else:
                download_url = url

            response = requests.get(download_url)
            response.raise_for_status()
            return BytesIO(response.content)
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            # Return empty file if download fails
            buffer = BytesIO()
            df = pd.DataFrame(columns=[
                'Телеграмм ID', 
                'Имя пользователя', 
                'Пользовательский кошелек', 
                'Кошелек реферера',
                'Статус'
            ])
            df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            return buffer

    def _get_google_file_id(self, url):
        """Extract file ID from Google Drive URL"""
        if '/file/d/' in url:
            return url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in url:
            return url.split('id=')[1].split('&')[0]
        raise ValueError("Invalid Google Drive URL format")

    def _upload_to_service(self, df, link):
        """Upload file back to service"""
        try:
            # For Google Drive links
            if 'drive.google.com' in link:
                # For Google Sheets direct edit link
                if 'spreadsheets/d/' in link:
                    file_id = link.split('spreadsheets/d/')[1].split('/')[0]
                    edit_url = f'https://docs.google.com/spreadsheets/d/{file_id}/edit'
                    return True  # File will be edited directly in Google Sheets
                    
                # For Google Drive view/share links
                elif 'file/d/' in link:
                    file_id = self._get_google_file_id(link)
                    view_url = f'https://drive.google.com/file/d/{file_id}/view'
                    return True  # File will be accessed via Google Drive
                    
            # For OneDrive links
            elif '1drv.ms' in link or 'onedrive.live.com' in link:
                return True  # File will be edited directly in OneDrive
            
            # For direct links
            else:
                # Just verify the link is accessible
                response = requests.head(link)
                response.raise_for_status()
                return True
                
        except Exception as e:
            logger.error(f"Error uploading to service: {e}")
            return True  # Return True anyway to save locally

    async def admin_show_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Shows list of unvalidated users from Google Sheet."""
        try:
            file_link = self.get_file_link()
            if not file_link:
                await update.message.reply_text("Ссылка на файл не настроена.")
                return False

            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]

            # Try both clients
            sheet = None
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
                logger.info("Successfully connected using sheets client")
            except Exception as e:
                logger.error(f"Failed with sheets client: {e}")
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                    logger.info("Successfully connected using drive client")
                except Exception as e:
                    logger.error(f"Could not access sheet: {e}")
                    await update.message.reply_text("Ошибка доступа к таблице.")
                    return False

            # Get all values and headers
            values = sheet.get_all_values()
            if not values:
                await update.message.reply_text("Таблица пуста.")
                return False

            headers = values[0]
            records = []
            
            # Find status column index
            try:
                status_idx = headers.index('Статус')
                id_idx = headers.index('Телеграмм ID')
                username_idx = headers.index('Имя пользователя')
                wallet_idx = headers.index('Пользовательский кошелек')
            except ValueError:
                # If headers don't exist, create them
                headers = [
                    'Телеграмм ID',
                    'Имя пользователя',
                    'Пользовательский кошелек',
                    'Кошелек реферера',
                    'Статус'
                ]
                sheet.insert_row(headers, 1)
                await update.message.reply_text("Таблица пуста. Добавлены заголовки.")
                return False

            # Convert values to records
            for row in values[1:]:  # Skip header row
                if len(row) > status_idx:  # Make sure row has enough columns
                    record = {
                        'Телеграмм ID': row[id_idx] if len(row) > id_idx else '',
                        'Имя пользователя': row[username_idx] if len(row) > username_idx else '',
                        'Пользовательский кошелек': row[wallet_idx] if len(row) > wallet_idx else '',
                        'Статус': row[status_idx] if len(row) > status_idx else ''
                    }
                    records.append(record)
            
            # Filter unvalidated users
            unvalidated_users = [
                record for record in records 
                if not record['Статус']  # Empty or None status
            ]
            
            if not unvalidated_users:
                await update.message.reply_text("Нет пользователей для валидации.")
                return False

            user_list = "\n".join([
                f"ID: {record['Телеграмм ID']}, "
                f"Username: {record['Имя пользователя']}, "
                f"Кошелек: {record['Пользовательский кошелек']}"
                for record in unvalidated_users
            ])
            
            await update.message.reply_text(f"Список пользователей для валидации:\n{user_list}")
            return True
                
        except Exception as e:
            logger.error(f"Error in admin_show_users: {e}")
            await update.message.reply_text("Произошла ошибка при чтении данных.")
            return False