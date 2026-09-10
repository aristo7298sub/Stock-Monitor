from pathlib import Path

import requests


def main():
    destination = Path(__file__).resolve().parents[1] / "web" / "public"
    destination.mkdir(parents=True, exist_ok=True)
    sites = {"msft": "www.microsoft.com", "nvda": "www.nvidia.com", "amzn": "www.amazon.com", "googl": "abc.xyz", "aapl": "www.apple.com", "tsm": "www.tsmc.com"}
    for symbol, host in sites.items():
        target = destination / f"{symbol}.ico"
        if target.is_file():
            print(f"{symbol}: cached")
            continue
        try:
            response = requests.get(f"https://{host}/favicon.ico", timeout=(5, 12))
            response.raise_for_status()
            content = response.content
            if content[:4] not in (b"\x00\x00\x01\x00", b"\x89PNG"):
                raise ValueError("Response is not an ICO or PNG")
            target.write_bytes(content)
            print(f"{symbol}: {len(content)} bytes")
        except (requests.RequestException, ValueError) as error:
            print(f"{symbol}: text monogram fallback ({type(error).__name__})")


if __name__ == "__main__":
    main()