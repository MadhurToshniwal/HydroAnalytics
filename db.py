# db.py - Complete and corrected version
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pandas as pd
from contextlib import contextmanager
from passlib.context import CryptContext
import logging
from typing import Optional, Dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_URI = "mysql+mysqlconnector://Mariobot:mariobot%40123@103.224.245.53:3307/may_2025_data"
engine = create_engine(DB_URI)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@contextmanager
def get_db_session():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {str(e)}")
        return False

def get_password_hash(password: str) -> str:
    """Generate a password hash"""
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Password hashing failed: {str(e)}")
        raise

def get_user(username: str) -> Optional[Dict]:
    """Retrieve a user from the database"""
    try:
        with get_db_session() as session:
            result = session.execute(
                text("SELECT * FROM login WHERE username = :username"),
                {"username": username}
            )
            user = result.fetchone()
            if user:
                return dict(zip(result.keys(), user))
            logger.info(f"No user found with username: {username}")
            return None
    except Exception as e:
        logger.error(f"Database error in get_user: {str(e)}")
        return None

def create_user(username: str, password: str, is_admin: bool = False) -> bool:
    """Create a new user in the database"""
    try:
        with get_db_session() as session:
            # Check if user already exists
            existing_user = session.execute(
                text("SELECT id FROM login WHERE username = :username"),
                {"username": username}
            ).fetchone()
            
            if existing_user:
                logger.warning(f"User {username} already exists")
                return False
                
            # Create new user
            session.execute(
                text("""
                    INSERT INTO login (username, password_hash, is_admin)
                    VALUES (:username, :password_hash, :is_admin)
                """),
                {
                    "username": username,
                    "password_hash": get_password_hash(password),
                    "is_admin": is_admin
                }
            )
            session.commit()
            logger.info(f"Successfully created user: {username}")
            return True
    except Exception as e:
        logger.error(f"Database error in create_user: {str(e)}")
        return False

def fetch_data(table_name, 
               start_date=None, 
               end_date=None, 
               date_column='data_date',
               filter_column=None,
               filter_value=None):
    """
    Enhanced data fetching with multiple filter capabilities
    Args:
        table_name (str): Name of the database table
        start_date (str): Start date for filtering (YYYY-MM-DD format)
        end_date (str): End date for filtering (YYYY-MM-DD format)
        date_column (str): Name of the date column to filter on
        filter_column (str): Additional column to filter on
        filter_value (str): Value for the additional filter column
    
    Returns:
        pd.DataFrame: DataFrame containing the query results
    """
    try:
        with get_db_session() as session:
            # Base query
            query = text(f"SELECT * FROM {table_name}")
            conditions = []
            params = {}

            # Date range filtering
            if start_date and end_date and date_column:
                conditions.append(f"{date_column} BETWEEN :start_date AND :end_date")
                params.update({
                    'start_date': start_date,
                    'end_date': end_date
                })

            # Column-value filtering
            if filter_column and filter_value is not None:
                conditions.append(f"{filter_column} = :filter_value")
                params['filter_value'] = filter_value

            # Build final query
            if conditions:
                query = text(f"""
                    SELECT * FROM {table_name}
                    WHERE {' AND '.join(conditions)}
                """)

            # Add ordering if date column exists
            if date_column:
                query = text(f"{str(query)} ORDER BY {date_column}")

            # Execute query
            result = session.execute(query, params)
            
            # Convert to DataFrame
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
            
            logger.info(f"Fetched {len(df)} rows from {table_name}")
            return df

    except Exception as e:
        logger.error(f"Database error in fetch_data: {str(e)}")
        return pd.DataFrame()
