import os, psycopg2
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
load_dotenv(override=True)   # override=True ignores any old DATABASE_URL set on your PC

u = urlparse(os.environ["DATABASE_URL"])
print("user:", repr(u.username), "| password length:", len(u.password or ""),
      "| host:", u.hostname, "| port:", u.port, "| db:", u.path)

conn = psycopg2.connect(host=u.hostname, port=u.port, dbname=u.path.lstrip("/"),
                        user=u.username, password=unquote(u.password), sslmode="require")
print("connected")