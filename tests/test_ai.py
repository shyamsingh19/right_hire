import os
from dotenv import load_dotenv
import os
from dotenv import load_dotenv
from cerebras.cloud.sdk import Cerebras
from groq import Groq

# Load environment variables from the .env file
load_dotenv(override=True)


# Initialize the Groq client
def groq_test():
    try:
        client = Groq()

        print("🔄 Asking Groq about the capital of Thailand...")

        # Send the question to the model
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": "Explain how an API works in 2 sentences?"}],
            max_tokens=50,
        )

        print("\n✅ Response from Groq:")
        print(completion.choices[0].message.content.strip())

    except Exception as e:
        print(f"\n❌ Error: {e}")


def cerebras_test(model_id: str):
    try:
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError(
                "CEREBRAS_API_KEY is not set in the environment variables."
            )

        client = Cerebras(api_key=api_key)

        print(f"🔄 Asking Cerebras ({model_id}) about the capital of Thailand...")

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": "Explain how an API works in 2 sentences?",
                }
            ],
            model=model_id,
            max_tokens=500,
        )

        print(f"\n✅ Response from Cerebras ({model_id}):")
        print(chat_completion.choices[0].message.content.strip())

    except Exception as e:
        print(f"\n❌ Error with {model_id}: {e}")


if __name__ == "__main__":
    print("Starting tests...\n")

    # Test Gemma 4 31B
    cerebras_test("gemma-4-31b")

    print("\n-----------------------------\n")

    # Test GPT-OSS 120B
    cerebras_test("gpt-oss-120b")

    print("\nTests completed.")
