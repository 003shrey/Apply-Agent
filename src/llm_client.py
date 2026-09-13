import os


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call the configured LLM provider and return generated text."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()

    if not provider:
        raise RuntimeError(
            "Missing LLM_PROVIDER. Set it to anthropic, openai, or gemini."
        )

    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY environment variable.")

    if not model:
        model_defaults = {
            "anthropic": "claude-sonnet-4-5",
            "openai": "gpt-4o-mini",
            "gemini": "gemini-2.5-flash",
        }
        model = model_defaults.get(provider)

    if provider == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )

        return "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()

    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
        )
        return response.output_text.strip()

    if provider in {"gemini", "google", "google-gemini"}:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            ),
        )
        return response.text.strip()

    raise RuntimeError(
        f"Unsupported LLM_PROVIDER '{provider}'. "
        "Use anthropic, openai, or gemini."
    )