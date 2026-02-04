import os
from dotenv import load_dotenv
from google import genai

# Load .env
load_dotenv()

# Create client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("\nAvailable Gemini Models")
print("=" * 50)

models = client.models.list()

for m in models:
    print(f"Name        : {m.name}")
    print(f"Description : {m.description}")

    # Some models expose input/output types
    if hasattr(m, "input_token_limit"):
        print(f"Input Tokens: {m.input_token_limit}")
    if hasattr(m, "output_token_limit"):
        print(f"Output Tokens: {m.output_token_limit}")

    print("-" * 50)
