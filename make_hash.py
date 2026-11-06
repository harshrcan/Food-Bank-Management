"""Create a bcrypt hash for a test user, then paste it into an UPDATE.
pip install bcrypt
python make_hash.py "Password123!"
"""
import sys, bcrypt
pw = sys.argv[1] if len(sys.argv) > 1 else "Password123!"
h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
print(h)
print(f"\nUPDATE foodbank.User_Account SET Password_Hash='{h}';")

# Login check in your app:
#   row = SELECT User_ID, Password_Hash, Role FROM User_Account WHERE Email=%s AND Is_Active=1
#   ok  = bcrypt.checkpw(entered_pw.encode(), row['Password_Hash'].encode())
