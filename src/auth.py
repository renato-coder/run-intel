"""
One-time OAuth2 authorization script for Whoop.

Run this once to connect your Whoop account:
    python src/auth.py

It will print an authorization URL. Open it in your browser, approve access,
then paste the full redirect URL back here to complete the flow.
"""

import urllib.parse

from whoop import WhoopClient


def main():
    client = WhoopClient()

    # Step 1: Generate and display the auth URL (includes CSRF state param)
    auth_url, state = client.generate_auth_url()
    print("\n=== Whoop Authorization ===\n")
    print("1. Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print("2. Log in and authorize the app.")
    print("3. You'll be redirected. Copy the FULL redirect URL from your browser.\n")

    # Step 2: Get the redirect URL from the user
    redirect_url = input("Paste the full redirect URL here: ").strip()

    # Step 3: Parse the authorization code and validate state
    parsed = urllib.parse.urlparse(redirect_url)
    query_params = urllib.parse.parse_qs(parsed.query)

    if "code" not in query_params:
        print("\nError: No authorization code found in URL.")
        print("Make sure you pasted the complete redirect URL.")
        return

    # Validate state to prevent CSRF attacks
    returned_state = query_params.get("state", [None])[0]
    if returned_state != state:
        print("\nError: OAuth state mismatch — possible CSRF attack.")
        print("Please try again.")
        return

    code = query_params["code"][0]

    # Step 4: Exchange the code for tokens
    print("\nExchanging code for tokens...")
    client.exchange_code(code)

    # Step 5: Confirm success by fetching the user profile
    profile = client.get_profile()
    first = profile.get("first_name", "")
    last = profile.get("last_name", "")
    print(f"\nSuccess! Authenticated as {first} {last}.")
    print("Tokens saved to data/tokens.json.\n")


if __name__ == "__main__":
    main()
