import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from the .env file
load_dotenv(override=True)

# Initialize the Groq client
try:
    client = Groq()
    
    print("🔄 Asking Groq about the capital of Thailand...")

    # Send the question to the model
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "user", "content": "What is the capital of Thailand?"}
        ],
        max_tokens=50
    )

    print("\n✅ Response from Groq:")
    print(completion.choices[0].message.content.strip())

except Exception as e:
    print(f"\n❌ Error: {e}")

