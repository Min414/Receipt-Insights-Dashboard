import os, time
from dotenv import load_dotenv
from google import genai
from google.genai import types
load_dotenv(override=True)
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=30_000))
cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="low"))
for m in ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
    t = time.time()
    try:
        r = client.models.generate_content(model=m, contents="Say hello in five words.", config=cfg)
        print(m, "OK", f"{time.time()-t:.1f}s", r.text)
    except Exception as e:
        print(m, "FAILED", str(e)[:80])