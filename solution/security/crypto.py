
import os
import base64
import hmac
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv


# Load environment variables from the root .env file
load_dotenv()


def get_encryption_key():
    key = os.getenv("PII_ENCRYPTION_KEY")

    if not key:
        raise ValueError("PII_ENCRYPTION_KEY is missing")

    decoded_key = base64.b64decode(key)

    if len(decoded_key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")

    return decoded_key


def get_hmac_key():
    key = os.getenv("PII_HMAC_KEY")

    if not key:
        raise ValueError("PII_HMAC_KEY is missing")

    decoded_key = base64.b64decode(key)

    if len(decoded_key) < 32:
        raise ValueError("HMAC key must be at least 32 bytes")

    return decoded_key


def encrypt_text(plain_text):
    """Encrypt text using AES-256-GCM."""

    if plain_text is None:
        return None

    key = get_encryption_key()
    aes = AESGCM(key)

    # AES-GCM uses a unique 12-byte nonce for each encryption.
    nonce = os.urandom(12)

    encrypted_data = aes.encrypt(
        nonce,
        plain_text.encode("utf-8"),
        None
    )

    # Store nonce together with encrypted data.
    return nonce + encrypted_data


def decrypt_text(encrypted_data):
    """Decrypt data previously encrypted using encrypt_text."""

    if encrypted_data is None:
        return None

    key = get_encryption_key()
    aes = AESGCM(key)

    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]

    decrypted_data = aes.decrypt(
        nonce,
        ciphertext,
        None
    )

    return decrypted_data.decode("utf-8")


def phone_fingerprint(canonical_phone):
    """Create a deterministic HMAC fingerprint for phone matching."""

    key = get_hmac_key()

    fingerprint = hmac.new(
        key,
        canonical_phone.encode("utf-8"),
        hashlib.sha256
    )

    return fingerprint.hexdigest()
