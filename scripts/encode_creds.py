"""
ENCODE GOOGLE CREDENTIALS
Google認証JSONファイルをBase64文字列にエンコードするスクリプト

RenderなどのPaaS環境変数に設定するために使用します。
"""

import base64
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))
from config import settings

def encode_credentials():
    """Encode credentials file to base64 string."""
    
    # Try to find credentials file
    # Default locations
    possible_paths = [
        "credentials.json",
        "google-credentials.json",
        "service-account.json",
        "../credentials/google_service_account.json", # Typical location in previous project
    ]
    
    target_file = None
    
    # Check if a path was provided as argument
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        # Check default paths
        import glob
        json_files = glob.glob("*.json")
        json_files = [f for f in json_files if "cred" in f or "service" in f]
        
        if json_files:
            target_file = json_files[0]
    
    if not target_file or not os.path.exists(target_file):
        print("❌ Credentials file not found.")
        print("Usage: python scripts/encode_creds.py <path_to_json_file>")
        print("Or place a .json file in the current directory.")
        return

    print(f"🔑 Encoding {target_file}...")
    
    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # Validate JSON
            json.loads(content)
            
            # Encode
            encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            print("\n✅ Encoded successfully!")
            print("-" * 20)
            print("GOOGLE_CREDENTIALS_JSON=" + encoded)
            print("-" * 20)
            print("Set this value in your .env file or Render Environment Variables.")
            
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    encode_credentials()
