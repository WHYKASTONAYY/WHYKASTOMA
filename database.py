import sqlite3
import logging

# Set up logging for debugging database operations
logger = logging.getLogger(__name__)

def init_db():
    """
    Initialize the SQLite database and create the 'users' table if it doesn't exist.
    Ensures the 'username' column is present for backward compatibility.
    """
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        # Create the table with user_id, username, and balance columns
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 100.0)''')
        # Check if 'username' column exists for older databases
        c.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in c.fetchall()]
        if 'username' not in columns:
            c.execute("ALTER TABLE users ADD COLUMN username TEXT")
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        conn.close()

def user_exists(user_id):
    """
    Check if a user with the given user_id exists in the database.
    
    Args:
        user_id (int): The Telegram user ID to check.
    
    Returns:
        bool: True if the user exists, False otherwise.
    """
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return c.fetchone() is not None
    except sqlite3.Error as e:
        logger.error(f"Database error in user_exists: {e}")
        return False

def get_user_balance(user_id):
    """
    Retrieve the balance for a given user_id.
    
    Args:
        user_id (int): The Telegram user ID.
    
    Returns:
        float: The user's balance, or 0 if the user doesn't exist.
    """
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            result = c.fetchone()
            return result[0] if result else 0
    except sqlite3.Error as e:
        logger.error(f"Database error in get_user_balance: {e}")
        return 0

def update_user_balance(user_id, new_balance):
    """
    Update the balance for a given user_id.
    
    Args:
        user_id (int): The Telegram user ID.
        new_balance (float): The new balance to set.
    """
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in update_user_balance: {e}")

def update_user_username(user_id, username):
    """
    Update the username for a given user_id.
    
    Args:
        user_id (int): The Telegram user ID.
        username (str): The new username to set.
    """
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in update_user_username: {e}")