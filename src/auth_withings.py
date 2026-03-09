"""
One-time OAuth2 authorization script for Withings.

Run this once to connect your Withings account:
    python src/auth_withings.py

It will print an authorization URL. Open it in your browser, authorize,
then paste the full redirect URL back here to complete the flow.
"""

import urllib.parse

from withings import WithingsClient


def main():
    client = WithingsClient()

    auth_url = client.generate_auth_url()
    print("\n=== Withings Authorization ===\n")
    print("1. Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print("2. Log in and authorize the app.")
    print("3. You'll be redirected. Copy the FULL redirect URL from your browser.\n")

    redirect_url = input("Paste the full redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    query_params = urllib.parse.parse_qs(parsed.query)

    if "code" not in query_params:
        print("\nError: No authorization code found in URL.")
        return

    code = query_params["code"][0]

    print("\nExchanging code for tokens (must happen within 30s)...")
    client.exchange_code(code)
    print("\nSuccess! Withings tokens saved.\n")


if __name__ == "__main__":
    main()
