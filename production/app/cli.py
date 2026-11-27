import asyncio, argparse, getpass
from .db import SessionLocal
from .models import User
from .security import hash_password
from sqlalchemy import select

async def create_admin(username,password):
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.username==username)):
            raise SystemExit("User already exists")
        db.add(User(username=username,password_hash=hash_password(password),role="admin",active=True))
        await db.commit()
    print("Admin account created.")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    c=sub.add_parser("create-admin"); c.add_argument("--username",required=True)
    a=parser.parse_args()
    if a.command=="create-admin":
        asyncio.run(create_admin(a.username,getpass.getpass("New admin password (14+ chars): ")))
