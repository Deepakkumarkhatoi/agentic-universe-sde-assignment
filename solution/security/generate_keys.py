
import base64
import secrets
from pathlib import Path


def generate_keys():
    env_path = Path(".env")

    if env_path.exists():
        raise FileExistsError(
            ".env already exists. Do not overwrite your existing keys."
        )

    encryption_key = base64.b64encode(
        secrets.token_bytes(32)
    ).decode("utf-8")

    hmac_key = base64.b64encode(
        secrets.token_bytes(32)
    ).decode("utf-8")

    env_content = (
        f"PII_ENCRYPTION_KEY={encryption_key}\n"
        f"PII_HMAC_KEY={hmac_key}\n"
    )

    env_path.write_text(env_content, encoding="utf-8")

    print("Security keys generated successfully!")
    print("Keys saved in .env. Keep this file private.")


if __name__ == "__main__":
    generate_keys()
